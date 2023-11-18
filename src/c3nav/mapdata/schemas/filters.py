from typing import Literal, Optional

from ninja import Schema
from pydantic import Field as APIField


class LevelFilters(Schema):
    on_top_of: Optional[Literal["null"] | int] = APIField(
        None,
        name='filter by on top of level ID (or "null")',
        description='if set, only levels on top of this level (or "null" for no level) will be shown'
    )
    group: Optional[int] = APIField(
        None,
        name="filter by location group"
    )
