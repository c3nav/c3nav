from typing import Annotated, Literal, Optional, Union

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import AnyGeometrySchema, GeometrySchema, LineSchema
from c3nav.api.utils import NonEmptyStr

GeometryStylesSchema = Annotated[
    dict[
        Annotated[str, APIField(title="feature type")],
        Annotated[str, APIField(title="color")]
    ],
    APIField(description="mapping with a color for each feature type")
]
EditorID = Union[
    Annotated[PositiveInt, APIField(
        title="existing object",
        description="ID of an existing object that might have been modified in this changeset"
    )],
    Annotated[str, APIField(
        pattern="^c:[0-9]+$",
        title="created object",
        description="id of an object that was created in this changeset"
    )],
]
EditorGeometriesUpdateCacheKeyElem = Annotated[
    tuple[
        Literal["update_cache_key"],
        Annotated[NonEmptyStr, APIField(title="the new cache key")],
    ],
    APIField(
        title="new cache key",  # todo better explanation
        description="the first element of the list, it informs you of the cache key to store these geometries under"
    )
]
EditorGeometriesCacheReferenceElem = Annotated[
    tuple[
        Annotated[NonEmptyStr, APIField(title="geometry type")],
        Annotated[EditorID, APIField(title="geometry id")],  # this could be an editor id, right?
    ],
    APIField(
        title="reference to a cached geometry",  # todo better explanation
        description="replaces an element that has not changed from the cache key you supplied. get it from your cache."
    )
]


class EditorGeometriesPropertiesSchema(Schema):
    id: EditorID
    type: NonEmptyStr
    space: Optional[EditorID] = None
    level: Optional[EditorID] = None
    bounds: bool = False
    color: Optional[str] = None
    opacity: Optional[float] = None   # todo: range


class EditorGeometriesGraphEdgePropertiesSchema(Schema):
    id: EditorID
    type: Literal["graphedge"]
    from_node: EditorID
    to_node: EditorID


class EditorGeometriesGraphEdgeElemSchema(Schema):
    type: Literal["Feature"]
    properties: EditorGeometriesGraphEdgePropertiesSchema
    geometry: LineSchema


class EditorGeometriesGeometryElemSchema(Schema):
    type: Literal["Feature"]
    geometry: AnyGeometrySchema = APIField(description="geometry, potentially modified for displaying")
    original_geometry: Optional[GeometrySchema] = APIField(
        default=None,
        description="original unchanged geometry, not modified, original(??)",  # todo: more precise
    )
    properties: EditorGeometriesPropertiesSchema


EditorGeometriesElemSchema = Union[
    EditorGeometriesUpdateCacheKeyElem,
    Annotated[EditorGeometriesGeometryElemSchema, APIField(title="a geometry object")],
    Annotated[EditorGeometriesGraphEdgeElemSchema, APIField(title="a graph edge")],
    EditorGeometriesCacheReferenceElem,
]

UpdateCacheKey = Annotated[
    Optional[NonEmptyStr],
    APIField(default=None, title="the cache key under which you have cached objects"),
]
