import math
import re
from typing import Annotated, Optional, Union, Literal, ClassVar

from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import BaseSchema, LineStringSchema, PointSchema, PolygonSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.utils.geometry import smart_mapping
from c3nav.mapdata.utils.json import format_geojson


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
    ], APIField(title="(left, bottom)", description="lowest coordinates", example=(-10, -20))],
    Annotated[tuple[
        Annotated[float, APIField(title="right", description="highest X coordindate")],
        Annotated[float, APIField(title="top", description="highest Y coordindate")]
    ], APIField(title="(right, top)", description="highest coordinates", example=(20, 30))]
]


class DjangoModelSchema(BaseSchema):
    id: PositiveInt = APIField(
        title="ID",
        example=1,
    )


class LocationSlugSchema(BaseSchema):
    slug: Optional[NonEmptyStr] = APIField(
        title="location slug",
        description="a slug is a unique way to refer to a location. while locations have a shared ID space, slugs"
                    "are meants to be human-readable and easy to remember.",
        example="entrance",
    )
    effective_slug: NonEmptyStr = APIField(
        title="effective location slug",
        description="if a location doesn't have a slug defined, this field holds a slug generated from the "
                    "location type and ID, which will work even  if a human-readable slug is defined later.\n\n"
                    "even dynamic locations like coordinates have an (auto-generated) slug.",
        example="entrance",
    )


class WithAccessRestrictionSchema(BaseSchema):
    access_restriction: Union[
        Annotated[PositiveInt, APIField(title="access restriction ID")],
        Annotated[None, APIField(title="null", description="no access restriction")],
    ] = APIField(
        default=None,
        title="access restriction ID",
        description="access restriction that this object belongs to",
    )


class TitledSchema(BaseSchema):
    titles: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="title (all languages)",
        description="title in all available languages. property names are the ISO-language code. "
                    "languages may be missing.",
        example={
            "en": "Entrance",
            "de": "Eingang",
        }
    )
    title: NonEmptyStr = APIField(
        title="title (preferred language)",
        description="title in the preferred language based on the Accept-Language header.",
        example="Entrance",
    )


class LocationSchema(WithAccessRestrictionSchema, TitledSchema, LocationSlugSchema):
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location in the "
                    "preferred language based on the Accept-Language header.",
        example="near Area 51",
    )
    icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="set icon name",
        description="as set in the object specifically (any material design icon name)",
        example="pin_drop",
    )
    effective_icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="icon name to use",
        description="effective icon to use (any material design icon name)",
        example="pin_drop",
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
        example="more search terms",
    )

    @classmethod
    def get_overrides(cls, value) -> dict:
        # todo: move into model
        return {
            "locationtype": value._meta.model_name,
        }


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
        example=12,
    )


class EffectiveLabelSettingsSchema(LabelSettingsSchema):
    """
    Settings preset for how and when to display a label.
    """
    id: ClassVar[None]
    title: ClassVar[None]
    titles: ClassVar[None]


