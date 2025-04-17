import operator
import struct
from functools import reduce
from os import PathLike
from typing import Self, Iterator, Union, TYPE_CHECKING

import numpy as np
from numpy.typing import NDArray

if TYPE_CHECKING:
    from shapely import Polygon, MultiPolygon

from c3nav.mapdata.utils.cache.indexed import LevelGeometryIndexed


class AccessRestrictionAffected(LevelGeometryIndexed):
    # metadata format:
    # 64 times:
    #     4 bytes (uint32): access restriction id (or 0x00 if empty)
    # each uint64 cell contains a bitmask of restrictions.
    # e.g.: 2^n bit set → restriction with index 2^n does apply
    dtype = np.uint64
    variant_id = 2
    variant_name = 'restrictions'

    def __init__(self, restrictions: list[int] = None, **kwargs):
        super().__init__(**kwargs)
        self.restrictions: list[int] = [] if restrictions is None else restrictions
        self.restrictions_lookup: dict[int, int] = {restriction: i for i, restriction in enumerate(self.restrictions)}

    @classmethod
    def _read_metadata(cls, f, kwargs: dict):
        restrictions = list(struct.unpack('<'+'I'*64, f.read(4*64)))
        while restrictions and restrictions[-1] == 0:
            restrictions.pop()
        kwargs['restrictions'] = restrictions

    def _write_metadata(self, f):
        f.write(struct.pack('<'+'I'*64, *self.restrictions, *((0, )*(64-len(self.restrictions)))))

    @classmethod
    def build(cls, access_restriction_affected) -> Self:
        result = cls()
        for restriction, area in access_restriction_affected.items():
            result[area.buffer(1)].add(restriction)
        return result

    @classmethod
    def open(cls, filename: str | bytes | PathLike) -> Self:
        try:
            instance = super().open(filename)
        except FileNotFoundError:
            instance = cls(restrictions=[], filename=filename)
        return instance

    def get_restriction_index(self, restriction: int, create=False) -> int:
        i = self.restrictions_lookup.get(restriction)
        if create and i is None:
            i = len(self.restrictions)
            self.restrictions_lookup[restriction] = i
            self.restrictions.append(restriction)
        return i

    def __getitem__(self, selector: Union[tuple[slice, slice], 'Polygon', 'MultiPolygon']) -> "AccessRestrictionAffectedCells":
        return AccessRestrictionAffectedCells(self, selector)

    def __setitem__(self, selector, value):
        raise TypeError('__setitem__ not supported for AccessRestriction matrix')


class AccessRestrictionAffectedCells:
    def __init__(self, parent: AccessRestrictionAffected,
                 selector: Union[tuple[slice, slice], 'Polygon','MultiPolygon']):
        self.parent = parent
        self.selector = selector
        self.values = self._get_values()

    def _get_values(self) -> NDArray:
        return LevelGeometryIndexed.__getitem__(self.parent, self.selector)

    def _set(self, values: NDArray):
        self.values = values
        LevelGeometryIndexed.__setitem__(self.parent, self.selector, values)

    def __contains__(self, restriction: int):
        i = self.parent.get_restriction_index(restriction)
        return (self.values & (2**i)).any()

    def add(self, restriction: int):
        from shapely.geometry.base import BaseGeometry
        if not isinstance(self.selector, BaseGeometry):
            raise TypeError('Can only add restrictions with Geometry based selectors')

        # expand array
        bounds = self.parent.get_geometry_bounds(self.selector)
        self.parent.fit_bounds(*bounds)
        self.values = self._get_values()

        i = self.parent.get_restriction_index(restriction, create=True)
        self._set(self.values | (2**i))

    def discard(self, restriction: int):
        from shapely.geometry.base import BaseGeometry
        if not isinstance(self.selector, BaseGeometry):
            raise TypeError('Can only discard restrictions with Geometry based selectors')

        i = self.parent.get_restriction_index(restriction)
        self._set(self.values & ((2**64-1) ^ (2**i)))

    def __iter__(self) -> Iterator[int]:
        all = reduce(operator.or_, self.values.tolist(), 0)
        yield from (restriction for i, restriction in enumerate(self.parent.restrictions) if (all & 2**i))
