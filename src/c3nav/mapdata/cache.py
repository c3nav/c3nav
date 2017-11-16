import logging
import math
import os
import struct
import threading
import traceback
from itertools import chain

import numpy as np
from django.conf import settings
from django.db.models.signals import m2m_changed, post_delete
from PIL import Image
from shapely import prepared
from shapely.geometry import box
from shapely.ops import unary_union

from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.utils.models import get_submodels

logger = logging.getLogger('c3nav')


class MapHistory:
    # binary format (everything little-endian):
    # 1 byte (uint8): resolution
    # 2 bytes (uint16): origin x
    # 2 bytes (uint16): origin y
    # 2 bytes (uint16): origin width
    # 2 bytes (uint16): origin height
    # 2 bytes (uint16): number of updates
    # n uptates times:
    #     4 bytes (uint32): update id
    #     4 bytes (uint32): timestamp
    # width*height*2 bytes:
    #     data array (line after line) with uint16 cells
    empty_array = np.empty((0, 0), dtype=np.uint16)

    def __init__(self, resolution=settings.CACHE_RESOLUTION, x=0, y=0, updates=None, data=empty_array, filename=None):
        self.resolution = resolution
        self.x = x
        self.y = y
        self.updates = updates
        self.data = data
        self.filename = filename
        self.unfinished = False

    @classmethod
    def open(cls, filename, default_update=None):
        try:
            with open(filename, 'rb') as f:
                resolution, x, y, width, height, num_updates = struct.unpack('<BHHHHH', f.read(11))
                updates = struct.unpack('<'+'II'*num_updates, f.read(num_updates*8))
                updates = list(zip(updates[0::2], updates[1::2]))
                # noinspection PyTypeChecker
                data = np.fromstring(f.read(width*height*2), np.uint16).reshape((height, width))
                return cls(resolution, x, y, list(updates), data, filename)
        except (FileNotFoundError, struct.error) as e:
            logger.info('Exception in MapHistory loading! %s' % traceback.format_exc())
            if default_update is None:
                default_update = MapUpdate.last_update()
            new_empty = cls(updates=[default_update], filename=filename)
            new_empty.save(filename)
            return new_empty

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

    def save(self, filename=None):
        if filename is None:
            filename = self.filename
        with open(filename, 'wb') as f:
            self.write(f)

    def write(self, f):
        f.write(struct.pack('<BHHHHH', self.resolution, self.x, self.y, *reversed(self.data.shape),
                            len(self.updates)))
        f.write(struct.pack('<'+'II'*len(self.updates), *chain(*self.updates)))
        f.write(self.data.tobytes('C'))

    def add_new(self, geometry, data=None):
        logging.info('add_new called, res=%d, x=%d, y=%d, shape=%s, updates=%s' %
                     (self.resolution, self.x, self.y, self.data.shape, self.updates))

        prep = prepared.prep(geometry)
        minx, miny, maxx, maxy = geometry.bounds
        res = self.resolution
        minx = int(math.floor(minx/res))
        miny = int(math.floor(miny/res))
        maxx = int(math.ceil(maxx/res))
        maxy = int(math.ceil(maxy/res))

        logging.info('minx=%d, miny=%d, maxx=%d, maxy=%d' % (minx, miny, maxx, maxy))

        direct = data is None

        if direct:
            logging.info('direct!')
            data = self.data
            if self.resolution != settings.CACHE_RESOLUTION:
                logging.info('cache_resolution does not match')
                data = None
                self.updates = self.updates[-1:]

            if not data.size:
                logging.info('data is empty, creating new map')
                data = np.zeros(((maxy-miny), (maxx-minx)), dtype=np.uint16)
                logging.info('data is empty, created new! shape=%s' % (data.shape, ))
                self.x, self.y = minx, miny
            else:
                logging.info('resize?')
                orig_height, orig_width = data.shape
                if minx < self.x or miny < self.y or maxx > self.x+orig_width or maxy > self.y+orig_height:
                    logging.info('resize!')
                    new_x, new_y = min(minx, self.x), min(miny, self.y)
                    new_width = max(maxx, self.x+orig_width)-new_x
                    new_height = max(maxy, self.y+orig_height)-new_y
                    new_data = np.zeros((new_height, new_width), dtype=np.uint16)
                    dx, dy = self.x-new_x, self.y-new_y
                    new_data[dy:(dy+orig_height), dx:(dx+orig_width)] = data
                    data = new_data
                    self.x, self.y = new_x, new_y
                logging.info('')
                logging.info('add_new called, dx=%d, dy=%d, x=%d, y=%d, shape=%s' %
                             (self.resolution, self.x, self.y, data.shape, self.updates))
        else:
            logging.info('not direct!')
            height, width = data.shape
            minx, miny = max(minx, self.x), max(miny, self.y)
            maxx, maxy = min(maxx, self.x+width), min(maxy, self.y+height)

        new_val = len(self.updates) if direct else 1
        i = 0
        for iy, y in enumerate(range(miny*res, maxy*res, res), start=miny-self.y):
            for ix, x in enumerate(range(minx*res, maxx*res, res), start=minx-self.x):
                if prep.intersects(box(x, y, x+res, y+res)):
                    data[iy, ix] = new_val
                    i += 1
        logging.info('%d points changed' % i)

        if direct:
            logging.info('saved data')
            self.data = data
            self.unfinished = True
        else:
            return data

    def finish(self, update):
        self.unfinished = False
        self.updates.append(update)
        self.simplify()

    def simplify(self):
        logging.info('simplify!')
        # remove updates that have no longer any array cells
        new_updates = ((update, (self.data == i)) for i, update in enumerate(self.updates))
        logging.info('before: %s' % (self.updates, ))
        self.updates, new_affected = zip(*((update, affected) for update, affected in new_updates if affected.any()))
        logging.info('after: %s' % (self.updates, ))
        for i, affected in enumerate(new_affected):
            self.data[affected] = i

        # remove borders
        rows = self.data.any(axis=1).nonzero()[0]
        logging.info('rows: %s' % rows)
        if not rows.size:
            logging.info('no rows, empty_array')
            self.data = self.empty_array
            self.x = 0
            self.y = 0
            return
        cols = self.data.any(axis=0).nonzero()[0]
        logging.info('cols: %s' % cols)
        miny, maxy = rows.min(), rows.max()
        minx, maxx = cols.min(), cols.max()
        logging.info('minx=%d, miny=%d, maxx=%d, maxy=%d' % (minx, miny, maxx, maxy))
        self.x += minx
        self.y += miny
        self.data = self.data[miny:maxy+1, minx:maxx+1]

    def composite(self, other, mask_geometry):
        if other.resolution != other.resolution:
            return

        # check overlapping area
        self_height, self_width = self.data.shape
        other_height, other_width = other.data.shape
        minx, miny = max(self.x, other.x), max(self.y, other.y)
        maxx = min(self.x+self_width-1, other.x+other_width-1)
        maxy = min(self.y+self_height-1, other.y+other_height-1)
        if maxx < minx or maxy < miny:
            return

        # merge update lists
        self_update_i = {update: i for i, update in enumerate(self.updates)}
        other_update_i = {update: i for i, update in enumerate(other.updates)}
        new_updates = sorted(set(self_update_i.keys()) | set(other_update_i.keys()))

        # create slices
        self_slice = slice(miny-self.y, maxy-self.y+1), slice(minx-self.x, maxx-self.x+1)
        other_slice = slice(miny-other.y, maxy-other.y+1), slice(minx-other.x, maxx-other.x+1)

        # reindex according to new update list
        other_data = np.zeros_like(self.data)
        other_data[self_slice] = other.data[other_slice]
        for i, update in enumerate(new_updates):
            if update in self_update_i:
                self.data[self.data == self_update_i[update]] = i
            if update in other_update_i:
                other_data[other_data == other_update_i[update]] = i

        # calculate maximum
        maximum = np.maximum(self.data, other_data)

        # add with mask
        if mask_geometry is not None:
            mask = self.add_new(mask_geometry.buffer(1), data=np.zeros_like(self.data, dtype=np.bool))
            self.data[mask] = maximum[mask]
        else:
            self.data = maximum

        # write new updates
        self.updates = new_updates

        self.simplify()

    def to_image(self):
        from c3nav.mapdata.models import Source
        (minx, miny), (maxx, maxy) = Source.max_bounds()

        height, width = self.data.shape
        image_data = np.zeros((int(math.ceil((maxy-miny)/self.resolution)),
                               int(math.ceil((maxx-minx)/self.resolution))), dtype=np.uint8)
        visible_data = (self.data.astype(float)*255/(len(self.updates)-1)).clip(0, 255).astype(np.uint8)
        image_data[self.y:self.y+height, self.x:self.x+width] = visible_data

        return Image.fromarray(np.flip(image_data, axis=0), 'L')

    def last_update(self, minx, miny, maxx, maxy):
        res = self.resolution
        height, width = self.data.shape
        minx = max(int(math.floor(minx/res)), self.x)-self.x
        miny = max(int(math.floor(miny/res)), self.y)-self.y
        maxx = min(int(math.ceil(maxx/res)), self.x+width)-self.x
        maxy = min(int(math.ceil(maxy/res)), self.y+height)-self.y
        if minx >= maxx or miny >= maxy:
            return self.updates[0]
        return self.updates[self.data[miny:maxy, minx:maxx].max()]


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
            history.add_new(geometries.buffer(1))
            history.finish(new_update)
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
