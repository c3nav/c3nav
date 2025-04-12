import logging
from collections import deque, defaultdict
from dataclasses import dataclass
from functools import wraps
from itertools import groupby, chain
from operator import attrgetter
from typing import Callable, Iterable, NamedTuple, Optional

from django.conf import settings
from django.db import IntegrityError, transaction, DatabaseError
from django.db.models.expressions import F
from django.db.models.query_utils import Q
from django.utils import timezone

from c3nav.mapdata.models import MapUpdate, AltitudeArea, Level, Space, Area
from c3nav.mapdata.models.locations import SpecificLocation, LocationParentage, LocationAncestry, LocationAncestryPath
from c3nav.mapdata.models.update import MapUpdateJobStatus, MapUpdateJob
from c3nav.mapdata.permissions import active_map_permissions
from c3nav.mapdata.render.renderdata import LevelRenderData
from c3nav.mapdata.tasks import run_mapupdate_job
from c3nav.mapdata.utils.cache.changes import changed_geometries

logger = logging.getLogger('c3nav')


class CantStartMapUpdateJob(Exception):
    pass


@dataclass
class MapUpdateJobConfig:
    key: str
    title: str
    func: Callable[[tuple[MapUpdate, ...]], bool]
    eager: bool
    dependencies: frozenset[str]

    def run(self, mapupdates: tuple[MapUpdate, ...], *, nowait=True):
        logger.info(f'Running job: {self.title}')
        MapUpdate.last_update(nocache=True)
        try:
            job = mapupdates[-1].jobs.create(job_type=self.key, status=MapUpdateJobStatus.RUNNING)
        except IntegrityError:
            raise CantStartMapUpdateJob
        e = None
        with transaction.atomic():
            job: MapUpdateJob = MapUpdateJob.objects.select_for_update(nowait=nowait).get(pk=job.pk)
            try:
                with active_map_permissions.disable_access_checks():
                    had_effect = self.func(mapupdates)
            except Exception as e:
                job.update_status(MapUpdateJobStatus.FAILED)
                raise
            else:
                job.update_status(MapUpdateJobStatus.SUCCESS if had_effect else MapUpdateJobStatus.SKIPPED)
        if e:
            raise e


update_job_configs: dict[str, MapUpdateJobConfig] = {}


class MapUpdateJobCallable:
    def __init__(self, key: str, func: Callable[[tuple[MapUpdate, ...]], bool]):
        self.key = key
        self.func = func

    def __call__(self, mapupdates: tuple[MapUpdate, ...]) -> bool:
        return self.func(mapupdates)


def register_mapupdate_job(title: str, *, eager: bool = False,
                           dependencies: Iterable[MapUpdateJobCallable] = ()) -> (
        Callable[[Callable[[tuple[MapUpdate, ...]], bool]], MapUpdateJobCallable]
):
    """
    Register the decorated function as a mapupdate job.

    :param title: title to show to users
    :param eager: True if this should be run immediately if no celery is active (only if dependencies are eager too)
    :param dependencies: other functions that have been registered as functions that need to run before this one
    :return: True if the job did something, False if it was skipped cause no action was required
    """
    def wrapper(func: Callable[[tuple[MapUpdate, ...]], bool]) -> MapUpdateJobCallable:
        app_name = func.__module__.split('c3nav.', 1)[1].split('.', 1)[0]
        func_name = func.__name__
        key = f"{app_name}.{func_name}"
        if key in update_job_configs:
            raise TypeError(f"{key} already registered")

        update_job_configs[key] = MapUpdateJobConfig(
            key=key,
            title=title,
            func=func,
            eager=eager,
            dependencies=frozenset(dependency.key for dependency in dependencies),
        )
        return wraps(func)(MapUpdateJobCallable(key=key, func=func))

    return wrapper


def run_eager_mapupdate_jobs(mapupdate: MapUpdate):
    """
    Run all eager jobs, this function is to be called when creating a mapupdate, and only if celery is disabled
    """
    remaining_job_types = {job_type for job_type, job_config in update_job_configs.items() if job_config.eager}
    running_jobs = {job.job_type: job for job in MapUpdateJob.objects.filter(job_type__in=remaining_job_types,
                                                                             status=MapUpdateJobStatus.RUNNING)}

    done_jobs = set()
    while True:
        try:
            next_job_type = next(iter(job_type for job_type in remaining_job_types
                                      if not (update_job_configs[job_type].dependencies - done_jobs)))
        except StopIteration:
            break
        running_job = running_jobs.get(next_job_type)

        if running_job and check_running_job(running_job):
            logger.info(f"Job already running, this shouldn't happen: {next_job_type}")
            raise CantStartMapUpdateJob(f"Can't ran eager job because already running: {next_job_type}")

        try:
            update_job_configs[next_job_type].run((mapupdate,), nowait=False)
        except CantStartMapUpdateJob:
            raise CantStartMapUpdateJob(f"Can't ran eager job because race condition?: {next_job_type}")

        done_jobs.add(next_job_type)
        remaining_job_types.remove(next_job_type)


