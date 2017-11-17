import logging
import math
import os
import struct
import threading
from itertools import chain

import numpy as np
from django.conf import settings
from django.db.models.signals import m2m_changed, post_delete
from PIL import Image
from shapely import prepared
from shapely.geometry import box
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.utils.models import get_submodels

logger = logging.getLogger('c3nav')


class GeometryIndexed:
    # binary format (everything little-endian):
    # 1 byte (uint8): variant id
    # 1 byte (uint8): resolution
    # 2 bytes (uint16): origin x
    # 2 bytes (uint16): origin y
    # 2 bytes (uint16): origin width
    # 2 bytes (uint16): origin height
    # (optional meta data, depending on subclass)
    # x bytes data, line after line. (cell size depends on subclass)
    dtype = np.uint16
    variant_id = 0

    def __init__(self, resolution=settings.CACHE_RESOLUTION, x=0, y=0, data=None, filename=None):
        self.resolution = resolution
        self.x = x
        self.y = y
        self.data = data if data is not None else self._get_empty_array()
        self.filename = filename

    @classmethod
    def _get_empty_array(cls):
        return np.empty((0, 0), dtype=cls.dtype)

    @classmethod
    def open(cls, filename):
        with open(filename, 'rb') as f:
            instance = cls.read(f)
        instance.filename = filename
        return instance

    @classmethod
    def read(cls, f):
        variant_id, resolution, x, y, width, height = struct.unpack('<BBHHHH', f.read(10))
        if variant_id != cls.variant_id:
            raise ValueError('variant id does not match')

        kwargs = {
            'resolution': resolution,
            'x': x,
            'y': y,
        }
        cls._read_metadata(f, kwargs)

        # noinspection PyTypeChecker
        kwargs['data'] = np.fromstring(f.read(width*height*cls.dtype().itemsize), cls.dtype).reshape((height, width))
        return cls(**kwargs)

    @classmethod
    def _read_metadata(cls, f, kwargs):
        pass

    def save(self, filename=None):
        if filename is None:
            filename = self.filename
        if filename is None:
            raise ValueError('Missing filename.')

        with open(filename, 'wb') as f:
            self.write(f)

    def write(self, f):
        f.write(struct.pack('<BBHHHH', self.variant_id, self.resolution, self.x, self.y, *reversed(self.data.shape)))
        self._write_metadata(f)
        f.write(self.data.tobytes('C'))

    def _write_metadata(cls, f):
        pass

    def _get_geometry_bounds(self, geometry):
        minx, miny, maxx, maxy = geometry.bounds
        return (
            int(math.floor(minx / self.resolution)),
            int(math.floor(miny / self.resolution)),
            int(math.ceil(maxx / self.resolution)),
            int(math.ceil(maxy / self.resolution)),
        )

    def fit_bounds(self, minx, miny, maxx, maxy):
        height, width = self.data.shape

        if self.data.size:
            minx = min(self.x, minx)
            miny = min(self.y, miny)
            maxx = max(self.x + width, maxx - minx)
            maxy = max(self.y + height, maxy - miny)

        new_data = np.zeros((maxy - miny, maxx - minx), dtype=self.dtype)

        if self.data.size:
            dx = self.x - minx
            dy = self.y - miny
            new_data[dy:(dy + height), dx:(dx + width)] = self.data

        self.data = new_data
        self.x = minx
        self.y = miny

    def get_geometry_cells(self, geometry, bounds=None):
        if bounds is None:
            bounds = self._get_geometry_bounds(geometry)
        minx, miny, maxx, maxy = bounds

        height, width = self.data.shape
        minx = max(minx, self.x)
        miny = max(miny, self.y)
        maxx = min(maxx, self.x + width)
        maxy = min(maxy, self.y + height)

        cells = np.zeros_like(self.data, dtype=np.bool)
        prep = prepared.prep(geometry)
        res = self.resolution
        for iy, y in enumerate(range(miny * res, maxy * res, res), start=miny - self.y):
            for ix, x in enumerate(range(minx * res, maxx * res, res), start=minx - self.x):
                if prep.intersects(box(x, y, x + res, y + res)):
                    cells[iy, ix] = True

        return cells

    @property
    def bounds(self):
        height, width = self.data.shape
        return self.x, self.y, self.x+width, self.y+height

    def __getitem__(self, key):
        if isinstance(key, BaseGeometry):
            bounds = self._get_geometry_bounds(key)
            return self.data[self.get_geometry_cells(key, bounds)]

        raise TypeError('GeometryIndexed index must be a shapely geometry, not %s' % type(key).__name__)

    def __setitem__(self, key, value):
        if isinstance(key, BaseGeometry):
            bounds = self._get_geometry_bounds(key)
            self.fit_bounds(*bounds)
            cells = self.get_geometry_cells(key, bounds)
            print('setitem: %s' % cells)
            self.data[cells] = value
            return

        raise TypeError('GeometryIndexed index must be a shapely geometry, not %s' % type(key).__name__)

    def to_image(self):
        from c3nav.mapdata.models import Source
        (minx, miny), (maxx, maxy) = Source.max_bounds()

        height, width = self.data.shape
        image_data = np.zeros((int(math.ceil((maxy-miny)/self.resolution)),
                               int(math.ceil((maxx-minx)/self.resolution))), dtype=np.uint8)

        if self.data.size:
            minval = max(self.data.min(), 0)
            maxval = max(self.data.max(), minval+0.01)
            visible_data = ((self.data.astype(float)-minval)*255/(maxval-minval)).clip(0, 255).astype(np.uint8)
            image_data[self.y:self.y+height, self.x:self.x+width] = visible_data

        return Image.fromarray(np.flip(image_data, axis=0), 'L')


