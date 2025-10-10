from typing import Annotated, Optional, Union

from pydantic import Field as APIField
from pydantic import NonNegativeFloat, PositiveFloat, PositiveInt

from c3nav.api.schema import BaseSchema, AnyGeometrySchema, PolygonSchema
from c3nav.api.utils import NonEmptyStr
from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.models.locations import LocationTag
from c3nav.mapdata.schemas.model_base import (DjangoModelSchema, LabelSettingsSchema, TitledSchema,
                                              WithAccessRestrictionSchema, WithLevelSchema,
                                              WithLineStringGeometrySchema, WithPointGeometrySchema,
                                              WithPolygonGeometrySchema, WithSpaceSchema, schema_description,
                                              WithGeometrySchema, LocationPoint, BoundsByLevelSchema,
                                              OptionalLocationSlugField)
from c3nav.mapdata.utils.geometry import smart_mapping
from c3nav.mapdata.utils.json import format_geojson


class LevelSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    A physical level of the map, containing building, spaces, doors…
    """
    short_label: NonEmptyStr = APIField(
        title="short label (for level selector)",
        description="unique among levels",
    )
    level_index: NonEmptyStr = APIField(
        title="level index (for coordinates)",
        description="unique among levels",
    )
    on_top_of: Union[
        Annotated[PositiveInt, APIField(
            title="level ID",
            description="level this level is on top of",
            examples=[1]
        )],
        Annotated[None, APIField(
            title="null",
            description="this is a primary level, not on top of any other"
        )]
    ] = APIField(
        title="on top of level ID",
        description="if set, this is not a primary level, but it's on top of this other level"
    )
    base_altitude: float = APIField(
        title="base/default altitude",
        description="default ground altitude for this level, if it can't be determined using altitude markers.",
    )
    default_height: PositiveFloat = APIField(
        title="default ceiling height",
        description="default ceiling height for all spaces that don't set their own",
        examples=[2.5],
    )
    door_height: PositiveFloat = APIField(
        title="door height",
        description="height for all doors on this level",
        examples=["2.0"],
    )


class BuildingSchema(WithPolygonGeometrySchema, WithLevelSchema, DjangoModelSchema):
    """
    A non-outdoor part of the map.
    """
    pass


class SpaceSchema(WithPolygonGeometrySchema, WithAccessRestrictionSchema, WithLevelSchema, DjangoModelSchema):
    """
    An accessible area on a level. It can be outside-only or inside-only.
    """
    outside: bool = APIField(
        title="outside only",
        description="determines whether to truncate to buildings or to the outside of buildings"
    )
    height: Optional[PositiveFloat] = APIField(
        title="ceiling height",
        description="if not set, default height for this level will be used"
    )


class DoorSchema(WithPolygonGeometrySchema, WithAccessRestrictionSchema, WithLevelSchema, DjangoModelSchema):
    """
    A link between two spaces
    """
    pass


class HoleSchema(WithPolygonGeometrySchema, WithSpaceSchema):
    """
    A hole in a space, showing the levels below
    """
    pass


class AreaSchema(WithPolygonGeometrySchema, WithAccessRestrictionSchema, WithSpaceSchema, DjangoModelSchema):
    """
    An area inside a space.
    """
    slow_down_factor: PositiveFloat = APIField(
        title="slow-down factor",
        description="how much walking in this area is slowed down, overlapping areas are multiplied",
        examples=[1.0],
    )


class StairSchema(WithLineStringGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    A line sharply dividing the accessible surface of a space into two different altitudes.
    """
    pass


