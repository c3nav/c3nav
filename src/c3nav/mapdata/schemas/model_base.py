import math
import re
from typing import Annotated, Optional, Union, TYPE_CHECKING, TypeAlias

from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import BaseSchema, LineStringSchema, PointSchema, PolygonSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.utils.geometry import smart_mapping
from c3nav.mapdata.utils.json import format_geojson

if TYPE_CHECKING:
    from c3nav.mapdata.models.geometry.base import GeometryMixin


def schema_description(schema):
    return schema.__doc__.replace("\n    ", "\n").strip()


def schema_definition(schema):
    return ("- **"+re.sub(r"([a-z])([A-Z])", r"\1 \2", schema.__name__.removesuffix("Schema")) + "**: " +
            schema_description(schema).split("\n")[0].strip())


def schema_definitions(schemas):
    return "\n".join(schema_definition(schema) for schema in schemas)


BoundsSchema = tuple[
    Annotated[tuple[
        Annotated[float, APIField(title="left", description="lowest X coordindate")],
        Annotated[float, APIField(title="bottom", description="lowest Y coordindate")]
    ], APIField(title="(left, bottom)", description="lowest coordinates", examples=[(-10, -20)])],
    Annotated[tuple[
        Annotated[float, APIField(title="right", description="highest X coordindate")],
        Annotated[float, APIField(title="top", description="highest Y coordindate")]
    ], APIField(title="(right, top)", description="highest coordinates", examples=[(20, 30)])]
]


BoundsByLevelSchema = Annotated[
    dict[int, BoundsSchema],
    APIField(
        title="bounds by level",
        description="object containing bounds for every level, identified by its ID"
    )
]
DjangoID = Annotated[
    PositiveInt,
    APIField(
        title="ID",
        examples=[1],
    )
]


class DjangoModelSchema(BaseSchema):
    id: DjangoID


OptionalLocationSlugField = Annotated[
    Optional[NonEmptyStr],
    APIField(
        title="location slug",
        description="a slug is a unique way to refer to a location. while locations have a shared ID space, slugs"
                    "are meants to be human-readable and easy to remember. "
                    "If no slug is defined, you can use the ID as a string.",
        examples=["entrance"],
    )
]


class LocationSlugSchema(BaseSchema):
    slug: OptionalLocationSlugField


AccessRestrictionField = Annotated[
    Union[
        Annotated[PositiveInt, APIField(title="access restriction ID")],
        Annotated[None, APIField(title="null", description="no access restriction")],
    ],
    APIField(
        default=None,
        title="access restriction ID",
        description="access restriction that this object belongs to",
    )
]


class WithAccessRestrictionSchema(BaseSchema):
    access_restriction: AccessRestrictionField


TitlesField = Annotated[
    dict[NonEmptyStr, NonEmptyStr],
    APIField(
        title="title (all languages)",
        description="title in all available languages. property names are the ISO-language code. "
                    "languages may be missing.",
        examples=[
            {"en": "Entrance", "de": "Eingang"}
        ]
    )
]
TitleField = Annotated[
    NonEmptyStr,
    APIField(
        title="title (preferred language)",
        description="title in the preferred language based on the Accept-Language header.",
        examples=["Entrance"],
    )
]


class TitledSchema(BaseSchema):
    titles: TitlesField
    title: TitleField


class BaseLocationSchema(WithAccessRestrictionSchema, TitledSchema, LocationSlugSchema):
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location in the "
                    "preferred language based on the Accept-Language header.",
        examples=["near Area 51"],
    )
    icon: Optional[NonEmptyStr] = APIField(
        title="set icon name",
        description="as set in the object specifically (any material design icon name)",
        examples=["pin_drop"],
    )
    effective_icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="icon name to use",
        description="effective icon to use (any material design icon name)",
        examples=["pin_drop"],
    )
    can_search: bool = APIField(
        title="can be searched",
        description="if `true`, this object can show up in search results",
    )
    can_describe: bool = APIField(
        title="can describe locations",
        description="if `true`, this object can be used to describe other locations (e.g. in their subtitle)",
    )
    add_search: str = APIField(
        title="additional search terms",
        description="more data for the search index separated by spaces",
        examples=["more search terms"],
    )


