from typing import Annotated, Optional

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import GeometrySchema
from c3nav.mapdata.schemas.model_base import AnyLocationID


class BoundsSchema(Schema):
    """
    Describing a bounding box
    """
    bounds: tuple[
        Annotated[tuple[
            Annotated[float, APIField(title="left", description="lowest X coordindate")],
            Annotated[float, APIField(title="bottom", description="lowest Y coordindate")]
        ], APIField(title="(left, bottom)", description="lowest coordinates", example=(-10, -20))],
        Annotated[tuple[
            Annotated[float, APIField(title="right", description="highest X coordindate")],
            Annotated[float, APIField(title="top", description="highest Y coordindate")]
        ], APIField(title="(right, top)", description="highest coordinates", example=(20, 30))]
    ] = APIField(
        title="boundaries",
        description="(left, bottom) to (top, right)",
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
