from typing import Annotated, Union

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import GeometrySchema
from c3nav.mapdata.schemas.model_base import AnyLocationID, BoundsSchema


class WithBoundsSchema(Schema):
    """
    Describing a bounding box
    """
    bounds: BoundsSchema = APIField(
        title="boundaries",
        description="(left, bottom) to (top, right)",
    )


class LocationGeometry(Schema):
    id: AnyLocationID = APIField(
        description="ID of the location that the geometry is being queried for",
    )
    level: Union[
        Annotated[PositiveInt, APIField(title="level ID")],
        Annotated[None, APIField(title="null", description="geometry is not on any level")],  # todo: possible?
    ] = APIField(
        description="ID of the level the geometry is on",
    )
    geometry: Union[
        GeometrySchema,
        Annotated[None, APIField(title="null", description="no geometry available")]
    ] = APIField(
        description="geometry, if available"
    )
