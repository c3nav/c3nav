from typing import Annotated, ClassVar, Literal, Optional, Union

from ninja import Schema
from pydantic import Discriminator
from pydantic import Field as APIField
from pydantic import NonNegativeFloat, PositiveFloat, PositiveInt

from c3nav.api.schema import GeometrySchema, PointSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import (AnyLocationID, AnyPositionID, CustomLocationID, DjangoModelSchema,
                                              LabelSettingsSchema, LocationSchema, PositionID, SerializableSchema,
                                              SimpleGeometryLocationsSchema, SimpleGeometryPointAndBoundsSchema,
                                              SimpleGeometryPointSchema, SpecificLocationSchema, TitledSchema,
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


class DynamicLocationSchema(SpecificLocationSchema, DjangoModelSchema):
    """
    A dynamic location represents a moving object. Its position has to be separately queries through the position API.

    A dynamic location is a specific location, and can therefore be routed to and from,
    as well as belong to location groups.
    """
    pass


class SourceSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    A source image that can be traced in the editor.
    """
    name: NonEmptyStr = APIField(
        title="name",
        description="name/filename of the source",
    )
    bounds: tuple[
        tuple[
            Annotated[float, APIField(name="left")],
            Annotated[float, APIField(name="bottom")],
        ],
        tuple[
            Annotated[float, APIField(name="right")],
            Annotated[float, APIField(name="top")],
        ]
    ]


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


class CustomLocationSchema(SerializableSchema):
    """
    A custom location represents coordinates that have been put in or calculated.

    A custom location is a location, so it can be routed to and from.
    """
    id: CustomLocationID = APIField(
        description="ID representing the coordinates"
    )
    slug: CustomLocationID = APIField(
        description="slug, identical to ID"
    )
    icon: Optional[NonEmptyStr] = APIField(
        default=None,
        title="icon name",
        description="any material design icon name"
    )
    title: NonEmptyStr = APIField(
        title="title (preferred language)",
        description="preferred language based on the Accept-Language header."
    )
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location. "
                    "preferred language based on the Accept-Language header."
    )
    level: PositiveInt = APIField(
        description="level ID this custom location is located on"
    )
    space: Optional[PositiveInt] = APIField(
        description="space ID this custom location is located in, if applicable"
    )
    areas: list[PositiveInt] = APIField(
        description="IDs of areas this custom location is located in"
    )
    grid_square: Optional[NonEmptyStr] = APIField(
        default=None,
        title="grid square",
        description="if a grid is defined and this custom location is within it",
    )
    near_area: Optional[PositiveInt] = APIField(
        description="the ID of an area near this custom location, if there is one"
    )
    near_poi: Optional[PositiveInt] = APIField(
        description="the ID of a POI near this custom location, if there is one"
    )
    nearby: list[PositiveInt] = APIField(
        description="list of IDs of nearby locations"
    )
    altitude: Optional[float] = APIField(
        description="ground altitude (in the map-wide coordinate system), if it can be determined"
    )
    geometry: Optional[PointSchema] = APIField(
        None,
        description="point geometry for this custom location",
    )


class TrackablePositionSchema(Schema):
    """
    A trackable position. It's position can be set or reset.
    """
    id: PositionID = APIField(
        description="ID representing the position"
    )
    slug: PositionID = APIField(
        description="slug representing the position"
    )
    icon: Optional[NonEmptyStr] = APIField(
        default=None,
        title="icon name",
        description="any material design icon name"
    )
    title: NonEmptyStr = APIField(
        title="title of the position",
    )
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description, which might change when the position changes. "
                    "preferred language based on the Accept-Language header."
    )


def put_locationtype_first(schema):
    fields = schema.__fields__.copy()
    schema.__fields__ = {"locationtype": fields.pop("locationtype"), **fields}
    return schema


class LocationTypeSchema(Schema):
    locationtype: str


class FullLevelLocationSchema(LevelSchema, LocationTypeSchema):
    """
    A level for the location API.
    See Level schema for details.
    """
    locationtype: Literal["level"]


class FullSpaceLocationSchema(SimpleGeometryPointAndBoundsSchema, SpaceSchema, LocationTypeSchema):
    """
    A space with some additional information for the location API.
    See Space schema for details.
    """
    locationtype: Literal["space"]


class FullAreaLocationSchema(SimpleGeometryPointAndBoundsSchema, AreaSchema, LocationTypeSchema):
    """
    An area with some additional information for the location API.
    See Area schema for details.
    """
    locationtype: Literal["area"]


class FullPOILocationSchema(SimpleGeometryPointSchema, POISchema, LocationTypeSchema):
    """
    A point of interest with some additional information for the location API.
    See POI schema for details.
    """
    locationtype: Literal["poi"]


class FullLocationGroupLocationSchema(SimpleGeometryLocationsSchema, LocationGroupSchema, LocationTypeSchema):
    """
    A location group with some additional information for the location API.
    See LocationGroup schema for details.
    """
    locationtype: Literal["locationgroup"]


class FullDynamicLocationLocationSchema(DynamicLocationSchema, LocationTypeSchema):
    """
    A dynamic location for the location API.
    See DynamicLocation schema for details.
    """
    locationtype: Literal["dynamiclocation"]


class CustomLocationLocationSchema(SimpleGeometryPointAndBoundsSchema, CustomLocationSchema, LocationTypeSchema):
    """
    A custom location for the location API.
    See CustomLocation schema for details.
    """
    locationtype: Literal["customlocation"]


class TrackablePositionLocationSchema(TrackablePositionSchema, LocationTypeSchema):
    """
    A trackable position for the location API.
    See TrackablePosition schema for details.
    """
    locationtype: Literal["position"]


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
    A location group with some rarely needed fields removed and some additional information for the location API.
    See LocationGroup schema for details.
    """
    category: ClassVar[None]
    priority: ClassVar[None]
    hierarchy: ClassVar[None]
    color: ClassVar[None]
    can_report_missing: ClassVar[None]


class SlimDynamicLocationLocationSchema(SlimLocationMixin, FullDynamicLocationLocationSchema):
    """
    A dynamic location with some rarely needed fields removed for the location API.
    See DynamicLocation schema for details.
    """
    pass


FullListableLocationSchema = Annotated[
    Union[
        FullLevelLocationSchema,
        FullSpaceLocationSchema,
        FullAreaLocationSchema,
        FullPOILocationSchema,
        FullLocationGroupLocationSchema,
        FullDynamicLocationLocationSchema,
    ],
    Discriminator("locationtype"),
]

FullLocationSchema = Annotated[
    Union[
        FullListableLocationSchema,
        CustomLocationLocationSchema,
        TrackablePositionLocationSchema,
    ],
    Discriminator("locationtype"),
]

SlimListableLocationSchema = Annotated[
    Union[
        SlimLevelLocationSchema,
        SlimSpaceLocationSchema,
        SlimAreaLocationSchema,
        SlimPOILocationSchema,
        SlimLocationGroupLocationSchema,
        SlimDynamicLocationLocationSchema,
    ],
    Discriminator("locationtype"),
]

SlimLocationSchema = Annotated[
    Union[
        SlimListableLocationSchema,
        CustomLocationLocationSchema,
        TrackablePositionLocationSchema,
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
    id: AnyLocationID = APIField(
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
            Annotated[NonEmptyStr, APIField(title="field title")],
            Annotated[Union[
                Annotated[str, APIField(title="a simple string value")],
                Annotated[DisplayLink, APIField(title="a link value")],
                Annotated[list[DisplayLink], APIField(title="a list of link values")],
                Annotated[None, APIField(title="no value")]
            ], APIField(title="field value", union_mode='left_to_right')]
        ]
    ] = APIField(description="a list of human-readable display values")
    geometry: Optional[GeometrySchema] = APIField(
        None, description="representative geometry, if available"
    )
    editor_url: Optional[NonEmptyStr] = APIField(
        None, description="path to edit this object in the editor, if the user has access to it",
    )


class PositionStatusSchema(Schema):
    id: AnyPositionID = APIField(
        description="the ID of the dynamic position that has been queries",
    )
    slug: NonEmptyStr = APIField(
        description="a description for the dynamic position that has been queried"
    )


class PositionAvailabilitySchema(Schema):
    available: str


class PositionUnavailableStatusSchema(PositionStatusSchema, SimpleGeometryPointAndBoundsSchema,
                                      TrackablePositionSchema, PositionAvailabilitySchema):
    """ position unavailable """
    available: Literal[False]


class PositionAvailableStatusSchema(PositionStatusSchema, SimpleGeometryPointAndBoundsSchema, TrackablePositionSchema,
                                    CustomLocationSchema, PositionAvailabilitySchema):
    """ position available """
    available: Literal[True]


AnyPositionStatusSchema = Annotated[
    Union[
        Annotated[PositionUnavailableStatusSchema, APIField(title="position is unavailable")],
        Annotated[PositionAvailableStatusSchema, APIField(title="position is available")],
    ],
    Discriminator("available"),
]
