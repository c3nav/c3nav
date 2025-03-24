from typing import NamedTuple, Self

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

    @property
    def folder_name(self) -> str:
        return f"update-{self.update_id:010d}"

    @property
    def as_legacy(self) -> tuple[int, int]:
        return self.update_id, self.timestamp // 1_000_000

    @classmethod
    def from_legacy(cls, val: tuple[int, int]) -> Self:
        return cls(timestamp=val[1]*1_000_000, job_id=0, update_id=val[0])
