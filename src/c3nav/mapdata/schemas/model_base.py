from typing import Annotated, Any, ClassVar, Optional, Union

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt, model_validator
from pydantic.functional_validators import ModelWrapValidatorHandler
from pydantic_core.core_schema import ValidationInfo

from c3nav.api.schema import LineStringSchema, PointSchema, PolygonSchema
from c3nav.api.utils import NonEmptyStr


class SerializableSchema(Schema):
    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        """ overwriting this, we need to call serialize to get the correct data """
        if not isinstance(values, dict):
            values = values.serialize()
        return handler(values)


class DjangoModelSchema(SerializableSchema):
    id: PositiveInt = APIField(
        title="ID",
    )


class LocationSlugSchema(Schema):
    slug: NonEmptyStr = APIField(
        title="location slug",
        description="a slug is a unique way to refer to a location across all location types. "
                    "locations can have a human-readable slug. "
                    "if it doesn't, this field holds a slug generated based from the location type and ID. "
                    "this slug will work even if a human-readable slug is defined later. "
                    "even dynamic locations like coordinates have a slug.",
    )


class WithAccessRestrictionSchema(Schema):
    access_restriction: Optional[PositiveInt] = APIField(
        default=None,
        title="access restriction ID",
    )


class TitledSchema(Schema):
    titles: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="title (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        example={
            "en": "Title",
            "de": "Titel",
        }
    )
    title: NonEmptyStr = APIField(
        title="title (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class LocationSchema(WithAccessRestrictionSchema, TitledSchema, LocationSlugSchema):
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location. "
                    "preferred language based on the Accept-Language header."
    )
    icon: Optional[NonEmptyStr] = APIField(
        default=None,
        title="icon name",
        description="any material design icon name"
    )
    can_search: bool = APIField(
        title="can be searched",
    )
    can_describe: bool = APIField(
        title="can describe locations",
    )
    # todo: add_search


class LabelSettingsSchema(TitledSchema, DjangoModelSchema):
    """
    Settings preset for how and when to display a label. Reusable between objects.
    The title describes the title of this preset, not the displayed label.
    """
    min_zoom: Optional[float] = APIField(
        title="min zoom",
    )
    max_zoom: Optional[float] = APIField(
        title="max zoom",
    )
    font_size: PositiveInt = APIField(
        title="font size",
    )


class SpecificLocationSchema(LocationSchema):
    grid_square: Optional[NonEmptyStr] = APIField(
        default=None,
        title="grid square",
        description="if a grid is defined and this location is within it",
    )
    groups: dict[NonEmptyStr, list[PositiveInt] | Optional[PositiveInt]] = APIField(
        title="location groups",
        description="grouped by location group categories. "
                    "property names are the names of location groupes. "
                    "property values are integer, None or a list of integers, see example."
                    "see location group category endpoint for currently available possibilities."
                    "categories may be missing if no groups apply.",
        example={
            "category_with_single_true": 5,
            "other_category_with_single_true": None,
            "categoryother_category_with_single_false": [1, 3, 7],
        }
    )
    label_settings: Optional[LabelSettingsSchema] = APIField(
        default=None,
        title="label settings",
        description="if not set, it may be taken from location groups"
    )
    label_override: Optional[NonEmptyStr] = APIField(
        default=None,
        title="label override (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class WithPolygonGeometrySchema(Schema):
    geometry: Optional[PolygonSchema] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithLineStringGeometrySchema(Schema):
    geometry: Optional[LineStringSchema] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithPointGeometrySchema(Schema):
    geometry: Optional[PointSchema] = APIField(
        None,
        title="geometry",
        description="can be null if not available or excluded from endpoint",
    )


class WithLevelSchema(SerializableSchema):
    level: PositiveInt = APIField(
        title="level",
        description="level id this object belongs to.",
    )


class WithSpaceSchema(SerializableSchema):
    space: PositiveInt = APIField(
        title="space",
        description="space id this object belongs to.",
    )


class SimpleGeometryBoundsSchema(Schema):
    bounds: tuple[tuple[float, float], tuple[float, float]] = APIField(
        description="location bounding box from (x, y) to (x, y)",
        example=((-10, -20), (20, 30)),
    )


class SimpleGeometryBoundsAndPointSchema(SimpleGeometryBoundsSchema):
    point: tuple[
        Annotated[PositiveInt, APIField(title="level ID")],
        Annotated[float, APIField(title="x coordinate")],
        Annotated[float, APIField(title="y coordinate")]
    ] = APIField(
        title="point representation",
        description="representative point for the location",
        example=(1, 4.2, 13.37)
    )


class SimpleGeometryLocationsSchema(Schema):
    locations: list[PositiveInt] = APIField(  # todo: this should be a set… but json serialization?
        description="IDs of all locations that belong to this grouo",
        example=(1, 2, 3),
    )


LocationID = Union[
    Annotated[int, APIField(title="location ID",
                            description="numeric ID of any lcation")],
    Annotated[str, APIField(title="custom location ID",
                            pattern=r"c:[a-z0-9-_]+:(-?\d+(\.\d+)?):(-?\d+(\.\d+)?)$",
                            description="level short_name and x/y coordinates form the ID of a custom location")],
    Annotated[str, APIField(title="position ID",
                            pattern=r"p:[a-z0-9]+$",
                            description="the ID of a user-defined tracked position is made up of its secret")],
]