def run_mapupdate_jobs():
    """
    Run all jobs, blocking, this is for manage.py processupdates
    """
    remaining_job_types = set(update_job_configs.keys())
    done_jobs = set()

    # collect running jobs
    running_jobs = {job.job_type: job for job in MapUpdateJob.objects.filter(status=MapUpdateJobStatus.RUNNING)}

    while True:
        try:
            next_job_type = next(iter(job_type for job_type in remaining_job_types
                                      if not (update_job_configs[job_type].dependencies - done_jobs)))
        except StopIteration:
            break
        running_job = running_jobs.get(next_job_type)
        if running_job and check_running_job(running_job):
            logger.info(f"Job already running, why are you using processupdates?: {next_job_type}")
        else:
            try:
                run_job(next_job_type)
            except CantStartMapUpdateJob:
                logger.info(f"Couldn't start job, race condition?: {next_job_type}")
        done_jobs.add(next_job_type)
        remaining_job_types.remove(next_job_type)


def run_job(job_type: str, schedule_next=False):
    """
    Run job with whatever updates it can be ran with.
    This can throw an excpetion if it can't be run right now.
    """
    job_config = update_job_configs[job_type]

    last_job = MapUpdateJob.last_successful_or_skipped_job(job_type)
    if job_config.dependencies:
        last_dependency_jobs = tuple(MapUpdateJob.last_successful_or_skipped_job(dependency)
                                     for dependency in job_config.dependencies)
        if any(job is None for job in last_dependency_jobs):
            logger.info(f'Unfilfilled dependencies for job: {job_config.title}')
            return
        newest_update_id_for_job = min(job.mapupdate_id for job in last_dependency_jobs)
    else:
        newest_update_id_for_job = MapUpdate.last_update().update_id

    last_job_update_id = 0 if last_job is None else last_job.mapupdate_id

    if newest_update_id_for_job <= last_job_update_id:
        logger.info(f'No updates for job: {update_job_configs[job_type].title}')
        return

    job_config.run(tuple(MapUpdate.objects.filter(pk__gt=last_job_update_id, pk__lte=newest_update_id_for_job)))

    if schedule_next:
        schedule_available_mapupdate_jobs_as_tasks()


def check_running_job(running_job):
    if (timezone.now() - running_job.start).total_seconds() < 10:
        # job just started, don't try to timeout it
        return True

    try:
        # try to select_for_update this job and set it to timed out
        with transaction.atomic():
            job = MapUpdateJob.objects.select_for_update(nowait=True).get(pk=running_job.pk)
            job.status = MapUpdateJobStatus.TIMEOUT
            job.end = timezone.now()
            job.save()
            logger.info(f"Successfully timeouted job: {update_job_configs[running_job.job_type].title}")
    except DatabaseError:
        # job is running and row is still locked (so the process is still running)
        return True

    return False


def schedule_available_mapupdate_jobs_as_tasks(dependency: str = None):
    """
    Schedule job runs for all jobs, or jobs with the given dependency.
    """
    last_map_update_id = MapUpdate.last_update().update_id
    last_jobs = {}

    # collect running jobs
    running_jobs = {job.job_type: job for job in MapUpdateJob.objects.filter(status=MapUpdateJobStatus.RUNNING)}

    filtered_jobs = {}
    if dependency is not None:
        filtered_jobs = {job_type: job_config for job_type, job_config in update_job_configs.items()
                         if dependency in job_config.dependencies}
    if not filtered_jobs:
        # if we are meant to filter by dependency but no jobs depends on this dependency, don't filter
        filtered_jobs = update_job_configs

    # collect last run
    for job_type, job_config in filtered_jobs.items():
        if dependency is not None and dependency not in job_config.dependencies:
            continue
        last_jobs[job_type] = MapUpdateJob.last_successful_or_skipped_job(job_type)

    for job_type, job_config in filtered_jobs.items():
        last_job = last_jobs[job_type]

        if last_job.mapupdate_id >= last_map_update_id:
            # job is already up to date
            continue

        for dependency in job_config.dependencies:
            if last_jobs[dependency].mapupdate_id <= last_job.mapupdate_id:
                # job is up to date with dependency, need to wait for dependency
                continue

        running_job = running_jobs.get(job_type)
        if running_job:
            if check_running_job(running_job):
                continue

        run_mapupdate_job.delay(job_type=job_type)


