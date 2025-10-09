import operator
from functools import reduce

from django.core import checks
from shapely.geometry.base import BaseGeometry


try:
    import rtree
except OSError:
    rtree_index = False

    class Index:
        def __init__(self):
            self.objects = {}

        def insert(self, value: int, geometry):
            self.objects[value] = geometry

        def delete(self, value: int):
            self.objects.pop(value)

        def intersection(self, geometry) -> set[int]:
            raise ValueError("abc")
            return set(self.objects.keys())
else:
    rtree_index = True

    class Index:
        def __init__(self):
            self._index = rtree.index.Index(interleaved=True)
            self._bounds = {}

        def insert(self, value: int, geometry):
            try:
                geoms = geometry.geoms
            except AttributeError:
                self._bounds.setdefault(value, []).append(geometry.bounds)
                self._index.insert(value, geometry.bounds)
            else:
                for geom in geoms:
                    self.insert(value, geom)

        def delete(self, value: int):
            for bounds in self._bounds.pop(value):
                self._index.delete(value, bounds)

        def intersection(self, geometry: BaseGeometry) -> set[int]:
            try:
                geoms = geometry.geoms
            except AttributeError:
                return set(self._index.intersection(geometry.bounds))
            else:
                return reduce(operator.__or__, (self.intersection(geom) for geom in geoms), set())


@checks.register()
def check_svg_renderer(app_configs, **kwargs):
    errors = []
    if not rtree_index:
        errors.append(
            checks.Warning(
                'The libspatialindex_c library is missing. This will slow down c3nav in future versions.',
                obj='rtree.index.Index',
                id='c3nav.mapdata.W002',
            )
        )
    return errors
