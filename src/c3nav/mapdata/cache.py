import math
import struct

import numpy as np
from django.conf import settings
from django.db.models.signals import m2m_changed, post_delete
from shapely import prepared
from shapely.geometry import box

from c3nav.mapdata.utils.models import get_submodels


class MapHistory:
    # binary format (everything little-endian):
    # 1 byte (uint8): resolution
    # 2 bytes (uint16): origin x
    # 2 bytes (uint16): origin y
    # 2 bytes (uint16): origin width
    # 2 bytes (uint16): origin height
    # 2 bytes (uint16): number of updates
    # n*16 bytes: update keys as null-terminated strings
    # width*height*2 bytes: data (line after line) with uint16 data

    def __init__(self, resolution=settings.CACHE_RESOLUTION, x=None, y=None, updates=None, data=None):
        self.resolution = resolution
        self.x = None
        self.y = None
        self.updates = updates
        self.data = data
        self.unfinished = False

    @classmethod
    def open(cls, filename, default_update=None):
        try:
            with open(filename, 'rb') as f:
                resolution, x, y, width, height, num_updates = struct.unpack('<BHHHHH', f.read(11))
                updates = list(struct.unpack('16s'*num_updates, f.read(num_updates*16)))
                data = np.frombuffer(f.read(width*height*2), np.uint16).reshape((height, width))
                return cls(resolution, x, y, list(updates), data)
        except FileNotFoundError:
            if default_update is None:
                raise
            return cls(updates=[default_update])

    def save(self, filename):
        with open(filename, 'wb') as f:
            f.write(struct.pack('<BHHHHH', self.resolution, self.x, self.y, *reversed(self.data.shape),
                                len(self.updates)))
            f.write(struct.pack('16s'*len(self.updates), *self.updates))
            f.write(self.data.tobytes('C'))

    def add_new(self, geometry):
        prep = prepared.prep(geometry)
        minx, miny, maxx, maxy = geometry.bounds
        res = self.resolution
        minx = int(math.floor(minx/res))
        miny = int(math.floor(miny/res))
        maxx = int(math.ceil(maxx/res))
        maxy = int(math.ceil(maxy/res))

        data = self.data
        if self.resolution != settings.CACHE_RESOLUTION:
            data = None
            self.updates = self.updates[-1:]

        if data is None:
            data = np.zeros(((maxy-miny), (maxx-minx)), dtype=np.uint16)
            self.x, self.y = minx, miny
        else:
            orig_height, orig_width = data.shape
            if minx < self.x or miny < self.y or maxx > self.x+orig_width or maxy > self.y+orig_height:
                new_x, new_y = min(minx, self.x), min(miny, self.y)
                new_width = min(maxx, self.x+orig_width)-new_x
                new_height = min(maxy, self.y+orig_height)-new_y
                new_data = np.zeros((new_height, new_width), dtype=np.uint16)
                dx, dy = new_x-self.x, new_y-self.y
                new_data[dy:dx, (dy+orig_height):(dx+orig_width)] = data
                data = new_data
                self.x, self.y = new_x, new_y

        new_val = len(self.updates)
        for iy, y in enumerate(range(miny*res, maxy*res, res), start=miny-self.y):
            for ix, x in enumerate(range(miny*res, maxy*res, res), start=minx-self.x):
                if prep.intersects(box(x, y, x+res, y+res)):
                    data[iy, ix] = new_val

        self.unfinished = True

    def finish(self, cache_key):
        self.unfinished = False
        self.updates.append(cache_key)


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
