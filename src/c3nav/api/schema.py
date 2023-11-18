from typing import Literal

from ninja import Schema
from pydantic import Field as APIField

from c3nav.api.utils import NonEmptyStr


class APIErrorSchema(Schema):
    """
    An error has occured with this request
    """
    detail: NonEmptyStr = APIField(
        description="A human-readable error description"
    )


class PolygonSchema(Schema):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = APIField(
        example=[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]
    )
