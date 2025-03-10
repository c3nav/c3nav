from typing import Union, Annotated, Literal, Optional, ClassVar, Protocol

from pydantic import Field as APIField, PositiveInt, NonNegativeInt

from c3nav.api.schema import BaseSchema, GeometryByLevelSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import (schema_description, LabelSettingsSchema,
                                              LocationPoint, BoundsByLevelSchema, TitleField, LocationIdentifier,
                                              DjangoID, PositionIdentifier, CustomLocationIdentifier,
                                              OptionalLocationSlugField)

SubtitleField = Annotated[NonEmptyStr, APIField(
    title="subtitle (preferred language)",
    description="an automatically generated short description for this location in the " \
                "preferred language based on the Accept-Language header.",
    examples=["near Area 51"],
)]
GridSquare = Annotated[
    Union[
        Annotated[NonEmptyStr, APIField(
            title="grid square",
            description="grid square(s) that this location is in"
        )],
        Annotated[Literal[""], APIField(
            title="grid square",
            description="outside of grid"
        )],
        Annotated[None, APIField(
            title="null",
            description="no grid defined or outside of grid"
        )],
    ],
    APIField(
        default=None,
        title="grid square",
        description="grid cell(s) that this location is in, if a grid is defined and the location is within it",
        examples=["C3"],
    )
]


class EffectiveLabelSettingsSchema(LabelSettingsSchema):
    """
    Settings preset for how and when to display a label.
    """
    id: ClassVar[None]
    title: ClassVar[None]
    titles: ClassVar[None]


class NearbySchema(BaseSchema):
    level: Annotated[PositiveInt, APIField(
        description="level ID this custom location is located on",
        examples=[1],
    )]
    space: Annotated[
        Union[
            Annotated[PositiveInt, APIField(title="space ID", examples=[1])],
            Annotated[None, APIField(title="null", description="the location is not inside a space")],
        ],
        APIField(
            default=None,
            description="space ID this custom location is located in"
        )
    ]
    areas: Annotated[list[PositiveInt], APIField(
        description="IDs of areas this custom location is located in"
    )]
    near_area: Annotated[
        Union[
            Annotated[PositiveInt, APIField(title="area ID", examples=[1])],
            Annotated[None, APIField(title="null", description="the location is not near any areas")],
        ],
        APIField(
            title="nearby area",
            description="the ID of an area near this custom location"
        )
    ]
    near_poi: Annotated[
        Union[
            Annotated[PositiveInt, APIField(title="POI ID", examples=[1])],
            Annotated[None, APIField(title="null", description="the location is not near any POIs")],
        ],
        APIField(
            title="nearby POI",
            description="the ID of a POI near this custom location"
        )
    ]
    near_locations: Annotated[list[PositiveInt], APIField(
        description="list of IDs of nearby locations"
    )]
    altitude: Annotated[
        Union[  # todo: merge this into points?
            Annotated[float, APIField(title="ground altitude", examples=[1])],
            Annotated[None, APIField(title="null", description="could not be determined (outside of space?)")],
        ],
        APIField(
            title="ground altitude",
            description="ground altitude (in the map-wide coordinate system)"
        )
    ]


class DynamicLocationState(BaseSchema):
    subtitle: SubtitleField
    grid_square: GridSquare
    dynamic_points: Annotated[list[LocationPoint], APIField(
        title="dynamic points",
        description="representative points of dynamic targets, to be merged with the static points"
    )] = []
    bounds: BoundsByLevelSchema = {}
    nearby: Optional[NearbySchema] = None


class DisplayURL(BaseSchema):
    """
    A URL link for the location display
    """
    title: NonEmptyStr
    url: NonEmptyStr


class DisplayLink(BaseSchema):
    """
    A link for the location display
    """
    id: PositiveInt
    slug: NonEmptyStr
    title: NonEmptyStr
    can_search: bool


class LocationDisplay(BaseSchema):
    id: Annotated[LocationIdentifier, APIField(
        description="a numeric ID for a map location or a string ID for generated locations",
        examples=[1],
    )]
    external_url: Optional[DisplayURL] = None
    display: Annotated[
        list[
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
        ],
        APIField(
            title="display fields",
            description="a list of human-readable display values",
            examples=[[
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
            ]]
        )
    ]
    editor_url: Annotated[
        Union[
            Annotated[NonEmptyStr, APIField(title="path to editor")],
            Annotated[None, APIField(title="null", description="no editor access or object is not editable")],
        ],
        APIField(
            None,
            title="editor URL",
            description="path to edit this object in the editor",
            examples=["/editor/spaces/2/pois/1/"]
        )
    ]


