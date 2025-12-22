import re

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import BaseModel
from shapely import distance

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.utils.placement import PointPlacementHelper
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import unwrap_geom


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
        import_helper = PointPlacementHelper()

        beacons_so_far: dict[str, RangingBeacon] = {
            **{":".join(m.import_tag.split(':')[:2]): m
               for m in RangingBeacon.objects.filter(import_tag__startswith="noc:",
                                                     beacon_type=RangingBeacon.BeaconType.EVENT_WIFI)},
        }

        for orig_name, item in items.items():
            if item.type != "AP":
                continue

            match = re.match(r"^AP[0-9]+", orig_name)
            if match is None:
                continue

            name = match.group(0)

            import_tag = f"noc:{name}"
            import_tag_full = f"noc:{name}:{item.layer}:{item.lat}:{item.lng}"

            # determine geometry
            converter = settings.NOC_LAYERS.get(item.layer, None)
            if not converter:
                print(f"ERROR: {name} has invalid layer: {item.layer}")
                continue

            point = converter.convert(item.lat, item.lng)

            new_space, point = import_helper.get_point_and_space(
                level_id=converter.level_id,
                point=point,
                name=name,
            )

            if new_space is None:
                continue

            # find existing location
            result = beacons_so_far.pop(import_tag, None)

            # build resulting object
            if not result:
                result = RangingBeacon(import_tag=import_tag_full, beacon_type=RangingBeacon.BeaconType.EVENT_WIFI)
                result.geometry = point
                result.space = new_space
                result.ap_name = name

            elif result.import_tag == import_tag_full:
                # if the import data has not changed, there's nothing to do
                continue
            else:
                result.import_tag = import_tag_full
                if result.space == new_space and distance(unwrap_geom(result.geometry), point) < 1:
                    # same space and noc has moved it, but closer than 1m to where we have it, ignore
                    pass
                else:
                    # different space or noc has moved it to a place more than 1m away from our position, update
                    result.geometry = point
                    result.space = new_space
                    result.altitude_quest = True

            result.save()

        for import_tag, location in beacons_so_far.items():
            location.delete()
            print(f"NOTE: {import_tag} was deleted")
