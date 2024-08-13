from typing import Annotated, ClassVar, Literal, Optional, Union

from pydantic import Discriminator
from pydantic import Field as APIField
from pydantic import NonNegativeFloat, PositiveFloat, PositiveInt

from c3nav.api.schema import BaseSchema, GeometrySchema, PointSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models import LocationGroup
from c3nav.mapdata.schemas.model_base import (AnyLocationID, AnyPositionID, CustomLocationID, DjangoModelSchema,
                                              LabelSettingsSchema, LocationSchema, PositionID,
                                              SimpleGeometryLocationsSchema, SimpleGeometryPointAndBoundsSchema,
                                              SimpleGeometryPointSchema, SpecificLocationSchema, TitledSchema,
                                              WithAccessRestrictionSchema, WithLevelSchema,
                                              WithLineStringGeometrySchema, WithPointGeometrySchema,
                                              WithPolygonGeometrySchema, WithSpaceSchema, schema_definitions,
                                              schema_description)


class LevelSchema(SpecificLocationSchema, DjangoModelSchema):
    """
    A physical level of the map, containing building, spaces, doors…

    A level is a specific location, and can therefore be routed to and from, as well as belong to location groups.
    """
    short_label: NonEmptyStr = APIField(
        title="short label (for level selector)",
        description="unique among levels",
    )
    on_top_of: Union[
        Annotated[PositiveInt, APIField(title="level ID", description="level this level is on top of", example=1)],
        Annotated[None, APIField(title="null", description="this is a main level, not on top of any other")]
    ] = APIField(
        title="on top of level ID",
        description="if set, this is not a main level, but it's on top of this other level"
    )
    base_altitude: float = APIField(
        title="base/default altitude",
        description="default ground altitude for this level, if it can't be determined using altitude markers.",
    )
    default_height: PositiveFloat = APIField(
        title="default ceiling height",
        description="default ceiling height for all spaces that don't set their own",
        example=2.5
    )
    door_height: PositiveFloat = APIField(
        title="door height",
        description="height for all doors on this level",
        example="2.0",
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
        description="how much walking in this area is slowed down, overlapping areas are multiplied",
        example=1.0,
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
    label_settings: Union[
        Annotated[LabelSettingsSchema, APIField(
            title="label settings",
            description="label settings to use for gruop members that don't have their own set",
        )],
        Annotated[None, APIField(
            title="null",
            description="no label settings set"
        )],
    ] = APIField(
        default=None,
        title="label settings",
        description=(
                schema_description(LabelSettingsSchema) +
                "\n\nlocations can override this setting"
        )
    )
    can_report_missing: LocationGroup.CanReportMissing = APIField(
        title="report missing locations",
        description="whether this location group can be used to report missing locations",
    )
    color: Union[
        Annotated[NonEmptyStr, APIField(title="color", description="a valid CSS color expression")],
        Annotated[None, APIField(title="null", description="default/no color will be used")],
    ] = APIField(
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
    Represents a moving object. Its position has to be separately queried through the position API.

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


class CustomLocationSchema(BaseSchema):
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
    icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="icon name",
        description="any material design icon name",
        example="pin_drop",
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
        description="level ID this custom location is located on",
        example=1,
    )
    space: Union[
        Annotated[PositiveInt, APIField(title="space ID", example=1)],
        Annotated[None, APIField(title="null", description="the location is not inside a space")],
    ] = APIField(
        default=None,
        description="space ID this custom location is located in"
    )
    areas: list[PositiveInt] = APIField(
        description="IDs of areas this custom location is located in"
    )
    grid_square: Union[
        Annotated[NonEmptyStr, APIField(title="grid square", description="grid square(s) that this location is in")],
        Annotated[None, APIField(title="null", description="no grid defined or outside of grid")],
    ] = APIField(
        default=None,
        title="grid square",
        description="grid cell(s) that this location is in, if a grid is defined and the location is within it",
        example="C3",
    )
    near_area: Union[
        Annotated[PositiveInt, APIField(title="area ID", example=1)],
        Annotated[None, APIField(title="null", description="the location is not near any areas")],
    ] = APIField(
        near="nearby area",
        description="the ID of an area near this custom location"
    )
    near_poi: Union[
        Annotated[PositiveInt, APIField(title="POI ID", example=1)],
        Annotated[None, APIField(title="null", description="the location is not near any POIs")],
    ] = APIField(
        title="nearby POI",
        description="the ID of a POI near this custom location"
    )
    nearby: list[PositiveInt] = APIField(
        description="list of IDs of nearby locations"
    )
    altitude: Union[
        Annotated[float, APIField(title="ground altitude", example=1)],
        Annotated[None, APIField(title="null", description="could not be determined (outside of space?)")],
    ] = APIField(
        title="ground altitude",
        description="ground altitude (in the map-wide coordinate system)"
    )
    geometry: Union[
        PointSchema,
        Annotated[None, APIField(title="null", description="geometry excluded from endpoint")]
    ] = APIField(
        None,
        description="point geometry for this custom location",
    )


class TrackablePositionSchema(BaseSchema):
    """
    A trackable position. Its position can be set or reset.
    """
    id: PositionID = APIField(
        description="ID representing the position",
        example="p:adskjfalskdj",
    )
    slug: PositionID = APIField(
        description="slug representing the position",
        example="p:adskjfalskdj",
    )
    icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="icon name",
        description="any material design icon name",
        example="pin_drop",
    )
    title: NonEmptyStr = APIField(
        title="title of the position",
        example="My position"
    )
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description, which might change when the position changes. "
                    "preferred language based on the Accept-Language header.",
        example="Near Bällebad"
    )


