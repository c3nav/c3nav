import math
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional

from shapely.geometry import JOIN_STYLE, box

from c3nav.mapdata.utils.color import color_to_rgb


@dataclass(slots=True)
class FillAttribs:
    color: str
    opacity: float | None = None


@dataclass(slots=True)
class StrokeAttribs:
    color: str
    width: float
    min_px: float | None = None
    opacity: float | None = None


class RenderEngine(ABC):
    is_3d = False
    filetype = 'dat'

    # draw an svg image. supports pseudo-3D shadow-rendering
    def __init__(self, width: int, height: int, xoff=0, yoff=0, zoff=0,
                 scale=1, buffer=0, background='#FFFFFF', min_width=None, center=True):
        self.width = width
        self.height = height
        self.minx = xoff
        self.miny = yoff
        self.base_z = zoff
        self.scale = scale
        self.orig_buffer = buffer
        self.buffer = int(math.ceil(buffer*self.scale))
        self.background = background
        self.min_width = min_width

        self.maxx = self.minx + width / scale
        self.maxy = self.miny + height / scale
        self.bbox = box(self.minx, self.miny, self.maxx, self.maxy)

        # how many pixels around the image should be added and later cropped (otherwise rsvg does not blur correctly)
        self.buffer = int(math.ceil(buffer*self.scale))
        self.buffered_width = self.width + 2 * self.buffer
        self.buffered_height = self.height + 2 * self.buffer
        self.buffered_bbox = self.bbox.buffer(buffer, join_style=JOIN_STYLE.mitre)

        self.background_rgb = tuple(int(background[i:i + 2], 16)/255 for i in range(1, len(background), 2))

    @abstractmethod
    def render(self, filename=None) -> bytes:
        # render the image to png.
        pass

    @staticmethod
    def color_to_rgb(color, alpha=None):
        return color_to_rgb(color, alpha=None)

    def add_group(self, group):
        pass

    def darken(self, area, much=False):
        pass

    def add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                     altitude=None, height=None, shadow_color=None, shape_cache_key=None, category=None, item=None):
        # draw a shapely geometry with a given style
        # altitude is the absolute altitude of the upper bound of the element
        # height is the height of the element
        # if altitude is not set but height is, the altitude will depend on the geometries below

        # if fill_color is set, filter out geometries that cannot be filled
        if geometry.is_empty:
            return

        self._add_geometry(geometry=geometry, fill=fill, stroke=stroke, altitude=altitude, height=height, shadow_color=shadow_color,
                           shape_cache_key=shape_cache_key, category=category, item=item)

    @abstractmethod
    def _add_geometry(self, geometry, fill: Optional[FillAttribs], stroke: Optional[StrokeAttribs],
                      altitude=None, height=None, shadow_color=None, shape_cache_key=None, category=None, item=None):
        pass

    def set_mesh_lookup_data(self, data):
        pass


engines_by_filetype = {}


def register_engine(engine=None):
    if isinstance(engine.filetype, tuple):
        for i, filetype in enumerate(engine.filetype):
            engines_by_filetype[filetype] = (engine, i)
    else:
        engines_by_filetype[engine.filetype] = (engine, None)
    return engine


def get_engine(filetype):
    return engines_by_filetype[filetype]


def get_engine_filetypes():
    return tuple(engines_by_filetype.keys())
