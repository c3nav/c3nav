import hashlib
from uuid import UUID

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import BaseModel, Field, PositiveInt
from shapely import Point
from shapely.geometry import shape

from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import Area, LocationGroup, LocationSlug, MapUpdate, Space
from c3nav.mapdata.models.geometry.space import POI
from c3nav.mapdata.models.report import Report
from c3nav.mapdata.utils.cache.changes import changed_geometries


class HubImportItem(BaseModel):
    """
    Something imported from the hub
    """
    type: NonEmptyStr
    id: UUID
    slug: NonEmptyStr = Field(pattern=r'^[-a-zA-Z0-9_]+$')
    name: NonEmptyStr | dict[NonEmptyStr, NonEmptyStr] = None
    is_official: bool = False
    description: dict[NonEmptyStr, str | None]
    public_url: NonEmptyStr = Field(pattern=r'^https://')
    parent_id: UUID | None = None
    children: list[NonEmptyStr] | None = []
    floor: PositiveInt | None
    location: tuple[float, float] | None
    polygons: tuple[list[tuple[float, float]]] | None = None


class Command(BaseCommand):
    help = 'import from hub'

    def handle(self, *args, **options):
        r = requests.get(settings.HUB_API_BASE+"/integrations/c3nav/",
                         headers={"Authorization": "Bearer " + settings.HUB_API_SECRET})
        r.raise_for_status()

        with MapUpdate.lock():
            changed_geometries.reset()
            self.do_import(r.json())
            MapUpdate.objects.create(type='importhub')

    def do_report(self, prefix: str, obj_id: str, obj, report: Report):
        import_prefix = f"{prefix}:{obj_id}:"
        import_tag = import_prefix+hashlib.md5(str(obj).encode()).hexdigest()
        Report.objects.filter(import_tag__startswith=import_prefix, open=True).exclude(import_tag=import_tag).delete()
        if not Report.objects.filter(import_tag=import_tag).exists():
            report.import_tag = import_tag
            report.save()
            report.notify_reviewers()

    def do_import(self, data):
        items: list[HubImportItem] = [HubImportItem.model_validate(item) for item in data
                                      if item["type"] in ("assembly", "room", "project")]
        items_by_id = {item.id: item for item in items}

        spaces_for_level = {}
        for space in Space.objects.all():
            spaces_for_level.setdefault(space.level_id, []).append(space)

        locations_so_far = {
            **{poi.import_tag: poi for poi in POI.objects.filter(import_tag__startswith="hub:")},
            **{area.import_tag: area for area in Area.objects.filter(import_tag__startswith="hub:")},
        }

        groups_for_types = {
            group.hub_import_type: group
            for group in LocationGroup.objects.filter(hub_import_type__isnull=False)
        }

        for item in items:
            item.slug = item.slug.lower().replace('_', '-')

            if item.type == "project":
                item.polygons = None

            if item.polygons is None and item.location is None:
                print(f"SKIPPING: {item.slug} / {item.id} has no polygon or location")
                continue

            if item.floor is None:
                print(f"SKIPPING: {item.slug} / {item.id} has no floor")
                continue

            if item.is_official:
                print(f"SKIPPING: {item.slug} / {item.id} because it is official")
                continue

            import_tag = f"hub:{item.id}"

            # determine geometry
            target_type = Area if item.polygons else POI
            if target_type == Area:
                new_geometry = shape({
                    "type": "Polygon",
                    "coordinates": [[[y, x] for x, y in item.polygons[0]]],
                })
            elif target_type == POI:
                new_geometry = shape({
                    "type": "Point",
                    "coordinates": list(reversed(item.location)),
                })
            else:
                raise ValueError

            # determine space
            try:
                possible_spaces = [space for space in spaces_for_level[item.floor]
                                   if space.geometry.intersects(new_geometry)]
            except KeyError:
                print(f"ERROR: {item.slug} / {item.id} has invalid level ID")
                continue
            if not possible_spaces:
                print(f"ERROR: {item.slug} / {item.id} is not within any space")
                continue
            if len(possible_spaces) == 1:
                new_space = possible_spaces[0]
            elif target_type == Area:
                new_space = max(possible_spaces, key=lambda s: s.geometry.intersection(new_geometry).area)
            elif target_type == POI:
                print(f"WARNING: {item.slug} / {item.id} could be in multiple spaces, picking one...")
                new_space = possible_spaces[0]
            else:
                raise ValueError

            # find existing location
            result = locations_so_far.pop(import_tag, None)
            result: Area | POI | None

            old_result = None   # only used if the type needs to be changed

            if result is None:
                occupied_by = LocationSlug.objects.filter(slug=item.id).first()
                if occupied_by:
                    print(f"SKIPPING (nonexisting): {item.slug} / {item.id} UUID already occupied by {occupied_by.get_child()}")
                    continue

            elif result is not None:
                # already exists
                if not isinstance(result, target_type):
                    # need to change from POI to Area or inverted
                    if result.import_block_geom:
                        self.do_report(
                            prefix='hub:switch_type',
                            obj_id=str(item.id),
                            report=Report(
                                category="location-issue",
                                title=f"importhub: change geometry type for {result.title}, is blocked",
                                description=f"the object has a wrong geometry type and needs to be switched to "
                                            f"{target_type} but the geometry is blocked",
                                location=result,
                            )
                        )
                        print(f"REPORT: {item.slug} / {item.id} needs to be switched to {target_type} but is blocked")
                        continue
                    old_result = result
                    result = target_type(
                        import_tag=import_tag,
                    )
                    result.titles = old_result.other_titles
                    result.icon = old_result.icon
                    result.external_url = old_result.external_url
                    result.can_search = old_result.can_search
                    result.can_describe = old_result.can_describe
                    result.label_overrides = old_result.label_overrides
                    result.label_settings_id = old_result.label_settings_id
                    result.import_block_data = old_result.import_block_data
                    print(f"NOTE: {item.slug} / {item.id} was switched to {target_type}")

            hub_types = [
                item.type,
                "%s:%s" % (item.type, "with-children" if item.children else "with-no-children"),
                "%s:%s" % (item.type, f"parent:{items_by_id[item.parent_id].slug}" if item.parent_id else "no-parent"),
            ]

            # build groups
            new_groups = [group for hub_type, group in groups_for_types.items() if hub_type in hub_types]

            # build resulting object
            is_new = False
            if not result:
                is_new = True
                result = target_type(
                    import_tag=import_tag,
                )

            geometry_needs_change = []

            if result.space_id != new_space.pk:
                if result.import_block_geom:
                    geometry_needs_change.append(f"change to space {new_space.title}")
                    print(f"NOTE: {item.slug} / {item.id} space has changed but is blocked")
                else:
                    result.space_id = new_space.pk

            if result.geometry != new_geometry or True:
                if result.import_block_geom:
                    geometry_needs_change.append("change geometry")
                    print(f"NOTE: {item.slug} / {item.id} geometry has changed but is blocked")
                else:
                    result.geometry = new_geometry

            if target_type == Area:
                new_main_point = Point(item.location) if item.location else None
                if result.main_point != new_main_point:
                    if result.import_block_geom:
                        geometry_needs_change.append("change main point")
                        print(f"NOTE: {item.slug} / {item.id} main point has changed but is blocked")
                    else:
                        result.main_point = new_main_point

            if geometry_needs_change:
                self.do_report(
                    prefix='hub:change_geometry',
                    obj_id=str(item.id),
                    obj=item,
                    report=Report(
                        category="location-issue",
                        title="importhub: geometry is blocked but needs changing",
                        description="changes needed: "+','.join(geometry_needs_change),
                        location=result,
                    )
                )

            data_needs_change = []

            if item.slug != result.slug:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} slug has changed but is blocked")
                    data_needs_change.append(f"change slug to {item.slug}")
                elif not old_result:
                    slug_occupied = LocationSlug.objects.filter(slug=item.slug).first()
                    if slug_occupied:
                        print(f"ERROR: {item.slug} / {item.id} slug {item.slug!r} is already occupied")
                        if is_new:
                            self.do_report(
                                prefix='hub:new_slug_occupied',
                                obj_id=str(item.id),
                                obj=item,
                                report=Report(
                                    category="location-issue",
                                    title=f"importhub: want to import item with this slug ({item.slug}), occupied",
                                    description=f"object to add {item.id}, for slug '{item.slug}' has name {item.name} "
                                                f"and url {item.public_url} and should be in space {new_space.title}",
                                    location=slug_occupied,
                                )
                            )
                        else:
                            self.do_report(
                                prefix='hub:new_slug_occupied',
                                obj_id=str(item.id),
                                obj=item,
                                report=Report(
                                    category="location-issue",
                                    title=f"importhub: want change slug to {item.slug} but it's occupied",
                                    description=f"object to add {item.id} for slug '{item.slug}' has name {item.name} "
                                                f"and url {item.public_url}",
                                    location=result,
                                )
                            )
                        continue
                    else:
                        result.slug = item.slug

            new_titles = {"en": item.name}
            if new_titles != result.titles:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} name has changed but is blocked")
                    data_needs_change.append(f"change name to {item.name}")
                else:
                    result.titles = new_titles

            if item.public_url != result.external_url:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} external url has changed but is blocked")
                    data_needs_change.append(f"change external_url to {item.public_url}")
                else:
                    result.external_url = item.public_url

            if data_needs_change:
                self.do_report(
                    prefix='hub:change_data',
                    obj_id=str(item.id),
                    obj=item,
                    report=Report(
                        category="location-issue",
                        title="importhub: data is blocked but needs changing",
                        description="changes needed: "+','.join(data_needs_change),
                        location=result,
                    )
                )

            # time to check the groups
            new_group_ids = set(group.id for group in new_groups)
            if is_new:
                if not new_group_ids:
                    print(f"SKIPPING: {item.slug} / {item.id} has no group IDs, {hub_types}")
                    continue
            else:
                if not new_group_ids:
                    print(f"SKIPPING: {item.slug} / {item.id} no longer has any group IDs, {hub_types}")
                    self.do_report(
                        prefix='hub:new_groups',
                        obj_id=str(item.id),
                        obj=item,
                        report=Report(
                            category="location-issue",
                            title="importhub: location no longer has any valid group ids",
                            description="from the hub we would remove all groups, this seems wrong",
                            location=result,
                        )
                    )
                    continue

            if old_result:
                old_group_ids = set(group.pk for group in old_result.groups.all())
                old_redirect_slugs = set(redirect.slug for redirect in old_result.redirects.all())
                old_result.delete()
            result.save()
            if old_result:
                result.groups.set(old_group_ids)
                for slug in old_redirect_slugs:
                    result.redirects.create(slug=slug)
            if not result.redirects.filter(slug=item.id).exists():
                result.redirects.create(slug=item.id)
            if is_new:
                result.groups.set(new_group_ids)
            else:
                old_group_ids = set(group.pk for group in result.groups.all())
                if new_group_ids != old_group_ids:
                    self.do_report(
                        prefix='hub:new_groups',
                        obj_id=str(item.id),
                        obj=item,
                        report=Report(
                            category="location-issue",
                            title="importhub: new groups",
                            description=("hub wants new groups for this, groups are now: " +
                                         str([group.title for group in new_groups])),
                            location=result,
                        )
                    )
                    print(f"NOTE: {item.slug} / {item.id} groups have changed, was " +
                          str([group.title for group in result.groups.all()]) +
                          ", is now"+str([group.title for group in new_groups]), new_group_ids, old_group_ids)

        for import_tag, location in locations_so_far.items():
            if location.import_block_data:
                self.do_report(
                    prefix='hub:new_groups',
                    obj_id=import_tag,
                    obj=import_tag,
                    report=Report(
                        category="location-issue",
                        title="importhub: delete this",
                        description="hub wants to delete this but it's blocked",
                        location=location,
                    )
                )
                print(f"NOTE: {location.slug} / {import_tag} should be deleted")
            else:
                location.delete()