class LocationProtocol(Protocol):
    """
    Any object that implements this protocol can be used as a location anywhere.
    The only exception is the location list API, for which it needs to implement ListableLocationProtocol.

    Current implementations in the c3nav source base are:
    - :py:class:`c3nav.mapdata.models.locations.SpecificLocation`
    - :py:class:`c3nav.mapdata.models.locations.LocationGroup`
    - :py:class:`c3nav.mapdata.models.locations.Position`
    - :py:class:`c3nav.mapdata.utils.locations.CustomLocation`

    See :py:class:`BaseLocationItemSchema` and :py:class:`SingleLocationItemSchema` below.
    """
    locationtype: str
    slug_as_id: bool

    id: PositiveInt | NonEmptyStr
    slug: NonEmptyStr | None
    title: NonEmptyStr
    subtitle: NonEmptyStr
    effective_icon: NonEmptyStr
    grid_square: str | None

    can_search: bool
    can_describe: bool
    dynamic: NonNegativeInt
    points: list[LocationPoint]
    bounds: BoundsByLevelSchema

    nearby: NearbySchema | None
    dynamic_state: DynamicLocationState | None
    locations: []  # todo: rename to sublocations?

    def details_display(self, editor_url: bool) -> LocationDisplay:
        """
        Get human-readable inforation to display about this location.
        """
        pass

    def get_geometry(self, request) -> GeometryByLevelSchema:
        """
        Get geometry associated with this location. This will not include point geometries.
        """
        pass

    def get_geometry_or_points(self, request) -> GeometryByLevelSchema:
        """
        Get geometry associated with this location. This will include points geometries as a fallback.
        """
        pass


class ListedLocationProtocol(LocationProtocol):
    """
    See :py:class:`ListedLocationItemSchema` below for documentation on most attributes.
    """
    id: PositiveInt
    effective_label_settings: EffectiveLabelSettingsSchema | None
    label_override: NonEmptyStr | None
    load_group_display: PositiveInt | None
    add_search: str


class BaseLocationItemSchema(BaseSchema):
    """
    A location is what c3nav can search for and route to and from.
    A location can be a SpecificLocation, a Locationgroup, a CustomLocation or a Position.
    """
    locationtype: Union[
        Literal["specificlocation"],
        Literal["locationgroup"],
        Literal["customlocation"],
        Literal["position"],
    ]
    id: Union[DjangoID, PositionIdentifier, CustomLocationIdentifier]
    slug: OptionalLocationSlugField

    title: TitleField
    subtitle: SubtitleField
    effective_icon: Annotated[Optional[NonEmptyStr], APIField(  # todo: not optional?
        title="icon name to use",
        description="effective icon to use (any material design icon name)",
        examples=["pin_drop"],
    )]
    grid_square: GridSquare
    can_search: Annotated[bool, APIField(
        title="can be searched",
        description="if `true`, this object can show up in search results",
    )]
    can_describe: Annotated[bool, APIField(
        title="can describe locations",
        description="if `true`, this object can be used to describe other locations (e.g. in their subtitle)",
    )]
    dynamic: Annotated[
        NonNegativeInt,
        APIField(
            title="dynamic targets",
            description="how many dynamic targets (for example positions that can move in real time) "
                        "are included in this location"
        )
    ] = 0
    points: list[LocationPoint] = []
    bounds: BoundsByLevelSchema = {}

    @classmethod
    def get_overrides(cls, value: LocationProtocol) -> dict:
        return {
            "id": value.slug if value.slug_as_id else value.id
        }


class SingleLocationItemSchema(BaseLocationItemSchema):
    nearby: Annotated[Optional[NearbySchema], APIField(
        title="nearby locations",
        description="for custom locations, information that is used to describe its position"
    )] = None
    dynamic_state: Annotated[Optional[DynamicLocationState], APIField(
        title="dynamic state",
        description="if this location features dynamic targets, this object contains dynamic replacement values "
                    "to override location properties with, unless specified otherwise"
    )] = []
    # todo: get dynamic states of children


class ListedLocationItemSchema(BaseLocationItemSchema):
    locationtype: Union[
        Literal["specificlocation"],
        Literal["locationgroup"],
    ]
    id: DjangoID
    effective_label_settings: Annotated[
        Union[
            Annotated[EffectiveLabelSettingsSchema, APIField(
                title="label settings",
                description="label settings to use",
            )],
            Annotated[None, APIField(
                title="null",
                description="don't display a label"
            )],
        ],
        APIField(
            default=None,
            title="label settings",
            description=(
                    schema_description(LabelSettingsSchema) +
                    "\n\neffective label settings to use for this location"
            )
        )
    ]
    label_override: Annotated[
        Union[
            Annotated[NonEmptyStr, APIField(title="label override", description="text to use for label")],
            Annotated[None, APIField(title="null", description="title will be used")],
        ],
        APIField(
            default=None,
            title="label override (preferred language)",
            description="text to use for the label. by default (null), the title would be used."
        )
    ]
    load_group_display: Annotated[Optional[PositiveInt], APIField(
        default=None,
        title="load group to display",
    )]

    locations: Annotated[
        list[PositiveInt],
        APIField(  # todo: this should be a set… but json serialization?
            description="IDs of all locations that belong to this grouo",
            examples=[(1, 2, 3)],
        )
    ] = []
    add_search: Annotated[str, APIField(
        title="additional search terms",
        description="more data for the search index separated by spaces",
        examples=["more search terms"],
    )]
    nearby: ClassVar[None]