class LocationAncestryPathTuple(NamedTuple):
    prev: Optional["LocationAncestryPathTuple"]
    ancestor: int | None
    parent: int
    location: int
    num_hops: int


# todo: make this a transaction?? is it already?
@register_mapupdate_job("SpecificLocation order", eager=True, dependencies=set())
def verify_location_ancestry(mapupdates: tuple[MapUpdate, ...]) -> bool:
    build_children_by_parent: dict[int | None, deque[int]] = defaultdict(deque)
    parentage_ids: dict[tuple[int, int], int] = {}
    for pk, parent_id, child_id in LocationParentage.objects.values_list("pk", "parent_id", "child_id"):
        parentage_ids[(parent_id, child_id)] = pk
        build_children_by_parent[parent_id].append(child_id)
    children_by_parent: dict[int | None, frozenset[int]] = {
        parent_id: frozenset(children_ids) for parent_id, children_ids in build_children_by_parent.items()
    }

    fail = False

    # create ancestors
    expected_paths: dict[int, tuple[LocationAncestryPathTuple, ...]] = {}
    num_hops = 0
    last_paths: tuple[LocationAncestryPathTuple, ...] = tuple(chain.from_iterable(
        (
            LocationAncestryPathTuple(ancestor=parent_id, parent=parent_id, location=child_id,
                                      prev=None, num_hops=0)
            for child_id in child_ids
        ) for parent_id, child_ids in children_by_parent.items()
    ))
    while last_paths:
        paths_by_cyclic = {cyclic: tuple(paths)
                           for cyclic, paths in groupby(last_paths, key=lambda p: p.ancestor == p.location)}
        for path in paths_by_cyclic.get(True, ()):
            print(f"INCONSISTENCY! Circular hierarchy! Breaking parent→child {path.parent}→{path.location}")
            fail = True
        last_paths = paths_by_cyclic.get(False, ())
        expected_paths[num_hops] = last_paths

        num_hops += 1
        last_paths = tuple(chain.from_iterable(
            (
                LocationAncestryPathTuple(ancestor=prev.ancestor, parent=prev.location, location=child_id,
                                          prev=prev, num_hops=num_hops)
                for child_id in child_ids
            ) for prev, child_ids in zip(last_paths, (children_by_parent[path.location] for path in last_paths))
        ))

    expected_ancestries = {(path.ancestor, path.location) for path in chain.from_iterable(expected_paths.values)}
    ancestry_ids = {
        (ancestor_id, descendant_id): pk
        for pk, ancestor_id, descendant_id in LocationAncestry.objects.values_list("pk", "ancestor_id", "descendant_id")
    }
    existing_ancestries = set(ancestry_ids.keys())

    missing_ancestries = expected_ancestries - existing_ancestries
    if missing_ancestries:
        print("INCONSISTENCY: Missing ancestries, creating:", missing_ancestries)
        fail = True
        ancestry_ids.update({
            ancestry.pk: (ancestry.ancestor_id, ancestry.descendant_id)
            for ancestry in LocationAncestry.objects.bulk_create((
                LocationAncestry(
                    ancestor_id=ancestor_id,
                    descendant_id=descendant_id,
                ) for ancestor_id, descendant_id in missing_ancestries
            ))
        })

    extra_ancestries = existing_ancestries - expected_ancestries
    if extra_ancestries:
        print("INCONSISTENCY: Extra ancestries, deleting:", missing_ancestries)
        fail = True
        LocationAncestry.objects.filter(
            pk__in=(ancestry_ids[extra_ancestry] for extra_ancestry in extra_ancestries)
        ).delete()
        for extra_ancestry in missing_ancestries:
            del ancestry_ids[extra_ancestry]

    num_deleted, num_deleted_per_model = LocationAncestryPath.objects.exclude(
        # exclude things where things make sense
        Q(parentage__child=F("ancestry__descendant")) & (
            (Q(prev_path__isnull=True) | (Q(parentage__parent=F("prev_path__parentage__child"))
                                          & Q(ancestry__ancestor=F("prev_path__ancestry__ancestor"))
                                          & Q(num_hops=F("prev_path__num_hops")+1)))
            | (Q(prev_path__isnull=False) | Q(parentage__parent=F("ancestry__ancestor")))
        )
    ).delete()
    if num_deleted:
        print("INCONSISTENCY: Invalid paths that don't fit modeling constraints, deleting", num_deleted, "of them")
        fail = True

    existing_paths_by_id = {
        pk: fields for pk, *fields in LocationAncestryPath.objects.values_list(
            "pk", "prev_path_id", "ancestry___ancestor_id",
            "parentage__parent_id", "parentage__child_id", "num_hops",
        )
    }
    existing_paths_by_num_hops_and_id: dict[int, dict[int, LocationAncestryPathTuple]] = {}
    existing_path_id_by_tuple = dict[LocationAncestryPathTuple | None, int | None] = {None: None}

    for num_hops, paths in (
        sorted(groupby(existing_paths_by_id.items(), key=lambda p: p[1][4]))
    ):
        # todo: walrus operator?
        num_hops_paths = {}
        existing_paths_by_num_hops_and_id[num_hops] = num_hops_paths

        last_num_hops_paths = {} if num_hops == 0 else existing_paths_by_num_hops_and_id.get(num_hops - 1, {})

        for pk, (prev_path_id, ancestor_id, parent_id, child_id, n) in paths:
            t = LocationAncestryPathTuple(
                prev=None if prev_path_id is None else last_num_hops_paths[prev_path_id],
                ancestor=ancestor_id,
                parent=parent_id,
                location=child_id,
                num_hops=num_hops,
            )
            num_hops_paths[pk] = t
            existing_path_id_by_tuple[t] = pk

    delete_ids: deque[int] = deque()

    max_num_hops = max(chain(existing_paths_by_num_hops_and_id.keys(), expected_paths.keys()))
    for num_hops in range(max_num_hops+1):
        existing_paths_for_hops = frozenset(existing_paths_by_num_hops_and_id.get(num_hops, {}).values())
        expected_paths_for_hops = frozenset(expected_paths.get(num_hops, ()))

        missing_paths = tuple(expected_paths_for_hops - existing_paths_for_hops)
        if missing_ancestries:
            print("INCONSISTENCY: Missing paths, creating:", missing_paths)
            fail = True
            existing_path_id_by_tuple.update(
                dict(zip(missing_paths, (created_path.pk for created_path in LocationAncestryPath.objects.bulk_create((
                    LocationAncestryPath(
                        prev_path=existing_path_id_by_tuple[missing_path.prev],
                        parentage=parentage_ids[(missing_path.parent, missing_path.location)],
                        ancestry=ancestry_ids[(missing_path.ancestor, missing_path.location)],
                        num_hops=num_hops,
                    ) for missing_path in missing_paths
                )))))
            )

        extra_paths = existing_paths_for_hops - expected_paths_for_hops
        if extra_ancestries:
            print("INCONSISTENCY: Extra paths, deleting:", extra_paths)
            delete_ids.extend(existing_path_id_by_tuple[extra_path] for extra_path in extra_paths)
            fail = True

    if delete_ids:
        LocationAncestryPath.objects.filter(pk__in=delete_ids).delete()

    if fail:
        raise ValueError("verify_location_ancestry failed")

    return True


