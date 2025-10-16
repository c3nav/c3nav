import math
from functools import cached_property

import numpy as np
from pydantic.main import BaseModel
from pydantic.type_adapter import TypeAdapter
from shapely import Point


def deg2pos(lat_deg, lon_deg):
    lat_rad = math.radians(lat_deg)
    xpos = (lon_deg + 180.0) / 360.0
    ypos = math.asinh(math.tan(lat_rad)) / math.pi / 2.0
    return ypos, xpos


class NocTransformLayerSchema(BaseModel):
    level_id: int
    scale: float | int
    offset: tuple[float, float] | int

    def convert(self, lat, lng) -> Point:
        return Point(*reversed(tuple(np.array(deg2pos(lat, lng)) * self.scale + np.array(self.offset))))


class NocTwoPointLayerSchema(BaseModel):
    level_id: int
    latlng1_noc: tuple[float, float]
    latlng1_nav: tuple[float, float]
    latlng2_noc: tuple[float, float]
    latlng2_nav: tuple[float, float]

    @cached_property
    def to_transform(self) -> NocTransformLayerSchema:
        diff_noc = np.array(deg2pos(*self.latlng1_noc)) - np.array(deg2pos(*self.latlng2_noc))
        diff_nav = np.array(self.latlng1_nav) - np.array(self.latlng2_nav)
        scale = np.linalg.norm(diff_nav) / np.linalg.norm(diff_noc)
        offset = np.array(self.latlng1_nav) - (np.array(deg2pos(*self.latlng1_noc)) * scale)
        return NocTransformLayerSchema(
            level_id=self.level_id,
            scale=scale,
            offset=tuple(offset),
        )

    def convert(self, lat, lng) -> Point:
        return self.to_transform.convert(lat, lng)


NocLayersSchema = TypeAdapter(dict[str, NocTransformLayerSchema | NocTwoPointLayerSchema])
