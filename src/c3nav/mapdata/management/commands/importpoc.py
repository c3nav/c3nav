from typing import Literal

import requests
from django.conf import settings
from django.core.management.base import BaseCommand
from pydantic import BaseModel
from pydantic.type_adapter import TypeAdapter
from pydantic_extra_types.mac_address import MacAddress
from shapely import distance
from shapely.geometry import shape, Point

from c3nav.api.schema import PointSchema
from c3nav.mapdata.models import MapUpdate, Level
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.mapdata.utils.importer import PointImportHelper


class PocImportItemProperties(BaseModel):
    level: str
    mac: MacAddress
    name: str


class PocImportItem(BaseModel):
    """
    Something imported from the NOC
    """
    type: Literal["Feature"] = "Feature"
    geometry: PointSchema
    properties: PocImportItemProperties


class Command(BaseCommand):
    help = 'import APs from noc'

    def handle(self, *args, **options):
        r = requests.get(settings.POC_API_BASE+"/antenna-locations", headers={'ApiKey': settings.POC_API_SECRET})
        r.raise_for_status()
        items = TypeAdapter(list[PocImportItem]).validate_python(r.json())

        with MapUpdate.lock():
            changed_geometries.reset()
            self.do_import(items)
            MapUpdate.objects.create(type='importnoc')

    def do_import(self, items: list[PocImportItem]):
        import_helper = PointImportHelper()

        beacons_so_far: dict[str, RangingBeacon] = {
            **{m.import_tag: m for m in RangingBeacon.objects.filter(import_tag__startswith="poc:",
                                                                     beacon_type=RangingBeacon.BeaconType.DECT)},
        }

        levels_by_level_index = {str(level.level_index): level for level in Level.objects.all()}

        for item in items:
            import_tag = f"poc:{item.properties.name}"

            # determine geometry
            level_id = levels_by_level_index[item.properties.level].pk

            point: Point = shape(item.geometry.model_dump())  # nowa

            new_space, point = import_helper.get_point_and_space(
                level_id=level_id,
                point=point,
                name=item.properties.name,
            )

            if new_space is None:
                continue

            # find existing location
            result = beacons_so_far.pop(import_tag, None)

            # build resulting object
            altitude_quest = True
            if not result:
                result = RangingBeacon(import_tag=import_tag, beacon_type=RangingBeacon.BeaconType.DECT)
            else:
                if result.space == new_space and distance(unwrap_geom(result.geometry), point) < 0.03:
                    continue
                if result.space == new_space and distance(unwrap_geom(result.geometry), point) < 0.20:
                    altitude_quest = False

            result.ap_name = item.properties.name
            result.addresses = [item.properties.mac.lower()]
            result.space = new_space
            result.geometry = point
            result.altitude = 0
            if altitude_quest:
                result.altitude_quest = True
            result.save()

        for import_tag, location in beacons_so_far.items():
            location.delete()
            print(f"NOTE: {import_tag} was deleted")