class LocationTypeSchema(BaseSchema):
    locationtype: str = APIField(title="location type",
                                 description="indicates what kind of location is included. "
                                             "different location types have different fields.")


def LocationTypeAPIField():
    return APIField(title="location type",
                    description="indicates what kind of location is included. "
                                "different location types have different fields.")


class FullLevelLocationSchema(LevelSchema, LocationTypeSchema):
    """
    A level for the location API.
    See Level schema for details.
    """
    locationtype: Literal["level"] = LocationTypeAPIField()


class FullSpaceLocationSchema(SimpleGeometryPointAndBoundsSchema, SpaceSchema, LocationTypeSchema):
    """
    A space with some additional information for the location API.
    See Space schema for details.
    """
    locationtype: Literal["space"] = LocationTypeAPIField()


class FullAreaLocationSchema(SimpleGeometryPointAndBoundsSchema, AreaSchema, LocationTypeSchema):
    """
    An area with some additional information for the location API.
    See Area schema for details.
    """
    locationtype: Literal["area"] = LocationTypeAPIField()


class FullPOILocationSchema(SimpleGeometryPointSchema, POISchema, LocationTypeSchema):
    """
    A point of interest with some additional information for the location API.
    See POI schema for details.
    """
    locationtype: Literal["poi"] = LocationTypeAPIField()


class FullLocationGroupLocationSchema(SimpleGeometryLocationsSchema, LocationGroupSchema, LocationTypeSchema):
    """
    A location group with some additional information for the location API.
    See LocationGroup schema for details.
    """
    locationtype: Literal["locationgroup"] = LocationTypeAPIField()


class FullDynamicLocationLocationSchema(DynamicLocationSchema, LocationTypeSchema):
    """
    A dynamic location for the location API.
    See DynamicLocation schema for details.
    """
    locationtype: Literal["dynamiclocation"] = LocationTypeAPIField()


class CustomLocationLocationSchema(SimpleGeometryPointAndBoundsSchema, CustomLocationSchema, LocationTypeSchema):
    """
    A custom location for the location API.
    See CustomLocation schema for details.
    """
    locationtype: Literal["customlocation"] = LocationTypeAPIField()


class TrackablePositionLocationSchema(TrackablePositionSchema, LocationTypeSchema):
    """
    A trackable position for the location API.
    See TrackablePosition schema for details.
    """
    locationtype: Literal["position"] = LocationTypeAPIField()


class SlimLocationMixin(BaseSchema):
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


listable_location_definitions = schema_definitions(
    (LevelSchema, SpaceSchema, AreaSchema, POISchema, DynamicLocationSchema, LocationGroupSchema)
)
all_location_definitions = listable_location_definitions + "\n" + schema_definitions(
    (CustomLocationSchema, TrackablePositionSchema)
)