@register_mapupdate_job("SpecificLocation order",
                        eager=True, dependencies=(verify_location_ancestry, ))
def recalculate_specificlocation_order(mapupdates: tuple[MapUpdate, ...]) -> bool:
    SpecificLocation.recalculate_effective_order()
    return True


@register_mapupdate_job("SpecificLocation cached from parents",
                        eager=True, dependencies=(recalculate_specificlocation_order, ))
def recalculate_specificlocation_cached_from_parents(mapupdates: tuple[MapUpdate, ...]) -> bool:
    SpecificLocation.recalculate_cached_from_parents()
    return True


@register_mapupdate_job("SpecificLocation static targets", eager=True)
def recalculate_specificlocation_static_targets(mapupdates: tuple[MapUpdate, ...]) -> bool:
    SpecificLocation.recalculate_all_static_targets()
    return True


@register_mapupdate_job("SpecificLocation dynamic targets", eager=True)
def recalculate_specificlocation_dynamic_targets(mapupdates: tuple[MapUpdate, ...]) -> bool:
    SpecificLocation.recalculate_all_position_secrets()
    return True


@register_mapupdate_job("SpecificLocation target subtitles",
                        eager=True, dependencies=(recalculate_specificlocation_cached_from_parents, ))
def recalculate_specificlocation_target_subtitles(mapupdates: tuple[MapUpdate, ...]) -> bool:
    SpecificLocation.recalculate_target_subtitles()
    return True


