import math
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional

from shapely.geometry import JOIN_STYLE, box


class FillAttribs:
    __slots__ = ('color', 'opacity')

    def __init__(self, color, opacity=None):
        self.color = color
        self.opacity = opacity


class StrokeAttribs:
    __slots__ = ('color', 'width', 'min_px', 'opacity')

    def __init__(self, color, width, min_px=None, opacity=None):
        self.color = color
        self.width = width
        self.min_px = min_px
        self.opacity = opacity


class RenderEngine(ABC):
    # draw an svg image. supports pseudo-3D shadow-rendering
    def __init__(self, width: int, height: int, xoff=0, yoff=0, scale=1, buffer=0, background='#FFFFFF'):
        self.width = width
        self.height = height
        self.minx = xoff
        self.miny = yoff
        self.scale = scale
        self.orig_buffer = buffer
        self.buffer = int(math.ceil(buffer*self.scale))
        self.background = background

        self.maxx = self.minx + width / scale
        self.maxy = self.miny + height / scale

        # how many pixels around the image should be added and later cropped (otherwise rsvg does not blur correctly)
        self.buffer = int(math.ceil(buffer*self.scale))
        self.buffered_width = self.width + 2 * self.buffer
        self.buffered_height = self.height + 2 * self.buffer
        self.buffered_bbox = box(self.minx, self.miny, self.maxx, self.maxy).buffer(buffer, join_style=JOIN_STYLE.mitre)

        self.background_rgb = tuple(int(background[i:i + 2], 16)/255 for i in range(1, 6, 2))

    @abstractmethod
    def get_png(self) -> bytes:
        # render the image to png.
        pass

    @staticmethod
    @lru_cache()
    def color_to_rgb(color, alpha=None):
        if color.startswith('#'):
            return (*(int(color[i:i + 2], 16) / 255 for i in range(1, 6, 2)), 1 if alpha is None else alpha)
        if color.startswith('rgba('):
            color = tuple(float(i.strip()) for i in color.strip()[5:-1].split(','))
            return (*(i/255 for i in color[:3]), color[3] if alpha is None else alpha)
        raise ValueError('invalid color string!')

    def add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                     altitude=None, height=None, shape_cache_key=None):
        # draw a shapely geometry with a given style
        # altitude is the absolute altitude of the upper bound of the element
        # height is the height of the element
        # if altitude is not set but height is, the altitude will depend on the geometries below

        # if fill_color is set, filter out geometries that cannot be filled
        if geometry.is_empty:
            return

        self._add_geometry(geometry=geometry, fill=fill, stroke=stroke,
                           altitude=altitude, height=height, shape_cache_key=shape_cache_key)

    @abstractmethod
    def _add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                      altitude=None, height=None, shape_cache_key=None):
        pass

    def set_mesh_lookup_data(self, data):
        pass
