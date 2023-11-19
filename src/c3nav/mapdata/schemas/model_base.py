from typing import Any, Optional

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt, model_validator
from pydantic.functional_validators import ModelWrapValidatorHandler
from pydantic_core.core_schema import ValidationInfo

from c3nav.api.schema import LineStringSchema, PointSchema, PolygonSchema
from c3nav.api.utils import NonEmptyStr


class DjangoModelSchema(Schema):
    id: PositiveInt = APIField(
        title="ID",
    )


class SerializableSchema(Schema):
    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        """ overwriting this, we need to call serialize to get the correct data """
        values = values.serialize()
        return handler(values)


class LocationSlugSchema(Schema):
    slug: NonEmptyStr = APIField(
        title="location slug",
        description="a slug is a unique way to refer to a location across all location types. "
                    "locations can have a human-readable slug. "
                    "if it doesn't, this field holds a slug generated based from the location type and ID. "
                    "this slug will work even if a human-readable slug is defined later. "
                    "even dynamic locations like coordinates have a slug.",
    )


class AccessRestrictionSchema(Schema):
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


class LocationSchema(AccessRestrictionSchema, TitledSchema, LocationSlugSchema, SerializableSchema):
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
    min_zoom: float = APIField(
        title="min zoom",
    )
    max_zoom: float = APIField(
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
    geometry: PolygonSchema = APIField(
        title="geometry",
    )


class WithLineStringGeometrySchema(Schema):
    geometry: LineStringSchema = APIField(
        title="geometry",
    )


class WithPointGeometrySchema(Schema):
    geometry: PointSchema = APIField(
        title="geometry",
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
