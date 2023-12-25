from uuid import UUID

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import Field, BaseModel
from pydantic import PositiveInt
from shapely import Point
from shapely.geometry import shape

from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import Area, Space, LocationGroup, LocationSlug, MapUpdate
from c3nav.mapdata.models.geometry.space import POI
from c3nav.mapdata.utils.cache.changes import changed_geometries


class HubImportItem(BaseModel):
    """
    Something imported from the hub
    """
    type: NonEmptyStr
    id: UUID
    slug: NonEmptyStr = Field(pattern=r'^[-a-zA-Z0-9_]+$')
    name: NonEmptyStr | dict[NonEmptyStr, NonEmptyStr]
    is_official: bool
    description: dict[NonEmptyStr, NonEmptyStr | None]
    public_url: NonEmptyStr = Field(pattern=r'^https://')
    parent_id: UUID | None
    children: list[NonEmptyStr] | None
    floor: PositiveInt | None
    location: tuple[float, float] | None
    polygons: tuple[list[tuple[float, float]]] | None


class Command(BaseCommand):
    help = 'import from hub'

    def handle(self, *args, **options):
        r = requests.get(settings.HUB_API_BASE+"/integration/c3nav?all=1",
                         headers={"Authorization": "Token "+settings.HUB_API_SECRET})
        r.raise_for_status()

        with MapUpdate.lock():
            changed_geometries.reset()
            self.do_import(r.json())
            MapUpdate.objects.create(type='importhub')

    def do_import(self, data):
        items: list[HubImportItem] = [HubImportItem.model_validate(item) for item in data]
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
            if item.polygons is None and item.location is None:
                print(f"SKIPPING: {item.slug} / {item.id} has no polygon or location")
                continue

            if item.floor is None:
                print(f"SKIPPING: {item.slug} / {item.id} has no floor")
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

            if result is not None:
                # already exists
                if not isinstance(result, target_type):
                    # need to change from POI to Area or inverted
                    if result.import_block_geom:
                        print(f"ERROR: {item.slug} / {item.id} needs to be switched to {target_type} but is blocked")
                        continue
                    print(f"ERROR: {item.slug} / {item.id} needs to be switched to {target_type} but not implemented")
                    continue

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

            if result.space_id != new_space.pk:
                if result.import_block_geom:
                    print(f"NOTE: {item.slug} / {item.id} space has changed but is blocked")
                else:
                    result.space_id = new_space.pk

            if result.geometry != new_geometry or True:
                if result.import_block_geom:
                    print(f"NOTE: {item.slug} / {item.id} geometry has changed but is blocked")
                else:
                    result.geometry = new_geometry

            if target_type == Area:
                new_main_point = Point(item.location) if item.location else None
                if result.main_point != new_main_point:
                    if result.import_block_geom:
                        print(f"NOTE: {item.slug} / {item.id} main point has changed but is blocked")
                    else:
                        result.main_point = new_main_point

            if item.slug != result.slug:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} slug has changed but is blocked")
                else:
                    if LocationSlug.objects.filter(slug=item.slug):
                        print(f"ERROR: {item.slug} / {item.id} slug {item.slug!r} is already occupied")
                        continue
                    else:
                        result.slug = item.slug

            new_titles = {"en": item.name}
            if new_titles != result.titles:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} name has changed but is blocked")
                else:
                    result.titles = new_titles

            if item.public_url != result.external_url:
                if result.import_block_data:
                    print(f"NOTE: {item.slug} / {item.id} external url has changed but is blocked")
                else:
                    result.external_url = item.public_url

            # time to check the groups
            new_group_ids = set(group.id for group in new_groups)
            if is_new:
                if not new_group_ids:
                    print(f"SKIPPING: {item.slug} / {item.id} has no group IDs, {hub_types}")
                    continue
            else:
                if not new_group_ids:
                    print(f"SKIPPING: {item.slug} / {item.id} no longer has any group IDs, {hub_types}")
                    continue

            result.save()
            if is_new:
                result.groups.set(new_group_ids)
            else:
                old_group_ids = set(group.pk for group in result.groups.all())
                if new_group_ids != old_group_ids:
                    print(f"NOTE: {item.slug} / {item.id} groups have changed, was " +
                          str([group.title for group in result.groups.all()]) +
                          ", is now"+str([group.title for group in new_groups]), new_group_ids, old_group_ids)

        for import_tag, location in locations_so_far.items():
            print(f"NOTE: {location.slug} / {import_tag} should be deleted")

