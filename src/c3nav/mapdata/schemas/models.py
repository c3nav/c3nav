from typing import Annotated, ClassVar, Literal, Optional, Union

from ninja import Schema
from pydantic import Discriminator
from pydantic import Field as APIField
from pydantic import GetJsonSchemaHandler, NonNegativeFloat, PositiveFloat, PositiveInt
from pydantic.json_schema import JsonSchemaValue
from pydantic_core import CoreSchema

from c3nav.api.schema import GeometrySchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import (DjangoModelSchema, LabelSettingsSchema, LocationID, LocationSchema,
                                              LocationSlugSchema, SerializableSchema,
                                              SimpleGeometryBoundsAndPointSchema, SimpleGeometryBoundsSchema,
                                              SimpleGeometryLocationsSchema, SpecificLocationSchema, TitledSchema,
                                              WithAccessRestrictionSchema, WithLevelSchema,
                                              WithLineStringGeometrySchema, WithPointGeometrySchema,
                                              WithPolygonGeometrySchema, WithSpaceSchema)


class LevelSchema(SpecificLocationSchema, DjangoModelSchema):
    """
    A physical level of the map, containing building, spaces, doors…

    A level is a specific location, and can therefore be routed to and from, as well as belong to location groups.
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

    A space is a specific location, and can therefore be routed to and from, as well as belong to location groups.
    """
    outside: bool = APIField(
        title="outside only",
        description="determines whether to truncate to buildings or to the outside of buildings"
    )
    height: Optional[PositiveFloat] = APIField(
        title="ceiling height",
        description="if not set, default height for this level will be used"
    )


