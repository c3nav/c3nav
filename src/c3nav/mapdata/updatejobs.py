import logging
from dataclasses import dataclass
from functools import wraps
from typing import Callable, Iterable

from django.conf import settings
from django.db import IntegrityError, transaction, DatabaseError
from django.utils import timezone

from c3nav.mapdata.models import MapUpdate, LocationGroup, AltitudeArea
from c3nav.mapdata.models.update import MapUpdateJobStatus, MapUpdateJob
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
    done_jobs = set()
    while True:
        try:
            next_job_type = next(iter(job_type for job_type in remaining_job_types
                                      if not (update_job_configs[job_type].dependencies - done_jobs)))
        except StopIteration:
            break
        update_job_configs[next_job_type].run((mapupdate,), nowait=False)
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


@register_mapupdate_job("LocationGroup order",
                        eager=True, dependencies=set())
def recalculate_locationgroup_order(mapupdates: tuple[MapUpdate, ...]) -> bool:
    LocationGroup.calculate_effective_order()
    return True


@register_mapupdate_job("SpecificLocation order",
                        eager=True, dependencies=set())
def recalculate_specificlocation_order(mapupdates: tuple[MapUpdate, ...]) -> bool:
    LocationGroup.calculate_effective_order()
    return True


@register_mapupdate_job("effective icons",
                        eager=True, dependencies=(recalculate_locationgroup_order,
                                                  recalculate_specificlocation_order))
def recalculate_effective_icon(mapupdates: tuple[MapUpdate, ...]) -> bool:
    LocationGroup.calculate_effective_order()
    return True


@register_mapupdate_job("geometries", dependencies=(recalculate_effective_icon, ))  # todo: depend on colors
def recalculate_geometries(mapupdates: tuple[MapUpdate, ...]) -> bool:
    if not any(update.geometries_changed for update in mapupdates):
        logger.info('No geometries affected.')
        return False

    geometry_update_cache_key = mapupdates[-1].to_tuple.cache_key
    (settings.CACHE_ROOT / geometry_update_cache_key).mkdir(exist_ok=True)

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

    LevelRenderData.rebuild(geometry_update_cache_key)

    return True