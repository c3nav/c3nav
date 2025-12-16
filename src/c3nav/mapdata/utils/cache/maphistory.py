import struct
from itertools import chain
from os import PathLike
from typing import Optional, Self, TYPE_CHECKING, Union

import numpy as np

from c3nav.mapdata.utils.cache.types import MapUpdateTuple
from c3nav.mapdata.utils.cache.indexed import LevelGeometryIndexed

if TYPE_CHECKING:
    from shapely import Polygon, MultiPolygon


class MapHistory(LevelGeometryIndexed):
    # metadata format:
    # 2 bytes (uint16): number of updates
    # n updates times:
    #     4 bytes (uint32): update id
    #     4 bytes (uint32): timestamp
    # each uint16 cell contains the index of the newest update
    dtype = np.uint16
    variant_id = 1
    variant_name = 'history'

    def __init__(self, updates: list[MapUpdateTuple], **kwargs):
        super().__init__(**kwargs)
        self.updates = updates

    @classmethod
    def _read_metadata(cls, f, kwargs: dict):
        num_updates = struct.unpack('<H', f.read(2))[0]
        updates = struct.unpack('<'+'II'*num_updates, f.read(num_updates*8))
        updates = list(zip(updates[0::2], updates[1::2]))
        kwargs['updates'] = updates

    def _write_metadata(self, f):
        f.write(struct.pack('<H', len(self.updates)))
        f.write(struct.pack('<'+'II'*len(self.updates), *chain(*self.updates)))

    @classmethod
    def open(cls, filename: str | bytes | PathLike, default_update: Optional[MapUpdateTuple] = None) -> Self:
        try:
            instance = super().open(filename)
        except FileNotFoundError:
            if default_update is None:
                from c3nav.mapdata.models import MapUpdate
                default_update = MapUpdate.last_processed_update()
            instance = cls(updates=[default_update], filename=filename)
            instance.save()
        return instance

    def add_geometry(self, geometry: Union["Polygon", "MultiPolygon"], update: MapUpdateTuple):
        if self.updates[-1] != update:
            self.updates.append(update)

        self[geometry] = len(self.updates) - 1

    def simplify(self):
        # remove updates that have no longer any array cells
        new_updates = ((i, update, (self.data == i)) for i, update in enumerate(self.updates))
        new_updates, new_affected = zip(*((update, affected) for i, update, affected in new_updates
                                          if i == 0 or affected.any()))
        self.updates = list(new_updates)
        for i, affected in enumerate(new_affected):
            self.data[affected] = i

    def write(self, *args, **kwargs):
        self.simplify()
        super().write(*args, **kwargs)

    def composite(self, other: Self, mask_geometry: Optional[Union["Polygon", "MultiPolygon"]]):
        if self.resolution != other.resolution:
            raise ValueError('Cannot composite with different resolutions.')

        self.fit_bounds(*other.bounds)
        other.fit_bounds(*self.bounds)

        # merge update lists
        self_update_i = {update: i for i, update in enumerate(self.updates)}
        other_update_i = {update: i for i, update in enumerate(other.updates)}
        new_updates = sorted(set(self_update_i.keys()) | set(other_update_i.keys()))

        # reindex according to merged update list
        self_data = self.data.copy()
        other_data = other.data.copy()
        for i, update in enumerate(new_updates):
            if update in self_update_i:
                self.data[self_data == self_update_i[update]] = i
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

    def last_update(self, minx: float, miny: float, maxx: float, maxy: float) -> MapUpdateTuple:
        cells = self[minx:maxx, miny:maxy]
        if cells.size:
            return self.updates[cells.max()]
        return self.updates[0]

    def to_dict(self) -> dict:
        return {
            **super().to_dict(),
            "updates": self.updates,
            "updates_data": [
                [self.updates[cell] for cell in row]
                for row in self.data.tolist()
            ],
        }