class LabelSettingsSchema(TitledSchema, DjangoModelSchema):  # todo: add titles back in here
    """
    Settings preset for how and when to display a label. Reusable between objects.
    The title describes the title of this preset, not the displayed label.
    """
    min_zoom: float = APIField(
        -10,
        title="min zoom",
        description="minimum zoom to display the label at",
    )
    max_zoom: float = APIField(
        10,
        title="max zoom",
        description="maximum, zoom to display the label at",
    )
    font_size: PositiveInt = APIField(
        title="font size",
        description="font size of the label",
        examples=[12],
    )


LocationPoint: TypeAlias = Annotated[
    tuple[
        Annotated[PositiveInt, APIField(title="level ID")],
        Annotated[float, APIField(title="x coordinate")],
        Annotated[float, APIField(title="y coordinate")]
    ],
    APIField(
        title="point representation",
        description="representative point for the location",
        examples=[(1, 4.2, 13.37)]
    )
]
DjangoCompatibleLocationPoint: TypeAlias = tuple[int, float, float]


class WithGeometrySchema(BaseSchema):
    @classmethod
    def get_overrides(cls, value) -> dict:
        # todo: move into model
        value: "GeometryMixin"
        if "geometry" in value.get_deferred_fields() or value.geometry is None:
            return {
                **super().get_overrides(value),
                "geometry": None,
                "point": None,
                "bounds": None,
            }
        minx, miny, maxx, maxy = value.geometry.bounds
        return {
            **super().get_overrides(value),
            "geometry": (
                format_geojson(smart_mapping(value.geometry), rounded=False)
                if not getattr(value, '_hide_geometry', False) else None
            ),
            "bounds": ((int(math.floor(minx)), int(math.floor(miny))),
                       (int(math.ceil(maxx)), int(math.ceil(maxy))))
        }


class WithPolygonGeometrySchema(WithGeometrySchema):
    geometry: Union[
        PolygonSchema,
        Annotated[None, APIField(title="null", description="geometry not available of excluded from endpoint")]
    ] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithLineStringGeometrySchema(WithGeometrySchema):
    geometry: Union[
        LineStringSchema,
        Annotated[None, APIField(title="null", description="geometry not available of excluded from endpoint")]
    ] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithPointGeometrySchema(WithGeometrySchema):
    geometry: Union[
        PointSchema,
        Annotated[None, APIField(title="null", description="geometry not available of excluded from endpoint")]
    ] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithLevelSchema(BaseSchema):
    level: PositiveInt = APIField(
        title="level",
        description="level id this object belongs to.",
        examples=[1],
    )


class WithSpaceSchema(BaseSchema):
    space: PositiveInt = APIField(
        title="space",
        description="space id this object belongs to.",
        examples=[1],
    )


LocationSlugStr = Annotated[NonEmptyStr, APIField(
    title="location slug",
    pattern=r"^[a-z0-9-]*[a-z]+[a-z0-9-]*$",
    description="a slug refering to a location"
)]
CustomLocationIdentifier = Annotated[NonEmptyStr, APIField(
    title="custom location ID",
    pattern=r"^c:[a-z0-9-_.]+:(-?\d+(\.\d+)?):(-?\d+(\.\d+)?)$",
    examples=["c:0:-7.23:12.34"],
    description="level identifier and x/y coordinates form the ID of a custom location"
)]
PositionIdentifier = Annotated[NonEmptyStr, APIField(
    title="position identifier",
    pattern=r"^m:[A-Za-z0-9]+$",
    description="the ID of a user-defined tracked position is made up of its secret"
)]
Coordinates3D = tuple[float, float, float]

LocationIdentifier = Union[
    Annotated[PositiveInt, APIField(
        title="location ID",
        description="numeric ID of any lcation – all locations have a shared ID space"
    )],
    LocationSlugStr,
    CustomLocationIdentifier,
    PositionIdentifier,
]
