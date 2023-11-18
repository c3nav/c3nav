from typing import Literal

from ninja import Schema
from pydantic import Field as APIField


class APIErrorSchema(Schema):
    detail: str


class PolygonSchema(Schema):
    type: Literal["Polygon"]
    coordinates: list[list[tuple[float, float]]] = APIField(
        example=[[1.5, 1.5], [1.5, 2.5], [2.5, 2.5], [2.5, 2.5]]
    )
