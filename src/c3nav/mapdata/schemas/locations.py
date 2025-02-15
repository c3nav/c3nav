from typing import Union, Annotated, Literal, Optional, ClassVar

from pydantic import Field as APIField, PositiveInt, NonNegativeInt

from c3nav.api.schema import BaseSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.schemas.model_base import schema_description, LabelSettingsSchema, \
    LocationPoint, BoundsByLevelSchema, LocationSlugSchema, TitleField, AnyLocationID, \
    DjangoID, PositionID, CustomLocationID, OptionalLocationSlugField


class NearbySchema(BaseSchema):
    level: Annotated[PositiveInt, APIField(
        description="level ID this custom location is located on",
        examples=[1],
    )]
    space: Annotated[
        Union[
            Annotated[PositiveInt, APIField(title="space ID", example=1)],
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
    grid_square: Annotated[
        Union[
            Annotated[NonEmptyStr, APIField(title="grid square", description="grid square(s) that this location is in")],
            Annotated[Literal[""], APIField(title="grid square", description="outside of grid")],
            Annotated[None, APIField(title="null", description="no grid defined or outside of grid")],
        ],
        APIField(
            default=None,
            title="grid square",
            description="grid cell(s) that this location is in, if a grid is defined and the location is within it",
            examples=["C3"],
        )
    ]
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
            Annotated[PositiveInt, APIField(title="POI ID", example=1)],
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
        Union[    # todo: merge this into points?
            Annotated[float, APIField(title="ground altitude", example=1)],
            Annotated[None, APIField(title="null", description="could not be determined (outside of space?)")],
        ],
        APIField(
            title="ground altitude",
            description="ground altitude (in the map-wide coordinate system)"
        )
    ]


class BaseLocationItemSchema(BaseSchema):
    locationtype: Union[
        Literal["specificlocation"],
        Literal["locationgroup"],
        Literal["customlocation"],
        Literal["position"],
    ]
    id: Union[DjangoID, PositionID, CustomLocationID]
    slug: OptionalLocationSlugField

    title: TitleField
    subtitle: Annotated[NonEmptyStr, APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location in the "
                    "preferred language based on the Accept-Language header.",
        examples=["near Area 51"],
    )]
    effective_icon: Annotated[Optional[NonEmptyStr], APIField(  # todo: not optional?
        title="icon name to use",
        description="effective icon to use (any material design icon name)",
        examples=["pin_drop"],
    )]
    grid_square: Annotated[
        Union[
            Annotated[NonEmptyStr, APIField(title="grid square", description="grid square(s) that this location is in")],
            Annotated[Literal[""], APIField(title="grid square", description="outside of grid")],
            Annotated[None, APIField(title="null", description="no grid defined or outside of grid")],
        ],
        APIField(
            default=None,
            title="grid square",
            description="grid cell(s) that this location is in, if a grid is defined and the location is within it",
            examples=["C3"],
        )
    ]
    can_search: Annotated[bool, APIField(
        title="can be searched",
        description="if `true`, this object can show up in search results",
    )]
    can_describe: Annotated[bool, APIField(
        title="can describe locations",
        description="if `true`, this object can be used to describe other locations (e.g. in their subtitle)",
    )]
    moving: Annotated[
        NonNegativeInt,
        APIField(
            title="moving positions",
            description="how many moving positions are included in this location"
        )
    ]= 0
    points: list[LocationPoint] = []
    bounds: BoundsByLevelSchema = {}


class EffectiveLabelSettingsSchema(LabelSettingsSchema):
    """
    Settings preset for how and when to display a label.
    """
    id: ClassVar[None]
    title: ClassVar[None]
    titles: ClassVar[None]


class SingleLocationItemSchema(BaseLocationItemSchema):
    nearby: Optional[NearbySchema]
    moving_points: list[LocationPoint]


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
    id: Annotated[AnyLocationID, APIField(
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