class MapHistory(GeometryIndexed):
    # metadata format:
    # 2 bytes (uint16): number of updates
    # n uptates times:
    #     4 bytes (uint32): update id
    #     8 bytes (uint64): timestamp
    dtype = np.uint16
    variant_id = 1

    def __init__(self, updates, **kwargs):
        super().__init__(**kwargs)
        self.updates = updates

    @classmethod
    def _read_metadata(cls, f, kwargs):
        num_updates = struct.unpack('<H', f.read(2))[0]
        updates = struct.unpack('<'+'II'*num_updates, f.read(num_updates*8))
        updates = list(zip(updates[0::2], updates[1::2]))
        kwargs['updates'] = updates

    def _write_metadata(self, f):
        f.write(struct.pack('<H', len(self.updates)))
        f.write(struct.pack('<'+'II'*len(self.updates), *chain(*self.updates)))

    # todo: continue
    @classmethod
    def open(cls, filename, default_update=None):
        try:
            instance = super().open(filename)
        except FileNotFoundError:
            if default_update is None:
                default_update = MapUpdate.last_processed_update()
            instance = cls(updates=[default_update], filename=filename)
        return instance

    @staticmethod
    def level_filename(level_id, mode):
        return os.path.join(settings.CACHE_ROOT, 'level_%d_history_%s' % (level_id, mode))

    @classmethod
    def open_level(cls, level_id, mode, default_update=None):
        return cls.open(cls.level_filename(level_id, mode), default_update)

    cached = {}
    cache_key = None
    cache_lock = threading.Lock()

    @classmethod
    def open_level_cached(cls, level_id, mode):
        with cls.cache_lock:
            cache_key = MapUpdate.current_processed_cache_key()
            if cls.cache_key != cache_key:
                cls.cache_key = cache_key
                cls.cached = {}
            else:
                result = cls.cached.get((level_id, mode), None)
                if result is not None:
                    return result

            result = cls.open_level(level_id, mode)
            cls.cached[(level_id, mode)] = result
            return result

    def add_geometry(self, geometry, update):
        if self.updates[-1] != update:
            self.updates.append(update)

        self[geometry] = len(self.updates) - 1

    def simplify(self):
        # remove updates that have no longer any array cells
        new_updates = ((i, update, (self.data == i)) for i, update in enumerate(self.updates))
        logger.info('before simplify: %s' % self.updates)
        logger.info(str(self.data))
        self.updates, new_affected = zip(*((update, affected) for i, update, affected in new_updates
                                           if i == 0 or affected.any()))
        logger.info('after simplify: %s' % self.updates)
        for i, affected in enumerate(new_affected):
            self.data[affected] = i

    def write(self, *args, **kwargs):
        self.simplify()
        super().write(*args, **kwargs)

    def composite(self, other, mask_geometry):
        if self.resolution != other.resolution:
            raise ValueError('Cannot composite with different resolutions.')

        self.fit_bounds(*other.bounds)
        other.fit_bounds(*self.bounds)

        # merge update lists
        self_update_i = {update: i for i, update in enumerate(self.updates)}
        other_update_i = {update: i for i, update in enumerate(other.updates)}
        new_updates = sorted(set(self_update_i.keys()) | set(other_update_i.keys()))

        # reindex according to merged update list
        other_data = other.data.copy()
        for i, update in enumerate(new_updates):
            if update in self_update_i:
                self.data[self.data == self_update_i[update]] = i
            if update in other_update_i:
                other_data[other_data == other_update_i[update]] = i

        # calculate maximum
        maximum = np.maximum(self.data, other_data)

        # add with mask
        if mask_geometry is not None:
            mask = self.get_geometry_cells(mask_geometry)
            self.data[mask] = maximum[mask]
        else:
            self.data = maximum

        # write new updates
        self.updates = new_updates
        self.simplify()

    def last_update(self, minx, miny, maxx, maxy):
        cells = self[box(minx, miny, maxx, maxy)]
        if cells.size:
            return self.updates[cells.max()]
        return self.updates[0]


