import hashlib

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import BaseModel
from shapely import distance

from c3nav.mapdata.models import MapUpdate, Space, Level
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.models.report import Report
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import unwrap_geom
from shapely.ops import nearest_points, unary_union


class NocImportItem(BaseModel):
    """
    Something imported from the NOC
    """
    lat: float | int
    lng: float | int
    layer: str
    type: str = "unknown"


class Command(BaseCommand):
    help = 'import APs from noc'

    def handle(self, *args, **options):
        r = requests.get(settings.NOC_BASE+"/api/markers/get")
        r.raise_for_status()
        items = {name: NocImportItem.model_validate(item)
                 for name, item in r.json()["markers"].items()
                 if not name.startswith("__polyline")}

        with MapUpdate.lock():
            changed_geometries.reset()
            self.do_import(items)
            MapUpdate.objects.create(type='importnoc')

    def do_import(self, items: dict[str, NocImportItem]):
        spaces_for_level = {}
        levels = tuple(Level.objects.values_list("pk", flat=True))
        lower_levels_for_level = {pk: levels[:i] for i, pk in enumerate(levels)}

        for space in Space.objects.select_related('level').prefetch_related('holes'):
            spaces_for_level.setdefault(space.level_id, []).append(space)

        beacons_so_far: dict[str, RangingBeacon] = {
            **{m.import_tag: m for m in RangingBeacon.objects.filter(import_tag__startswith="noc:")},
        }

        for name, item in items.items():
            import_tag = f"noc:{name}"

            if item.type != "AP":
                continue

            # determine geometry
            converter = settings.NOC_LAYERS.get(item.layer, None)
            if not converter:
                print(f"ERROR: {name} has invalid layer: {item.layer}")
                continue

            new_geometry = converter.convert(item.lat, item.lng)

            # determine space
            possible_spaces = [space for space in spaces_for_level[converter.level_id]
                               if space.geometry.intersects(new_geometry)]
            if not possible_spaces:
                possible_spaces = [space for space in spaces_for_level[converter.level_id]
                                   if distance(unwrap_geom(space.geometry), new_geometry) < 0.3]
                if len(possible_spaces) == 1:
                    new_space = possible_spaces[0]
                    the_distance = distance(unwrap_geom(new_space.geometry), new_geometry)
                    print(f"SUCCESS: {name} is {the_distance:.02f}m away from {new_space.title}")
                elif len(possible_spaces) == 2:
                    new_space = min(possible_spaces, key=lambda s: distance(unwrap_geom(s.geometry), new_geometry))
                    print(f"WARNING: {name} could be in multiple spaces ({possible_spaces}, picking {new_space}...")
                else:
                    print(f"ERROR: {name} is not within any space (NOC: {(item.lat, item.lng)}, NAV: {new_geometry}")
                    continue

                # move point into space if needed
                new_space_geometry = new_space.geometry.difference(
                    unary_union([unwrap_geom(hole.geometry) for hole in new_space.columns.all()])
                )
                if not new_space_geometry.intersects(new_geometry):
                    new_geometry = nearest_points(new_space_geometry.buffer(-0.05), new_geometry)[0]
            elif len(possible_spaces) == 1:
                new_space = possible_spaces[0]
                print(f"SUCCESS: {name} is in {new_space.title}")
            else:
                print(f"WARNING: {name} could be in multiple spaces, picking one...")
                new_space = possible_spaces[0]

            lower_levels = lower_levels_for_level[new_space.level_id]
            for lower_level in reversed(lower_levels):
                # let's go through the lower levels
                if not unary_union([unwrap_geom(h.geometry) for h in new_space.holes.all()]).intersects(new_geometry):
                    # current selected spacae is fine, that's it
                    break
                print(f"NOTE: {name} is in a hole, looking lower...")

                # find a lower space
                possible_spaces = [space for space in spaces_for_level[lower_level]
                                   if space.geometry.intersects(new_geometry)]
                if possible_spaces:
                    new_space = possible_spaces[0]
                    print(f"NOTE: {name} moved to lower space {new_space}")
            else:
                print(f"WARNING: {name} couldn't find a lower space, still in a hole")

            # find existing location
            result = beacons_so_far.pop(import_tag, None)

            # build resulting object
            altitude_quest = True
            if not result:
                result = RangingBeacon(import_tag=import_tag)
            else:
                if result.space == new_space and distance(unwrap_geom(result.geometry), new_geometry) < 0.03:
                    continue
                if result.space == new_space and distance(unwrap_geom(result.geometry), new_geometry) < 0.20:
                    altitude_quest = False

            result.comment = name
            result.space = new_space
            result.geometry = new_geometry
            result.altitude = 0
            if altitude_quest:
                result.altitude_quest = True
            result.save()

        for import_tag, location in beacons_so_far.items():
            location.delete()
            print(f"NOTE: {import_tag} was deleted")
