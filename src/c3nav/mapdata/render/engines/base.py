import math
from abc import ABC, abstractmethod
from functools import lru_cache
from typing import Optional

import numpy as np
import time
from shapely import prepared
from shapely.ops import unary_union

from c3nav.routing.utils.mpl import shapely_to_mpl


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
        self.buffer = int(math.ceil(buffer*self.scale))
        self.background = background

        self.maxx = self.minx + width / scale
        self.maxy = self.miny + height / scale

        # how many pixels around the image should be added and later cropped (otherwise rsvg does not blur correctly)
        self.buffer = int(math.ceil(buffer*self.scale))
        self.buffered_width = self.width + 2 * self.buffer
        self.buffered_height = self.height + 2 * self.buffer

        self.background_rgb = tuple(int(background[i:i + 2], 16) for i in range(1, 6, 2))

        # keep track which area of the image has which altitude currently
        self.altitudes = {}
        self.last_altitude = None

        self.altitudes_by_index = []
        self.altitude_indizes = {}

        samples = 2
        np_width = self.buffered_width * samples
        np_height = self.buffered_height * samples
        self.np_altitudes = np.full((np_height, np_width), fill_value=0, dtype=np.uint8)

        np_x = (np.arange(np_width) + 1/2/samples) / (scale*samples) + (self.minx-self.buffer/scale)
        np_y = (np.arange(np_height) + 1/2/samples) / (scale*samples) + (self.miny-self.buffer/scale)
        self.np_coords = np.stack((np.tile(np_x, np_height), np.repeat(np_y, np_width)), 1)

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

    def clip_altitudes(self, new_geometry, new_altitude=None):
        # register new geometry with an altitude
        # a geometry with no altitude will reset the altitude information of its area as if nothing was ever there
        if self.last_altitude is not None and self.last_altitude > new_altitude:
            raise ValueError('Altitudes have to be ascending.')

        if new_altitude is None:
            new_value = 0
        else:
            try:
                new_value = self.altitude_indizes[new_altitude]
            except KeyError:
                self.altitudes_by_index.append(new_altitude)
                new_value = len(self.altitudes_by_index)
                self.altitude_indizes[new_altitude] = new_value
        print(new_value)

        geometry = shapely_to_mpl(new_geometry)

        #print(self.np_coords)
        #print(new_geometry)
        start = time.time()
        bla = geometry.contains_points(self.np_coords)
        print(time.time()-start)
        #print(type(geometry), bla.shape, bla.astype(int).sum())
        self.np_altitudes[bla.reshape(self.np_altitudes.shape)] = new_value
        return

        if new_altitude in self.altitudes:
            self.altitudes[new_altitude] = unary_union([self.altitudes[new_altitude], new_geometry])
        else:
            self.altitudes[new_altitude] = new_geometry

    def add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                     altitude=None, height=None, shape_cache_key=None):
        # draw a shapely geometry with a given style
        # altitude is the absolute altitude of the upper bound of the element
        # height is the height of the element
        # if altitude is not set but height is, the altitude will depend on the geometries below

        # if fill_color is set, filter out geometries that cannot be filled
        if fill is not None:
            try:
                geometry.geoms
            except AttributeError:
                if not hasattr(geometry, 'exterior'):
                    return
            else:
                geometry = type(geometry)(tuple(geom for geom in geometry.geoms if hasattr(geom, 'exterior')))
        if geometry.is_empty:
            return

        self._add_geometry(geometry=geometry, fill=fill, stroke=stroke,
                           altitude=altitude, height=height, shape_cache_key=shape_cache_key)

    @abstractmethod
    def _add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                      altitude=None, height=None, shape_cache_key=None):
        pass