class GeometryChangeTracker:
    def __init__(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()

    def register(self, level_id, geometry):
        self._geometries_by_level.setdefault(level_id, []).append(geometry)

    def level_deleted(self, level_id):
        self._deleted_levels.add(level_id)

    def reset(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()

    @property
    def area(self):
        return sum((unary_union(geometries).area
                    for level_id, geometries in self._geometries_by_level.items()
                    if level_id not in self._deleted_levels), 0)

    def finalize(self):
        for level_id in self._deleted_levels:
            try:
                os.remove(MapHistory.level_filename(level_id, mode='base'))
            except FileNotFoundError:
                pass
            self._geometries_by_level.pop(level_id, None)
        self._deleted_levels = set()

    def combine(self, other):
        self.finalize()
        other.finalize()
        for level_id, geometries in other._geometries_by_level.items():
            self._geometries_by_level.setdefault(level_id, []).extend(geometries)

    def save(self, last_update, new_update):
        self.finalize()

        for level_id, geometries in self._geometries_by_level.items():
            geometries = unary_union(geometries)
            if geometries.is_empty:
                continue
            history = MapHistory.open_level(level_id, mode='base', default_update=last_update)
            history.add_geometry(geometries.buffer(1), new_update)
            history.save()
        self.reset()


changed_geometries = GeometryChangeTracker()


def geometry_deleted(sender, instance, **kwargs):
    instance.register_delete()


def locationgroup_changed(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if not reverse:
        instance.register_change(force=True)
    else:
        if action not in 'post_clear':
            raise NotImplementedError
        query = model.objects.filter(pk__in=pk_set)
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        if issubclass(model, SpaceGeometryMixin):
            query = query.select_related('space')
        for obj in query:
            obj.register_change(force=True)


def register_signals():
    from c3nav.mapdata.models.geometry.base import GeometryMixin
    for model in get_submodels(GeometryMixin):
        post_delete.connect(geometry_deleted, sender=model)

    from c3nav.mapdata.models.locations import SpecificLocation
    for model in get_submodels(SpecificLocation):
        m2m_changed.connect(locationgroup_changed, sender=model.groups.through)
