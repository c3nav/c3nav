from typing import Optional

from ninja import Schema, Swagger
from pydantic import Field as APIField
from pydantic import PositiveFloat, PositiveInt

from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import SpecificLocationSchema


class LevelSchema(SpecificLocationSchema):
    """
    A physical level of the map, containing building, spaces, doors…

    A level is a specific location, and can therefor be routed to and from, as well as belong to location groups.
    """
    short_label: NonEmptyStr = APIField(
        title="short label (for level selector)",
        description="unique among levels",
    )
    on_top_of: Optional[PositiveInt] = APIField(
        title="on top of level ID",
        description="if set, this is not a main level, but it's on top of this other level"
    )
    base_altitude: float = APIField(
        title="base/default altitude",
    )
    default_height: PositiveFloat = APIField(
        title="default ceiling height",
    )
    door_height: PositiveFloat = APIField(
        title="door height",
    )

    class Config(Schema.Config):
        title = "Level"
