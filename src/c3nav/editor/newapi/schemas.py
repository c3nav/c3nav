from typing import Annotated, Literal, Optional, Union

from ninja import Schema
from pydantic import Field as APIField
from pydantic import PositiveInt

from c3nav.api.schema import GeometrySchema, LineSchema
from c3nav.api.utils import NonEmptyStr

GeometryStylesSchema = Annotated[
    dict[
        Annotated[str, APIField(title="feature type")],
        Annotated[str, APIField(title="color")]
    ],
    APIField(description="mapping with a color for each feature type")
]
EditorID = Union[
    Annotated[PositiveInt, APIField(title="an existing object that might have been modified in this changeset")],
    Annotated[str, APIField(pattern="^c:[0-9]+$", title="an object that was created in this changeset")],
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


class BaseEditorGeometriesPropertiesSchema(Schema):
    id: EditorID
    type: NonEmptyStr
    bounds: bool = False
    color: Optional[str] = None
    opacity: Optional[float] = None   # todo: range


class EditorGeometriesGraphEdgePropertiesSchema(Schema):
    id: EditorID
    type: Literal["graphedge"]
    from_node: EditorID
    to_node: EditorID


class EditorSpaceGeometriesPropertiesSchema(BaseEditorGeometriesPropertiesSchema):
    space: EditorID


class EditorLevelGeometriesPropertiesSchema(BaseEditorGeometriesPropertiesSchema):
    level: EditorID


class EditorGeometriesGraphEdgeElemSchema(Schema):
    type: Literal["Feature"]
    properties: EditorGeometriesGraphEdgePropertiesSchema
    geometry: LineSchema


class BaseEditorGeometriesGeometryElemSchema(Schema):
    type: Literal["Feature"]
    geometry: GeometrySchema = APIField(description="geometry, potentially modified for displaying")
    original_geometry: Optional[GeometrySchema] = APIField(
        default=None,
        description="original unchanged geometry, not modified, original(??)",  # todo: more precise
    )


class EditorSpaceGeometriesGeometryElemSchema(BaseEditorGeometriesGeometryElemSchema):
    properties: EditorSpaceGeometriesPropertiesSchema


class EditorLevelGeometriesGeometryElemSchema(BaseEditorGeometriesGeometryElemSchema):
    properties: EditorLevelGeometriesPropertiesSchema


EditorSpaceGeometriesElemSchema = Union[
    EditorGeometriesUpdateCacheKeyElem,
    Annotated[EditorSpaceGeometriesGeometryElemSchema, APIField(title="a geometry object")],
    Annotated[EditorGeometriesGraphEdgeElemSchema, APIField(title="a graph edge")],
    EditorGeometriesCacheReferenceElem,
]
EditorLevelGeometriesElemSchema = Union[
    EditorGeometriesUpdateCacheKeyElem,
    Annotated[EditorLevelGeometriesGeometryElemSchema, APIField(title="a geometry object")],
    Annotated[EditorGeometriesGraphEdgeElemSchema, APIField(title="a graph edge")],
    EditorGeometriesCacheReferenceElem,
]

UpdateCacheKey = Annotated[
    Optional[NonEmptyStr],
    APIField(default=None, pattern="^c:[0-9]+$", title="the cache key under which you have cached objects"),
]