@register_mapupdate_job("level bounds")
def recalculate_level_bounds(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Level.recalculate_bounds()
    return True


@register_mapupdate_job("Space effective geometries")
def recalculate_space_effective_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Space.recalculate_effective_geometries()
    return True


@register_mapupdate_job("Space simplified geometries", dependencies=(recalculate_space_effective_geometries, ))
def recalculate_space_simplified_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Space.recalculate_simplified_geometries()
    return True


@register_mapupdate_job("Area effective geometries")
def recalculate_area_effective_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Area.recalculate_effective_geometries()
    return True


@register_mapupdate_job("Space points", dependencies=(recalculate_space_effective_geometries, ))
def recalculate_space_points(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Space.recalculate_points()
    return True


@register_mapupdate_job("Area points", dependencies=(recalculate_area_effective_geometries, ))
def recalculate_area_points(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Area.recalculate_points()
    return True


@register_mapupdate_job("Space bounds", dependencies=(recalculate_space_effective_geometries, ))
def recalculate_space_bounds(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Space.recalculate_bounds()
    return True


@register_mapupdate_job("Area bounds",
                        dependencies=(recalculate_area_effective_geometries, ))
def recalculate_area_bounds(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    Area.recalculate_bounds()
    return True


@register_mapupdate_job("Specific location geometries",
                        dependencies=(recalculate_space_effective_geometries, recalculate_area_effective_geometries))
def recalculate_specificlocation_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    SpecificLocation.recalculate_geometries()
    return True


@register_mapupdate_job("Specific location bounds",
                        dependencies=(recalculate_level_bounds, recalculate_space_bounds, recalculate_area_bounds))
def recalculate_specificlocation_bounds(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    SpecificLocation.recalculate_bounds()
    return True


@register_mapupdate_job("Specific location points",
                        dependencies=(recalculate_space_points, recalculate_area_points))
def recalculate_specificlocation_points(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    SpecificLocation.recalculate_points()
    return True


@register_mapupdate_job("SpecificLocation finalize",
                        eager=True, dependencies=(recalculate_specificlocation_geometries,
                                                  recalculate_specificlocation_bounds,
                                                  recalculate_specificlocation_points,
                                                  recalculate_specificlocation_target_subtitles,
                                                  recalculate_specificlocation_static_targets,
                                                  recalculate_specificlocation_dynamic_targets,))
def recalculate_specificlocation_final(mapupdates: tuple[MapUpdate, ...]) -> bool:
    return True


@register_mapupdate_job("geometries",
                        dependencies=(recalculate_space_effective_geometries,
                                      recalculate_area_effective_geometries,
                                      recalculate_specificlocation_cached_from_parents,
                                      recalculate_specificlocation_final,))
def recalculate_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    geometry_update_folder_name = mapupdates[-1].to_tuple.folder_name
    (settings.CACHE_ROOT / geometry_update_folder_name).mkdir(exist_ok=True)

    changed_geometries.reset()

    logger.info('Recalculating altitude areas...')

    AltitudeArea.recalculate()

    logger.info('%.3f m² of altitude areas affected.' % changed_geometries.area)

    for new_update in mapupdates:
        logger.info('Applying changed geometries from MapUpdate #%(id)s (%(type)s)...' %
                    {'id': new_update.pk, 'type': new_update.type})
        try:
            new_changes = new_update.get_changed_geometries()
            if new_changes is None:
                logger.warning('changed_geometries pickle file not found.')
            else:
                logger.info('%.3f m² affected by this update.' % new_changes.area)
                changed_geometries.combine(new_changes)
        except EOFError:
            logger.warning('changed_geometries pickle file corrupted.')

    logger.info('%.3f m² of geometries affected in total.' % changed_geometries.area)

    changed_geometries.save(mapupdates[0].to_tuple, mapupdates[-1].to_tuple)

    logger.info('Rebuilding level render data...')

    LevelRenderData.rebuild(geometry_update_folder_name)

    return True