from typing import Annotated, Literal, Optional, Union
from uuid import UUID

from annotated_types import Lt
from pydantic import Field as APIField
from pydantic import PositiveInt
from pydantic.types import NonNegativeInt
from pydantic_extra_types.mac_address import MacAddress

from c3nav.api.schema import AnyGeometrySchema, BaseSchema, GeometrySchema, LineSchema, PointSchema
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
        pattern="^c[0-9]+$",
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
        title="new cache key",
        description="the first element of the list, it informs you of the cache key to store these geometries under"
    )
]
EditorGeometriesCacheReferenceElem = Annotated[
    tuple[
        Annotated[NonEmptyStr, APIField(title="geometry type")],
        Annotated[EditorID, APIField(title="geometry id")],  # this could be an editor id, right?
    ],
    APIField(
        title="reference to a cached geometry",
        description="replaces an element that has not changed from the cache key you supplied. get it from your cache."
    )
]


class EditorGeometriesPropertiesSchema(BaseSchema):
    id: EditorID
    type: NonEmptyStr
    space: Union[
        Annotated[EditorID, APIField(title="level")],
        Annotated[None, APIField(title="null")]
    ] = APIField(None, title="lolala")
    level: Optional[EditorID] = None
    bounds: bool = False
    color: Union[
        Annotated[str, APIField(title="color")],
        Annotated[None, APIField(title="no color")]
    ] = None
    overlay: Optional[EditorID] = None
    opacity: Optional[float] = None   # todo: range
    access_restriction: Optional[PositiveInt] = None


class EditorGeometriesGraphEdgePropertiesSchema(BaseSchema):
    id: EditorID
    type: Literal["graphedge"]
    from_node: EditorID
    to_node: EditorID
    color: Union[
        Annotated[str, APIField(title="color")],
        Annotated[None, APIField(title="no color")]
    ] = None


class EditorGeometriesGraphEdgeElemSchema(BaseSchema):
    type: Literal["Feature"]
    properties: EditorGeometriesGraphEdgePropertiesSchema
    geometry: LineSchema


class EditorGeometriesGeometryElemSchema(BaseSchema):
    type: Literal["Feature"]
    geometry: AnyGeometrySchema = APIField(description="geometry, potentially modified for displaying")
    original_geometry: Optional[GeometrySchema] = APIField(
        default=None,
        description="original unchanged geometry, not modified, original(??)",  # todo: more precise
    )
    properties: EditorGeometriesPropertiesSchema


EditorGeometriesElemSchema = Union[
    EditorGeometriesUpdateCacheKeyElem,
    Annotated[EditorGeometriesGraphEdgeElemSchema, APIField(title="a graph edge")],
    Annotated[EditorGeometriesGeometryElemSchema, APIField(title="a geometry object")],
    EditorGeometriesCacheReferenceElem,
]

UpdateCacheKey = Annotated[
    Optional[NonEmptyStr],
    APIField(default=None, title="the cache key under which you have cached objects"),
]


class EditorBeacon(BaseSchema):
    name: NonEmptyStr
    point: Optional[PointSchema]


class EditorBeaconsLookup(BaseSchema):
    wifi_beacons: dict[Annotated[MacAddress, APIField(title="WiFi beacon BSSID")], EditorBeacon]
    ibeacons: dict[
        Annotated[str, APIField(title="iBeacon UUID")],  # todo: nice to use UUID but django json encoder fails
        dict[
            Annotated[NonNegativeInt, Lt(2 ** 16), APIField(title="iBeacon major value")],
            dict[
                Annotated[NonNegativeInt, Lt(2 ** 16), APIField(title="iBeacon minor value")],
                EditorBeacon
            ]
        ]
    ]