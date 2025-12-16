import math
import struct
from os import PathLike
from pathlib import Path
from typing import Self, Optional, Union, TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext

if TYPE_CHECKING:
    from shapely import Polygon, MultiPolygon


class GeometryIndexed:
    # binary format (everything little-endian):
    # 1 byte (uint8): variant id
    # 1 byte (uint8): resolution
    # 2 bytes (int16): origin x
    # 2 bytes (int16): origin y
    # 2 bytes (uint16): origin width
    # 2 bytes (uint16): origin height
    # (optional meta data, depending on subclass)
    # x bytes data, line after line. (cell size depends on subclass)
    dtype = np.uint16
    variant_id = 0

    def __init__(self, resolution: Optional[int] = None, x: int = 0, y: int = 0,
                 data: NDArray = None, filename: str | bytes | PathLike = None):
        if resolution is None:
            from django.conf import settings
            resolution = settings.CACHE_RESOLUTION
        self.resolution: int = resolution
        self.x = x
        self.y = y
        self.data: NDArray = data if data is not None else self._get_empty_array()
        self.filename = filename

    @classmethod
    def _get_empty_array(cls) -> NDArray:
        return np.empty((0, 0), dtype=cls.dtype)

    @classmethod
    def open(cls, filename: str | bytes | PathLike) -> Self:
        with open(filename, 'rb') as f:
            instance = cls.read(f)
        instance.filename = filename
        return instance

    @classmethod
    def read(cls, f) -> Self:
        variant_id, resolution, x, y, width, height = struct.unpack('<BBhhHH', f.read(10))
        if variant_id != cls.variant_id:
            raise ValueError('variant id does not match')

        kwargs = {
            'resolution': resolution,
            'x': x,
            'y': y,
        }
        cls._read_metadata(f, kwargs)

        # noinspection PyTypeChecker
        kwargs['data'] = np.frombuffer(f.read(width * height * cls.dtype().itemsize), cls.dtype).reshape(
            (height, width))
        return cls(**kwargs)

    @classmethod
    def _read_metadata(cls, f, kwargs: dict):
        pass

    def save(self, filename: str | bytes | PathLike = None):
        if filename is None:
            filename = self.filename
        if filename is None:
            raise ValueError('Missing filename.')

        with open(filename, 'wb') as f:
            self.write(f)

    def write(self, f):
        f.write(struct.pack('<BBhhHH', self.variant_id, self.resolution, self.x, self.y, *reversed(self.data.shape)))
        self._write_metadata(f)
        f.write(self.data.tobytes('C'))

    def _write_metadata(self, f):
        pass

    def get_geometry_bounds(self, geometry: Union['Polygon', 'MultiPolygon']) -> tuple[int, int, int, int]:
        minx, miny, maxx, maxy = geometry.bounds
        return (
            int(math.floor(minx / self.resolution)),
            int(math.floor(miny / self.resolution)),
            int(math.ceil(maxx / self.resolution)),
            int(math.ceil(maxy / self.resolution)),
        )

    def fit_bounds(self, minx: int, miny: int, maxx: int, maxy: int):
        height, width = self.data.shape

        if self.data.size:
            minx = min(self.x, minx)
            miny = min(self.y, miny)
            maxx = max(self.x + width, maxx)
            maxy = max(self.y + height, maxy)

        new_data = np.zeros((maxy - miny, maxx - minx), dtype=self.dtype)

        if self.data.size:
            dx = self.x - minx
            dy = self.y - miny
            new_data[dy:(dy + height), dx:(dx + width)] = self.data

        self.data = new_data
        self.x = minx
        self.y = miny

    def get_geometry_cells(self, geometry: Union['Polygon','MultiPolygon'],
                           bounds: Optional[tuple[int, int, int, int]] = None) -> NDArray:
        if bounds is None:
            bounds = self.get_geometry_bounds(geometry)
        minx, miny, maxx, maxy = bounds

        height, width = self.data.shape
        minx = max(minx, self.x)
        miny = max(miny, self.y)
        maxx = min(maxx, self.x + width)
        maxy = min(maxy, self.y + height)

        from shapely import prepared
        from shapely.geometry import box

        cells = np.zeros_like(self.data, dtype=bool)
        prep = prepared.prep(geometry)
        res = self.resolution
        for iy, y in enumerate(range(miny * res, maxy * res, res), start=miny - self.y):
            for ix, x in enumerate(range(minx * res, maxx * res, res), start=minx - self.x):
                if prep.intersects(box(x, y, x + res, y + res)):
                    cells[iy, ix] = True

        return cells

    @property
    def bounds(self) -> tuple[int, int, int, int]:
        height, width = self.data.shape
        return self.x, self.y, self.x + width, self.y + height

    def __getitem__(self, key: Union[tuple[slice, slice], 'Polygon','MultiPolygon']) -> int:
        if isinstance(key, tuple):
            xx, yy = key

            minx = int(math.floor(xx.start / self.resolution))
            miny = int(math.floor(yy.start / self.resolution))
            maxx = int(math.ceil(xx.stop / self.resolution))
            maxy = int(math.ceil(yy.stop / self.resolution))

            height, width = self.data.shape
            minx = max(0, minx - self.x)
            miny = max(0, miny - self.y)
            maxx = max(0, maxx - self.x)
            maxy = max(0, maxy - self.y)

            return self.data[miny:maxy, minx:maxx].ravel()

        from shapely.geometry.base import BaseGeometry
        if isinstance(key, BaseGeometry):
            bounds = self.get_geometry_bounds(key)
            return self.data[self.get_geometry_cells(key, bounds)]

        raise TypeError('GeometryIndexed index must be a shapely geometry or tuple, not %s' % type(key).__name__)

    def __setitem__(self, key: Union['Polygon','MultiPolygon'], value: NDArray | int):
        from shapely.geometry.base import BaseGeometry
        if isinstance(key, BaseGeometry):
            bounds = self.get_geometry_bounds(key)
            self.fit_bounds(*bounds)
            cells = self.get_geometry_cells(key, bounds)
            self.data[cells] = value
            return

        raise TypeError('GeometryIndexed index must be a shapely geometry, not %s' % type(key).__name__)

    def to_image(self):
        from c3nav.mapdata.models import Source
        (minx, miny), (maxx, maxy) = Source.max_bounds()

        height, width = self.data.shape
        image_data = np.zeros((int(math.ceil((maxy - miny) / self.resolution)),
                               int(math.ceil((maxx - minx) / self.resolution))), dtype=np.uint8)

        if self.data.size:
            # noinspection PyArgumentList
            minval = min(self.data.min(), 0)
            # noinspection PyArgumentList
            maxval = max(self.data.max(), minval + 0.01)
            visible_data = ((self.data.astype(float) - minval) * 255 / (maxval - minval)).clip(0, 255).astype(np.uint8)
            image_data[self.y:self.y + height, self.x:self.x + width] = visible_data

        from PIL import Image
        return Image.fromarray(np.flip(image_data, axis=0), 'L')

    def to_dict(self) -> dict:
        return {
            "variant_id": self.variant_id,
            "resolution": self.resolution,
            "x": self.x,
            "y": self.y,
            "width": self.data.shape[0],
            "height": self.data.shape[1],
            "data": self.data.tolist(),
        }


class LevelGeometryIndexed(GeometryIndexed):
    variant_name = None

    @classmethod
    def level_filename(cls, level_id: int, mode) -> Path:
        from django.conf import settings
        return settings.CACHE_ROOT / ('%s_%s_level_%d' % (cls.variant_name, mode, level_id))

    @classmethod
    def open_level(cls, level_id: int, mode, **kwargs) -> Self:
        # noinspection PyArgumentList
        return cls.open(cls.level_filename(level_id, mode), **kwargs)

    def save_level(self, level_id: int, mode):
        # noinspection PyArgumentList
        return self.save(self.level_filename(level_id, mode))

    cached = LocalContext()

    @classmethod
    def open_level_cached(cls, level_id: int, mode) -> Self:
        from c3nav.mapdata.models import MapUpdate
        cache_key = MapUpdate.current_processed_cache_key()
        if getattr(cls.cached, 'key', None) != cache_key:
            cls.cached.key = cache_key
            cls.cached.data = {}
        else:
            result = cls.cached.data.get((level_id, mode), None)
            if result is not None:
                return result

        result = cls.open_level(level_id, mode)
        cls.cached.data[(level_id, mode)] = result
        return result
