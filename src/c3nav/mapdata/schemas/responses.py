from ninja import Schema
from pydantic import Field as APIField


class BoundsSchema(Schema):
    """
    Describing a bounding box
    """
    bounds: tuple[tuple[float, float], tuple[float, float]] = APIField(
        description="(x, y) to (x, y)",
        example=((-10, -20), (20, 30)),
    )
