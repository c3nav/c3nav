from typing import Annotated, Union, Optional

from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import BaseSchema, GeometrySchema
from c3nav.mapdata.grid import GridSchema
from c3nav.mapdata.schemas.model_base import AnyLocationID, BoundsSchema


class MapSettingsSchema(BaseSchema):
    """
    various c3nav instance settings
    """
    initial_bounds: Optional[BoundsSchema] = APIField(
        title="initial boundaries",
        description="(left, bottom) to (top, right)",
    )
    initial_level: Optional[PositiveInt] = APIField(
        title="initial level id",
        description="the level id that is intially shown when opening the map",
    )

    grid: Optional[GridSchema] = APIField(
        title="grid config",
        description="grid configuration, if available",
    )
    tile_server: Optional[str] = APIField(
        title="tile server base URL",
        description="tile server base URL to use, if configured",
    )


class WithBoundsSchema(BaseSchema):
    """
    Describing a bounding box
    """
    bounds: BoundsSchema = APIField(
        title="boundaries",
        description="(left, bottom) to (top, right)",
    )


class LocationGeometry(BaseSchema):
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