class RampSchema(WithPolygonGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    An area in which the surface has an altitude gradient.
    """
    pass


class BaseObstacleSchema(WithSpaceSchema, DjangoModelSchema):
    height: PositiveFloat = APIField(
        title="height",
        description="size of the obstacle in the z dimension"
    )
    altitude: NonNegativeFloat = APIField(
        title="altitude above ground",
        description="altitude above ground"
    )
    color: Optional[NonEmptyStr] = APIField(
        title="color",
        description="an optional color for this obstacle"
    )


class ObstacleSchema(WithPolygonGeometrySchema, BaseObstacleSchema):
    """
    An obstacle to be subtracted from the accessible surface of a space.
    """
    pass


class LineObstacleSchema(WithLineStringGeometrySchema, BaseObstacleSchema):
    """
    An obstacle to be subtracted from the accessible surface of a space, defined as a line with width.
    """
    buffered_geometry: Union[
        PolygonSchema,
        Annotated[None, APIField(title="null", description="geometry not available of excluded from endpoint")]
    ] = APIField(
        None,
        title="buffered geometry",
        description="line turned into a polygon with the given width, "
                    "can be null if not available or excluded from endpoint",
    )
    width: PositiveFloat = APIField(
        title="width",
        description="width of the line"
    )

    @classmethod
    def get_overrides(cls, value) -> dict:
        # todo: move into model
        value: GeometryMixin
        if "geometry" in value.get_deferred_fields() or value.geometry is None:
            return {
                **super().get_overrides(value),
                "buffered_geometry": None,
            }
        return {
            **super().get_overrides(value),
            "buffered_geometry": (
                format_geojson(smart_mapping(value.buffered_geometry))
                if not getattr(value, '_hide_geometry', False) else None
            ),
        }


class ColumnSchema(WithPolygonGeometrySchema, WithSpaceSchema, DjangoModelSchema):
    """
    A ceiling-high obstacle subtracted from the space, effectively creating a "building" again.
    """
    pass


class POISchema(WithPointGeometrySchema, WithAccessRestrictionSchema, WithSpaceSchema, DjangoModelSchema):
    """
    A point of interest inside a space.
    """
    pass


class LeaveDescriptionSchema(WithSpaceSchema, DjangoModelSchema):
    """
    A description for leaving a space to enter another space.
    """
    target_space: PositiveInt = APIField(
        title="target space",
        description="the space that is being entered",
    )
    descriptions: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="description (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        examples=[{
            "en": "Stanley walked through the red door.",
            "de": "Stanley ging durch die rote Tür.",
        }]
    )
    description: NonEmptyStr = APIField(
        title="description (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class CrossDescriptionSchema(WithSpaceSchema, DjangoModelSchema):
    """
    A description for crossing through a space from one space to another.
    """
    origin_space: PositiveInt = APIField(
        title="origin space",
        description="the space from which the main space is being entered",
    )
    target_space: PositiveInt = APIField(
        title="target space",
        description="the space that is being entered from the main space",
    )
    descriptions: dict[NonEmptyStr, NonEmptyStr] = APIField(
        title="description (all languages)",
        description="property names are the ISO-language code. languages may be missing.",
        examples=[{
            "en": "Go straight ahead through the big glass doors.",
            "de": "gehe geradeaus durch die Glastüren.",
        }]
    )
    description: NonEmptyStr = APIField(
        title="description (preferred language)",
        description="preferred language based on the Accept-Language header."
    )


class LocationTagSchema(WithAccessRestrictionSchema, TitledSchema, DjangoModelSchema):
    """
    A location refering to a level, space, area, point of interest, or dynamic location.
    It can have other locations as parents (and thus, also, children).
    """
    slug: OptionalLocationSlugField
    subtitle: NonEmptyStr = APIField(
        title="subtitle (preferred language)",
        description="an automatically generated short description for this location in the "
                    "preferred language based on the Accept-Language header.",
        examples=["near Area 51"],
    )
    icon: Optional[NonEmptyStr] = APIField(
        title="set icon name",
        description="as set in the object specifically (any material design icon name)",
        examples=["pin_drop"],
    )
    effective_icon: Optional[NonEmptyStr] = APIField(  # todo: not optional?
        title="icon name to use",
        description="effective icon to use (any material design icon name)",
        examples=["pin_drop"],
    )
    can_search: bool = APIField(
        title="can be searched",
        description="if `true`, this object can show up in search results",
    )
    can_describe: bool = APIField(
        title="can describe locations",
        description="if `true`, this object can be used to describe other locations (e.g. in their subtitle)",
    )
    add_search: str = APIField(
        title="additional search terms",
        description="more data for the search index separated by spaces",
        examples=["more search terms"],
    )

    # add children or something here
    label_settings: Optional[PositiveInt] = APIField(
        default=None,
        title="label settings",
        description=(
                schema_description(LabelSettingsSchema) +
                "\n\nif not set, label settings of location groups should be used"
        )
    )
    label_override: Union[
        Annotated[NonEmptyStr, APIField(title="label override", description="text to use for label")],
        Annotated[None, APIField(title="null", description="title will be used")],
    ] = APIField(
        default=None,
        title="label override (preferred language)",
        description="text to use for the label. by default (null), the title would be used."
    )
    load_group_display: Optional[PositiveInt] = APIField(
        default=None,
        title="load group to display",
    )

    points: list[LocationPoint]
    bounds: BoundsByLevelSchema

    # imported from group
    priority: int = APIField()
    can_report_missing: LocationTag.CanReportMissing = APIField(
        title="report missing locations",
        description="whether this location group can be used to report missing locations",
    )
    color: Union[
        Annotated[NonEmptyStr, APIField(title="color", description="a valid CSS color expression")],
        Annotated[None, APIField(title="null", description="default/no color will be used")],
    ] = APIField(
        title="color",
        description="an optional color for spaces and areas with this group"
    )

    @classmethod
    def get_overrides(cls, value):
        return {
            "locationtype": "tag",
            "label_settings": value.label_settings_id,
            "load_group_display": value.load_group_display_id
        }


class DynamicLocationTagTargetSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    Represents a moving object. Its position has to be separately queried through the position API.
    """
    pass


class DataOverlaySchema(TitledSchema, DjangoModelSchema):
    """
    Represents a collection of geometries to be displayed as an optional overlay to the map.
    """
    description: Optional[str]
    stroke_color: Optional[str]
    stroke_width: Optional[float]
    stroke_opacity: Optional[float]
    fill_color: Optional[str]
    fill_opacity: Optional[float]
    cluster_points: bool
    update_interval: Optional[PositiveInt]


class DataOverlayFeatureSchema(TitledSchema, DjangoModelSchema):
    """
    A feature (any kind of geometry) to be displayed as part of a data overlay.
    """
    level_id: PositiveInt
    stroke_color: Optional[str]
    stroke_width: Optional[float]
    stroke_opacity: Optional[float]
    fill_color: Optional[str]
    fill_opacity: Optional[float]
    show_label: bool
    show_geometry: bool
    interactive: bool
    point_icon: Optional[str]
    external_url: Optional[str]
    extra_data: Optional[dict[str, str | int | float]]


class DataOverlayFeatureGeometrySchema(WithGeometrySchema, DjangoModelSchema):
    """
    A feature (any kind of geometry) to be displayed as part of a data overlay.
    """
    geometry: AnyGeometrySchema


class DataOverlayFeatureUpdateSchema(BaseSchema):
    """
    An update to a data overlay feature.
    """
    level_id: Optional[PositiveInt] = None
    stroke_color: Optional[str] = None
    stroke_width: Optional[float] = None
    stroke_opacity: Optional[float] = None
    fill_color: Optional[str] = None
    fill_opacity: Optional[float] = None
    show_label: Optional[bool] = None
    show_geometry: Optional[bool] = None
    interactive: Optional[bool] = None
    point_icon: Optional[str] = None
    external_url: Optional[str] = None
    extra_data: Optional[dict[str, str | int | float]] = None


class DataOverlayFeatureBulkUpdateItemSchema(BaseSchema):
    """
    An item of a bulk update to data overlay features (no geometries).
    """
    id: PositiveInt
    level_id: Optional[PositiveInt] = None
    stroke_color: Optional[str] = None
    stroke_width: Optional[float] = None
    stroke_opacity: Optional[float] = None
    fill_color: Optional[str] = None
    fill_opacity: Optional[float] = None
    show_label: Optional[bool] = None
    show_geometry: Optional[bool] = None
    interactive: Optional[bool] = None
    point_icon: Optional[str] = None
    external_url: Optional[str] = None
    extra_data: Optional[dict[str, str | int | float]] = None


class DataOverlayFeatureBulkUpdateSchema(BaseSchema):
    """
    A bulk update to data overlay features
    """
    updates: list[DataOverlayFeatureBulkUpdateItemSchema]


class WayTypeSchema(TitledSchema, DjangoModelSchema):
    """
    Waytypes for navigation like stairs, escalators etc
    """
    pass


class SourceSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    A source image that can be traced in the editor.
    """
    name: NonEmptyStr = APIField(
        title="name",
        description="name/filename of the source",
    )
    bounds: tuple[
        tuple[
            Annotated[float, APIField(title="left")],
            Annotated[float, APIField(title="bottom")],
        ],
        tuple[
            Annotated[float, APIField(title="right")],
            Annotated[float, APIField(title="top")],
        ]
    ]


class AccessRestrictionSchema(TitledSchema, DjangoModelSchema):
    """
    A category that some objects can belong to.

    If they do, you can only see them if you have a permission to see objects with this access retriction.
    """
    public: bool
    groups: list[PositiveInt] = APIField(
        title="access restriction groups"
    )


class AccessRestrictionGroupSchema(WithAccessRestrictionSchema, DjangoModelSchema):
    """
    For simplicity's sake, access restrictions can belong to groups, and you can grant permissions for the entire group.
    """
    pass


class ProjectionPipelineSchema(BaseSchema):
    pipeline: Union[
        Annotated[NonEmptyStr, APIField(title='proj4 string')],
        Annotated[None, APIField(title='null', description='projection not available')]
    ] = APIField(
        title='proj4 string',
        description='proj4 string for converting WGS84 coordinates to c3nav coordinates if available',
        examples=['+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs']
    )


class ProjectionSchema(ProjectionPipelineSchema):
    proj4: NonEmptyStr = APIField(
        title='proj4 string',
        description='proj4 string for converting WGS84 coordinates to c3nav coordinates without offset and rotation',
        examples=['+proj=utm +zone=33 +ellps=GRS80 +units=m +no_defs']
    )
    zero_point: tuple[float, float] = APIField(
        title='zero point',
        description='coordinates of the zero point of the c3nav coordinate system',
        examples=[(0.0, 0.0)],
    )
    rotation: float = APIField(
        title='rotation',
        description='rotational offset of the c3nav coordinate system',
        examples=[0.0],
    )
    rotation_matrix: Optional[tuple[
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
        float, float, float, float,
    ]] = APIField(
        title='rotation matrix',
        description='rotation matrix for rotational offset of the c3nav coordinate system',
        examples=[[
            1, 0, 0, 0,
            0, 1, 0, 0,
            0, 0, 1, 0,
            0, 0, 0, 1
        ]]
    )


class LegendItemSchema(BaseSchema):
    title: NonEmptyStr = APIField()
    fill: str | None
    border: str | None


class LegendSchema(BaseSchema):
    base: list[LegendItemSchema]
    groups: list[LegendItemSchema]
    obstacles: list[LegendItemSchema]
