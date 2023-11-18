from ninja import Schema
from pydantic import Field as APIField


class BoundsSchema(Schema):
    bounds: tuple[tuple[float, float], tuple[float, float]] = APIField(..., example=((-10, -20), (20, 30)))
