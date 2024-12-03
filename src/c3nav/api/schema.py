from contextlib import suppress
from dataclasses import dataclass
from types import NoneType
from typing import Annotated, Any, Literal, Union, ClassVar

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model, ManyToManyField
from django.utils.functional import Promise
from ninja import Schema
from pydantic import Discriminator
from pydantic import Field as APIField
from pydantic import model_validator
from pydantic.functional_validators import ModelWrapValidatorHandler
from pydantic_core.core_schema import ValidationInfo

from c3nav.api.utils import NonEmptyStr


def make_serializable(values: Any):
    if isinstance(values, Schema):
        return values
    if isinstance(values, (str, bool, int, float, complex, NoneType)):
        return values
    if isinstance(values, dict):
        return {
            key: make_serializable(val)
            for key, val in values.items()
        }
    if isinstance(values, (list, tuple, set, frozenset)):
        if values and isinstance(next(iter(values)), Model):
            return type(values)(val.pk for val in values)
        return type(values)(make_serializable(val) for val in values)
    if isinstance(values, Promise):
        return str(values)
    return values


@dataclass
class ModelDataForwarder:
    obj: Model
    overrides: dict

    def __getattr__(self, key):
        # noinspection PyUnusedLocal
        with suppress(KeyError):
            return make_serializable(self.overrides[key])
        with suppress(FieldDoesNotExist):
            field = self.obj._meta.get_field(key)
            if field.is_relation:
                if field.many_to_many:
                    return [obj.pk for obj in getattr(self.obj, key).all()]
                return make_serializable(getattr(self.obj, field.attname))
        return make_serializable(getattr(self.obj, key))


class BaseSchema(Schema):
    orig_keys: ClassVar[frozenset[str]] = frozenset()

    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        """ overwriting this, we need to call serialize to get the correct data """
        if hasattr(values, 'serialize') and callable(values.serialize) and not getattr(values, 'new_serialize', False):
            converted = make_serializable(values.serialize())
        elif isinstance(values, Model):
            converted = ModelDataForwarder(
                obj=values,
                overrides=cls.get_overrides(values),
            )
        else:
            converted = make_serializable(values)
        return handler(converted)

    @classmethod
    def get_overrides(cls, value: Model) -> dict:
        return {}


class APIErrorSchema(BaseSchema):
    """
    An error has occured with this request
    """
    detail: NonEmptyStr = APIField(
        description="A human-readable error description"
    )


class PolygonSchema(BaseSchema):
    """
    A GeoJSON Polygon
    """
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = APIField(
        example=[[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]]
    )

    class Config(Schema.Config):
        title = "GeoJSON Polygon"


class MultiPolygonSchema(BaseSchema):
    """
    A GeoJSON MultiPolygon
    """
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[tuple[float, float]]]] = APIField(
        example=[[[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]]]
    )

    class Config(Schema.Config):
        title = "GeoJSON Polygon"


class LineStringSchema(BaseSchema):
    """
    A GeoJSON LineString
    """
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [2.5, 2.5], [5, 8.7]]
    )

    class Config(Schema.Config):
        title = "GeoJSON LineString"


class LineSchema(BaseSchema):
    """
    A GeoJSON LineString with only two points
    """
    type: Literal["LineString"]
    coordinates: tuple[tuple[float, float], tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [5, 8.7]]
    )

    class Config(Schema.Config):
        title = "GeoJSON LineString (only two points)"


class PointSchema(BaseSchema):
    """
    A GeoJSON Point
    """
    type: Literal["Point"]
    coordinates: tuple[float, float] = APIField(
        example=[1, 2.5]
    )

    class Config(Schema.Config):
        title = "GeoJSON Point"


GeometrySchema = Annotated[
    Union[
        PolygonSchema,
        LineStringSchema,
        PointSchema,
        MultiPolygonSchema,
    ],
    Discriminator("type"),
]


class AnyGeometrySchema(BaseSchema):
    """
    A GeoJSON Geometry
    """
    type: NonEmptyStr
    coordinates: Any


class StatsSchema(BaseSchema):
    users_total: int
    reports_total: int
    reports_today: int
    reports_open: int