from typing import NamedTuple

from django.utils.http import int_to_base36


class MapUpdateTuple(NamedTuple):
    mapupdate_id: int
    timestamp: int

    @property
    def cache_key(self):
        return int_to_base36(self.mapupdate_id) + '_' + int_to_base36(self.timestamp)
