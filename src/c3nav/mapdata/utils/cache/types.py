from typing import NamedTuple

from django.utils.http import int_to_base36


class MapUpdateTuple(NamedTuple):
    timestamp: int
    job_id: int
    update_id: int

    @property
    def cache_key(self):
        return '_'.join(int_to_base36(i) for i in self)

    @classmethod
    def get_empty(cls):
        return cls(0, 0, 0)
