from typing import Optional

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import GeometrySchema
from c3nav.mapdata.schemas.model_base import AnyLocationID


class BoundsSchema(Schema):
    """
    Describing a bounding box
    """
    bounds: tuple[tuple[float, float], tuple[float, float]] = APIField(
        description="(x, y) to (x, y)",
        example=((-10, -20), (20, 30)),
    )


class LocationGeometry(Schema):
    id: AnyLocationID = APIField(
        description="ID of the location that the geometry is being queried for",
    )
    level: Optional[PositiveInt] = APIField(
        description="ID of the level the geometry is on",
    )
    geometry: Optional[GeometrySchema] = APIField(
        description="geometry, if available"
    )
