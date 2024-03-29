from types import NoneType
from typing import Annotated, Any, Literal, Union

from django.utils.functional import Promise
from ninja import Schema
from pydantic import Discriminator
from pydantic import Field as APIField
from pydantic import model_validator
from pydantic.functional_validators import ModelWrapValidatorHandler
from pydantic_core.core_schema import ValidationInfo

from c3nav.api.utils import NonEmptyStr


class BaseSchema(Schema):
    @model_validator(mode="wrap")  # noqa
    @classmethod
    def _run_root_validator(cls, values: Any, handler: ModelWrapValidatorHandler[Schema], info: ValidationInfo) -> Any:
        """ overwriting this, we need to call serialize to get the correct data """
        return handler(cls.convert(values))

    @classmethod
    def convert(cls, values: Any):
        if isinstance(values, Schema):
            return values
        if isinstance(values, (str, bool, int, float, complex, NoneType)):
            return values
        if isinstance(values, dict):
            return {
                key: cls.convert(val)
                for key, val in values.items()
            }
        if isinstance(values, (list, tuple, set, frozenset)):
            return type(values)(cls.convert(val) for val in values)
        if isinstance(values, Promise):
            return str(values)
        if hasattr(values, 'serialize') and callable(values.serialize):
            return cls.convert(values.serialize())
        return values


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