class DoorSchema(WithPolygonGeometrySchema, WithAccessRestrictionSchema, WithLevelSchema, DjangoModelSchema):
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

    An area is a specific location, and can therefore be routed to and from, as well as belong to location groups.
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
    color: Optional[NonEmptyStr] = APIField(
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

    A POI is a specific location, and can therefore be routed to and from, as well as belong to location groups.
    """
    pass


class LeaveDescriptionSchema(WithSpaceSchema, DjangoModelSchema):
    """
    A description for leaving a space to enter another space.
    """
    target_space: PositiveInt = APIField(
        title="target space",
        description="the space that is being entered",
    )
    descriptions: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="description (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        example={
            "en": "Stanley walked through the red door.",
            "de": "Stanley ging durch die rote Tür.",
        }
    )
    description: NonEmptyStr = APIField(
        title="description (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class CrossDescriptionSchema(WithSpaceSchema, DjangoModelSchema):
    """
    A description for crossing through a space from one space to another.
    """
    origin_space: PositiveInt = APIField(
        title="origin space",
        description="the space from which the main space is being entered",
    )
    target_space: PositiveInt = APIField(
        title="target space",
        description="the space that is being entered from the main space",
    )
    descriptions: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="description (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        example={
            "en": "Go straight ahead through the big glass doors.",
            "de": "gehe geradeaus durch die Glastüren.",
        }
    )
    description: NonEmptyStr = APIField(
        title="description (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class LocationGroupSchema(LocationSchema, DjangoModelSchema):
    """
    A location group, always belonging to a location group category.

    A location group is a (non-specific) location, which means it can be routed to and from.
    """
    category: PositiveInt = APIField(
        title="category",
        description="location group category that this location group belongs to",
    )
    priority: int = APIField()  # todo: ???
    hierarchy: int = APIField()  # todo: ???
    label_settings: Optional[LabelSettingsSchema] = APIField(
        default=None,
        title="label settings",
        description="for locations with this group, can be overwritten by specific locations"
    )
    can_report_missing: bool = APIField(
        title="report missing locations",
        description="can be used in form for reporting missing locations",
    )
    color: Optional[NonEmptyStr] = APIField(
        title="color",
        description="an optional color for spaces and areas with this group"
    )


class LocationGroupCategorySchema(TitledSchema, DjangoModelSchema):
    """
    A location group category can hold either one or multiple location groups.

    It is used to allow for having different kind of groups for different means.
    """
    name: NonEmptyStr = APIField(
        title="name/slug",
        description="name/slug of this location group category",
    )
    single: bool = APIField(
        title="single choice",
        description="if true, every location can only have one group from this category, not a list"
    )
    titles_plural: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="plural title (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        example={
            "en": "Title",
            "de": "Titel",
        }
    )
    title_plural: NonEmptyStr = APIField(
        title="plural title (preferred language)",
        description="preferred language based on the Accept-Language header."
    )
    help_texts: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="help text (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        example={
            "en": "Title",
            "de": "Titel",
        }
    )
    help_text: str = APIField(
        title="help text (preferred language)",
        description="preferred language based on the Accept-Language header."
    )
    allow_levels: bool = APIField(
        description="whether groups with this category can be assigned to levels"
    )
    allow_spaces: bool = APIField(
        description="whether groups with this category can be assigned to spaces"
    )
    allow_areas: bool = APIField(
        description="whether groups with this category can be assigned to areas"
    )
    allow_pois: bool = APIField(
        description="whether groups with this category can be assigned to POIs"
    )
    allow_dynamic_locations: bool = APIField(
        description="whether groups with this category can be assigned to dynamic locations"
    )
    priority: int = APIField()  # todo: ???


class SourceSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    A source image that can be traced in the editor.
    """
    name: NonEmptyStr = APIField(
        title="name",
        description="name/filename of the source",
    )
    bottom: float
    left: float
    top: float
    right: float


class AccessRestrictionSchema(TitledSchema, DjangoModelSchema):
    """
    A category that some objects can belong to.

    If they do, you can only see them if you have a permission to see objects with this access retriction.
    """
    open: bool
    groups: list[PositiveInt] = APIField(
        title="access restriction groups"
    )


class AccessRestrictionGroupSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    For simplicity's sake, access restrictions can belong to groups, and you can grant permissions for the entire group.
    """
    pass


class FullLevelLocationSchema(LevelSchema):
    """
    A level for the location API.
    See Level schema for details.
    """
    locationtype: Literal["level"]


class FullSpaceLocationSchema(SimpleGeometryBoundsAndPointSchema, SpaceSchema):
    """
    A space with some additional information for the location API.
    See Space schema for details.
    """
    locationtype: Literal["space"]


class FullAreaLocationSchema(SimpleGeometryBoundsAndPointSchema, AreaSchema):
    """
    An area with some additional information for the location API.
    See Area schema for details.
    """
    locationtype: Literal["area"]


class FullPOILocationSchema(SimpleGeometryBoundsSchema, POISchema):
    """
    A point of interest with some additional information for the location API.
    See POI schema for details.
    """
    locationtype: Literal["poi"]


class FullLocationGroupLocationSchema(SimpleGeometryLocationsSchema, LocationGroupSchema):
    """
    A location group with some additional information for the location API.
    See LocationGroup schema for details.
    """
    locationtype: Literal["locationgroup"]


class SlimLocationMixin(Schema):
    level: ClassVar[None]
    space: ClassVar[None]
    titles: ClassVar[None]
    access_restriction: ClassVar[None]
    can_search: ClassVar[None]
    can_describe: ClassVar[None]
    groups: ClassVar[None]


class SlimLevelLocationSchema(SlimLocationMixin, FullLevelLocationSchema):
    """
    A level for the location API with some rarely needed fields removed.
    See Level schema for details.
    """
    short_label: ClassVar[None]
    on_top_of: ClassVar[None]
    base_altitude: ClassVar[None]
    default_height: ClassVar[None]
    door_height: ClassVar[None]


class SlimSpaceLocationSchema(SlimLocationMixin, FullSpaceLocationSchema):
    """
    A space with some rarely needed fields removed and some additional information for the location API.
    See Space schema for details.
    """
    outside: ClassVar[None]
    height: ClassVar[None]


class SlimAreaLocationSchema(SlimLocationMixin, FullAreaLocationSchema):
    """
    An area with some rarely needed fields removed and some additional information for the location API.
    See Area schema for details.
    """
    slow_down_factor: ClassVar[None]


class SlimPOILocationSchema(SlimLocationMixin, FullPOILocationSchema):
    """
    A point of interest with some rarely needed fields removed and some additional information for the location API.
    See POI schema for details.
    """
    pass


class SlimLocationGroupLocationSchema(SlimLocationMixin, FullLocationGroupLocationSchema):
    """
    A locagroun group with some rarely needed fields removed and some additional information for the location API.
    See LocationGroup schema for details.
    """
    category: ClassVar[None]
    priority: ClassVar[None]
    hierarchy: ClassVar[None]
    color: ClassVar[None]
    can_report_missing: ClassVar[None]



FullLocationSchema = Annotated[
    Union[
        FullLevelLocationSchema,
        FullSpaceLocationSchema,
        FullAreaLocationSchema,
        FullPOILocationSchema,
        FullLocationGroupLocationSchema,
    ],
    Discriminator("locationtype"),
]

SlimLocationSchema = Annotated[
    Union[
        SlimLevelLocationSchema,
        SlimSpaceLocationSchema,
        SlimAreaLocationSchema,
        SlimPOILocationSchema,
        SlimLocationGroupLocationSchema,
    ],
    Discriminator("locationtype"),
]


class DisplayLink(Schema):
    """
    A link for the location display
    """
    id: PositiveInt
    slug: NonEmptyStr
    title: NonEmptyStr
    can_search: bool


class LocationDisplay(SerializableSchema):
    id: LocationID = APIField(
        description="a numeric ID for a map location or a string ID for generated locations",
    )
    level: Optional[PositiveInt] = APIField(
        None,
        description="level ID, if applicable"
    )
    space: Optional[PositiveInt] = APIField(
        None,
        description="space ID, if applicable"
    )
    display: list[
        tuple[
            Annotated[NonEmptyStr, APIField(name="field title")],
            Annotated[Union[
                Annotated[str, APIField(name="a simple string value")],
                Annotated[DisplayLink, APIField(namen="a link value")],
                Annotated[list[DisplayLink], APIField(name="a list of link values")],
                Annotated[Literal[None], APIField(name="no value")]
            ], APIField(name="field value", union_mode='left_to_right')]
        ]
    ] = APIField(description="a list of human-readable display values")
    geometry: Optional[GeometrySchema] = APIField(
        None, description="representative geometry, if available"
    )
    editor_url: Optional[NonEmptyStr] = APIField(
        None, description="path to edit this object in the editor, if the user has access to it",
    )
