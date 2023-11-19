from typing import Optional

from pydantic import Field as APIField
from pydantic import NonNegativeFloat, PositiveFloat, PositiveInt
from pydantic.color import Color

from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import (AccessRestrictionSchema, DjangoModelSchema, SpecificLocationSchema,
                                              WithLevelSchema, WithLineStringGeometrySchema, WithPointGeometrySchema,
                                              WithPolygonGeometrySchema, WithSpaceSchema)


class LevelSchema(SpecificLocationSchema, DjangoModelSchema):
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


class BuildingSchema(WithPolygonGeometrySchema, WithLevelSchema, DjangoModelSchema):
    """
    A non-outdoor part of the map.
    """
    pass


class SpaceSchema(WithPolygonGeometrySchema, SpecificLocationSchema, WithLevelSchema, DjangoModelSchema):
    """
    An accessible area on a level. It can be outside-only or inside-only.

    A space is a specific location, and can therefor be routed to and from, as well as belong to location groups.
    """
    outside: bool = APIField(
        title="outside only",
        description="determines whether to truncate to buildings or to the outside of buildings"
    )
    height: Optional[PositiveFloat] = APIField(
        title="ceiling height",
        description="if not set, default height for this level will be used"
    )


class DoorSchema(WithPolygonGeometrySchema, AccessRestrictionSchema, WithLevelSchema, DjangoModelSchema):
    """
    A link between two spaces
    """
    pass


class HoleSchema(WithPolygonGeometrySchema, WithSpaceSchema):
    """
    A hole in a space, showing the levels below
    """
    pass


class AreaSchema(WithPolygonGeometrySchema, SpecificLocationSchema, WithSpaceSchema, DjangoModelSchema):
    """
    An area inside a space.

    An area is a specific location, and can therefor be routed to and from, as well as belong to location groups.
    """
    slow_down_factor: PositiveFloat = APIField(
        title="slow-down factor",
        description="how much walking in this area is slowed down, overlapping areas are multiplied"
    )


class StairSchema(WithLineStringGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    A line sharply dividing the accessible surface of a space into two different altitudes.
    """
    pass


class RampSchema(WithPolygonGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    An area in which the surface has an altitude gradient.
    """
    pass


class BaseObstacleSchema(WithSpaceSchema, DjangoModelSchema):
    height: PositiveFloat = APIField(
        title="height",
        description="size of the obstacle in the z dimension"
    )
    altitude: NonNegativeFloat = APIField(
        title="altitude above ground",
        description="altitude above ground"
    )
    color: Optional[Color] = APIField(
        title="color",
        description="an optional color for this obstacle"
    )


class ObstacleSchema(WithPolygonGeometrySchema, BaseObstacleSchema):
    """
    An obstacle to be subtracted from the accessible surface of a space.
    """
    pass


class LineObstacleSchema(WithLineStringGeometrySchema, BaseObstacleSchema):
    """
    An obstacle to be subtracted from the accessible surface of a space, defined as a line with width.
    """
    width: PositiveFloat = APIField(
        title="width",
        description="width of the line"
    )


class ColumnSchema(WithPolygonGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    A ceiling-high obstacle subtracted from the space, effectively creating a "building" again.
    """
    pass


class POISchema(WithPointGeometrySchema, SpecificLocationSchema, WithSpaceSchema, DjangoModelSchema):
    """
    A point of interest inside a space.

    A POI is a specific location, and can therefor be routed to and from, as well as belong to location groups.
    """
    pass