class SpecificLocationSchema(LocationSchema):
    grid_square: Union[
        Annotated[NonEmptyStr, APIField(title="grid square", description="grid square(s) that this location is in")],
        Annotated[Literal[""], APIField(title="grid square", description="outside of grid")],
        Annotated[None, APIField(title="null", description="no grid defined or outside of grid")],
    ] = APIField(
        default=None,
        title="grid square",
        description="grid cell(s) that this location is in, if a grid is defined and the location is within it",
        example="C3",
    )
    groups: list[PositiveInt] = APIField(
        title="location groups",
        description="location group(s) that this specific location belongs to.",
        example=[5, 1, 3, 7],
    )
    groups_by_category: dict[
        Annotated[NonEmptyStr, APIField(title="location group category name")],
        Union[
            Annotated[list[PositiveInt], APIField(
                title="array of location IDs",
                description="for categories that have `single` set to `false`. can be an empty array.",
                example=[1, 4, 5],
            )],
            Annotated[PositiveInt, APIField(
                title="one location ID",
                description="for categories that have `single` set to `true`.",
                example=1,
            )],
            Annotated[None, APIField(
                title="null",
                description="for categories that have `single` set to `true`."
            )],
        ]
    ] = APIField(
        title="location groups by category",
        description="location group(s) that this specific location belongs to, grouped by categories.\n\n"
                    "keys are location group category names. see location group category endpoint for details.\n\n"
                    "categories may be missing if no groups apply.",
        example={
            "category_with_single_true": 5,
            "other_category_with_single_true": None,
            "category_with_single_false": [1, 3, 7],
        }
    )
    label_settings: Optional[PositiveInt] = APIField(
        default=None,
        title="label settings",
        description=(
                schema_description(LabelSettingsSchema) +
                "\n\nif not set, label settings of location groups should be used"
        )
    )
    effective_label_settings: Union[
        Annotated[EffectiveLabelSettingsSchema, APIField(
            title="label settings",
            description="label settings to use",
        )],
        Annotated[None, APIField(
            title="null",
            description="don't display a label"
        )],
    ] = APIField(
        default=None,
        title="label settings",
        description=(
            schema_description(LabelSettingsSchema) +
            "\n\neffective label settings to use for this location"
        )
    )
    label_override: Union[
        Annotated[NonEmptyStr, APIField(title="label override", description="text to use for label")],
        Annotated[None, APIField(title="null", description="title will be used")],
    ] = APIField(
        default=None,
        title="label override (preferred language)",
        description="text to use for the label. by default (null), the title would be used."
    )
    load_group_display: Optional[PositiveInt] = APIField(
        default=None,
        title="load group to display",
    )


class WithGeometrySchema(BaseSchema):
    @classmethod
    def get_overrides(cls, value) -> dict:
        # todo: move into model
        value: GeometryMixin
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
            "point": (value.level_id,) + tuple(round(i, 2) for i in value.point.coords[0]),
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
        example=1,
    )


class WithSpaceSchema(BaseSchema):
    space: PositiveInt = APIField(
        title="space",
        description="space id this object belongs to.",
        example=1,
    )


class SimpleGeometryPointSchema(BaseSchema):
    point: tuple[
        Annotated[PositiveInt, APIField(title="level ID")],
        Annotated[float, APIField(title="x coordinate")],
        Annotated[float, APIField(title="y coordinate")]
    ] = APIField(
        title="point representation",
        description="representative point for the location",
        example=(1, 4.2, 13.37)
    )


class SimpleGeometryPointAndBoundsSchema(SimpleGeometryPointSchema):
    bounds: BoundsSchema = APIField(
        description="location bounding box",
        example=((-10, -20), (20, 30)),
    )


class SimpleGeometryLocationsSchema(BaseSchema):
    locations: list[PositiveInt] = APIField(  # todo: this should be a set… but json serialization?
        description="IDs of all locations that belong to this grouo",
        example=(1, 2, 3),
    )


CustomLocationID = Annotated[NonEmptyStr, APIField(
    title="custom location ID",
    pattern=r"c:[a-z0-9-_.]+:(-?\d+(\.\d+)?):(-?\d+(\.\d+)?)$",
    example="c:0:-7.23:12.34",
    description="level short_name and x/y coordinates form the ID of a custom location"
)]
PositionID = Annotated[NonEmptyStr, APIField(
    title="position ID",
    pattern=r"m:[A-Za-z0-9]+$",
    description="the ID of a user-defined tracked position is made up of its secret"
)]
Coordinates3D = tuple[float, float, float]


AnyLocationID = Union[
    Annotated[PositiveInt, APIField(
        title="location ID",
        description="numeric ID of any lcation – all locations have a shared ID space"
    )],
    CustomLocationID,
    PositionID,
]
AnyPositionID = Union[
    Annotated[PositiveInt, APIField(
        title="dynamic location ID",
        description="numeric ID of any dynamic lcation"
    )],
    PositionID,
]
