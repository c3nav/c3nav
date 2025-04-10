import os

from shapely.ops import unary_union

from c3nav.mapdata.utils.cache.maphistory import MapHistory
from c3nav.mapdata.utils.cache.types import MapUpdateTuple


class GeometryChangeTracker:
    def __init__(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()
        self._unary_unions = {}

    def register(self, level_id, geometry):
        self._geometries_by_level.setdefault(level_id, []).append(geometry.buffer(0.01))
        self._unary_unions.pop(level_id, None)

    def level_deleted(self, level_id):
        self._deleted_levels.add(level_id)
        self._unary_unions.pop(level_id, None)

    def reset(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()
        self._unary_unions = {}

    def _get_unary_union(self, level_id):
        union = self._unary_unions.get(level_id)
        if union is None:
            union = unary_union(self._geometries_by_level[level_id])
            self._unary_unions[level_id] = union
        return union

    @property
    def is_empty(self):
        return not self._geometries_by_level

    @property
    def area(self):
        return sum((self._get_unary_union(level_id).area
                    for level_id in self._geometries_by_level.keys()
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
        for level_id in other._geometries_by_level.keys():
            self._geometries_by_level.setdefault(level_id, []).append(other._get_unary_union(level_id))
        self._unary_unions = {}

    def save(self, last_update: MapUpdateTuple, new_update: MapUpdateTuple):
        self.finalize()

        for level_id, geometries in self._geometries_by_level.items():
            geometries = unary_union(geometries)
            if geometries.is_empty:
                continue
            # todo: is new_update really better here? we sure hope it is
            history = MapHistory.open_level(level_id, mode='base', default_update=new_update)
            history.add_geometry(geometries.buffer(1), new_update)
            history.save()
        self.reset()


changed_geometries = GeometryChangeTracker()  # todo: no longer needed if we use the overlay stuff