class DisplayLink(BaseSchema):
    """
    A link for the location display
    """
    id: PositiveInt
    slug: NonEmptyStr
    title: NonEmptyStr
    can_search: bool


class DisplayURL(BaseSchema):
    """
    A URL link for the location display
    """
    title: NonEmptyStr
    url: NonEmptyStr


class LocationDisplay(BaseSchema):
    id: AnyLocationID = APIField(
        description="a numeric ID for a map location or a string ID for generated locations",
        example=1,
    )

    level: Union[
        Annotated[PositiveInt, APIField(title="level ID", description="ID of relevant level")],
        Annotated[None, APIField(title="null", description="no relevant level")],
    ] = APIField(
        None,
        title="level",
        example=2,
    )
    space: Union[
        Annotated[PositiveInt, APIField(title="level ID", description="ID of relevant level")],
        Annotated[None, APIField(title="null", description="no relevant level")],
    ] = APIField(
        None,
        description="space",
        example=3,
    )
    display: list[
        tuple[
            Annotated[NonEmptyStr, APIField(title="field title")],
            Annotated[Union[
                Annotated[str, APIField(title="a simple string value")],
                Annotated[DisplayLink, APIField(title="a link value")],
                Annotated[list[DisplayLink], APIField(title="a list of link values")],
                Annotated[DisplayURL, APIField(title="an URL value")],
                Annotated[None, APIField(title="no value")]
            ], APIField(title="field value", union_mode='left_to_right')]
        ]
    ] = APIField(
        title="display fields",
        description="a list of human-readable display values",
        example=[
            ("Title", "Awesome location"),
            ("Access Restriction", None),
            ("Level", {
                "id": 2,
                "slug": "level0",
                "title": "Ground Floor",
                "can_search": True,
            }),
            ("Groups", [
                {
                    "id": 10,
                    "slug": "entrances",
                    "title": "Entrances",
                    "can_search": True,
                },
                {
                    "id": 11,
                    "slug": "startswithe",
                    "title": "Locations that Start with E",
                    "can_search": False,
                }
            ]),
            ("External URL", {
                "title": "Open",
                "url": "https://example.com/",
            })
        ]
    )
    geometry: Union[
        GeometrySchema,
        Annotated[None, APIField(title="null", description="no geometry available")]
    ] = APIField(
        None, description="representative geometry, if available"
    )
    editor_url: Union[
        Annotated[NonEmptyStr, APIField(title="path to editor")],
        Annotated[None, APIField(title="null", description="no editor access or object is not editable")],
    ] = APIField(
        None,
        title="editor URL",
        description="path to edit this object in the editor",
        example="/editor/spaces/2/pois/1/"
    )


class PositionStatusSchema(BaseSchema):
    id: AnyPositionID = APIField(
        description="the ID of the dynamic position that has been queries",
    )
    slug: NonEmptyStr = APIField(
        description="a description for the dynamic position that has been queried"
    )


class PositionAvailabilitySchema(BaseSchema):
    available: str


class PositionUnavailableStatusSchema(PositionStatusSchema, TrackablePositionSchema, PositionAvailabilitySchema):
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


class ProjectionPipelineSchema(BaseSchema):
    pipeline: Union[
        Annotated[NonEmptyStr, APIField(title='proj4 string')],
        Annotated[None, APIField(title='null', description='projection not available')]
    ] = APIField(
        title='proj4 string',
        description='proj4 string for converting WGS84 coordinates to c3nav coordinates if available',
        example='+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs'
    )

class ProjectionSchema(ProjectionPipelineSchema):
    proj4: NonEmptyStr = APIField(
        title='proj4 string',
        description='proj4 string for converting WGS84 coordinates to c3nav coordinates without offset and rotation',
        example='+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs'
    )
    zero_point: tuple[float, float] = APIField(
        title='zero point',
        description='coordinates of the zero point of the c3nav coordinate system',
        example=(0.0, 0.0),
    )
    rotation: float = APIField(
        title='rotation',
        description='rotational offset of the c3nav coordinate system',
        example=0.0,
    )
    rotation_matrix: Optional[tuple[
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
    ]] = APIField(
        title='rotation matrix',
        description='rotation matrix for rotational offset of the c3nav coordinate system',
        example=[
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        ]
    )
