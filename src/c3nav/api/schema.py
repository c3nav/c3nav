from contextlib import suppress
from dataclasses import dataclass, is_dataclass
from types import NoneType
from typing import Annotated, Any, Literal, Union, ClassVar, TypeAlias, Iterable

from django.core.exceptions import FieldDoesNotExist
from django.db.models import Model
from django.utils.functional import Promise
from ninja import Schema
from pydantic import Discriminator, ConfigDict
from pydantic import Field as APIField
from pydantic import model_validator
from pydantic.functional_validators import ModelWrapValidatorHandler
from pydantic_core.core_schema import ValidationInfo

from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.utils.geometry import smart_mapping


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
        # This is needed for lazy attributes that evaluate to `None` to be serialized properly.
        # Without this `None` is returned as the string 'None'.
        # It can't be `is None` as the left side is a Proxy and not actually `None`.
        # Needed by at least the I18nField
        if values == None:
            return None
        return str(values)
    return values


@dataclass
class DataclassForwarder:
    obj: Any
    overrides: dict

    def __getattr__(self, key):
        # noinspection PyUnusedLocal
        with suppress(KeyError):
            return make_serializable(self.overrides[key])
        return make_serializable(getattr(self.obj, key))


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
            if key != "effective_label_settings" and field.is_relation:  # todo: ugly hack, lets remove this exception
                if field.many_to_many:
                    return [obj.pk for obj in getattr(self.obj, key).all()]
                return make_serializable(getattr(self.obj, field.attname))
        return make_serializable(getattr(self.obj, key))

    def __repr__(self):
        return f"F<{repr(self.obj)}>"


class BaseSchema(Schema):
    orig_keys: ClassVar[frozenset[str]] = frozenset()  # todo… what is this used for? remove?

    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        """ overwriting this, we need to call serialize to get the correct data """
        if hasattr(values, 'serialize') and callable(values.serialize):
            converted = make_serializable(values.serialize())
        elif isinstance(values, Model):
            converted = ModelDataForwarder(
                obj=values,
                overrides=cls.get_overrides(values),
            )
        elif is_dataclass(values):
            converted = DataclassForwarder(
                obj=values,
                overrides=cls.get_overrides(values),
            )
        else:
            converted = make_serializable(values)
        return handler(converted)

    @classmethod
    def get_overrides(cls, value) -> dict:
        return {}


class APIErrorSchema(BaseSchema):
    """
    An error has occured with this request
    """
    detail: NonEmptyStr = APIField(
        description="A human-readable error description"
    )


class BaseGeometrySchema(BaseSchema):
    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        if isinstance(values, dict):
            return values
        if isinstance(values, Iterable):
            return handler([value if isinstance(value, dict) else smart_mapping(value) for value in values])
        return smart_mapping(values)


class PolygonSchema(BaseGeometrySchema):
    """
    A GeoJSON Polygon
    """
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = APIField(
        example=[[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]]
    )

    model_config = ConfigDict(title="GeoJSON Polygon")


class MultiPolygonSchema(BaseGeometrySchema):
    """
    A GeoJSON MultiPolygon
    """
    type: Literal["MultiPolygon"]
    coordinates: list[list[list[tuple[float, float]]]] = APIField(
        example=[[[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]]]
    )

    model_config = ConfigDict(title="GeoJSON Multipolygon")


class LineStringSchema(BaseGeometrySchema):
    """
    A GeoJSON LineString
    """
    type: Literal["LineString"]
    coordinates: list[tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [2.5, 2.5], [5, 8.7]]
    )

    model_config = ConfigDict(title="GeoJSON LineString")


class LineSchema(BaseGeometrySchema):
    """
    A GeoJSON LineString with only two points
    """
    type: Literal["LineString"]
    coordinates: tuple[tuple[float, float], tuple[float, float]] = APIField(
        example=[[1.5, 1.5], [5, 8.7]]
    )

    model_config = ConfigDict(title="GeoJSON LineString (only two points)")


class PointSchema(BaseGeometrySchema):
    """
    A GeoJSON Point
    """
    type: Literal["Point"]
    coordinates: tuple[float, float] = APIField(
        example=[1, 2.5]
    )

    model_config = ConfigDict(title="GeoJSON Point")


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


GeometriesByLevelSchema: TypeAlias = dict[int, list[GeometrySchema]]


class StatsSchema(BaseSchema):
    users_total: int
    reports_total: int
    reports_today: int
    reports_open: int
