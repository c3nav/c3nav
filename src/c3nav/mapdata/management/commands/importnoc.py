import hashlib

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import BaseModel
from shapely import distance

from c3nav.mapdata.models import MapUpdate, Space
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.models.report import Report
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import unwrap_geom
from shapely.ops import nearest_points


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

    def do_report(self, prefix: str, obj_id: str, obj, report: Report):
        import_prefix = f"{prefix}:{obj_id}:"
        import_tag = import_prefix+hashlib.md5(str(obj).encode()).hexdigest()
        Report.objects.filter(import_tag__startswith=import_prefix, open=True).exclude(import_tag=import_tag).delete()
        if not Report.objects.filter(import_tag=import_tag).exists():
            report.import_tag = import_tag
            report.save()
            report.notify_reviewers()

    def do_import(self, items: dict[str, NocImportItem]):
        spaces_for_level = {}
        for space in Space.objects.all():
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
                if not space.geometry.intersects(new_geometry):
                    new_geometry = nearest_points(space.geometry.buffer(-0.05), new_geometry)[0]
            if len(possible_spaces) == 1:
                new_space = possible_spaces[0]
                print(f"SUCCESS: {name} is in {new_space.title}")
            else:
                print(f"WARNING: {name} could be in multiple spaces, picking one...")
                new_space = possible_spaces[0]

            # find existing location
            result = beacons_so_far.pop(import_tag, None)

            old_result = None

            # build resulting object
            if not result:
                old_result = result
                result = RangingBeacon(import_tag=import_tag)
            result.comment = name
            result.space = new_space
            result.geometry = new_geometry
            result.save()  # todo: onyl save if changes… etc

        for import_tag, location in beacons_so_far.items():
            location.delete()
            print(f"NOTE: {import_tag} was deleted")
