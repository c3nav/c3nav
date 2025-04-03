import typing
from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator, RegexValidator
from django.db import models
from django.utils.functional import cached_property
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _
from django_pydantic_field.fields import SchemaField
from pydantic_extra_types.mac_address import MacAddress
from shapely import Polygon, MultiPolygon
from shapely.geometry import CAP_STYLE, JOIN_STYLE, mapping, shape, Point

from c3nav.api.schema import GeometriesByLevelSchema
from c3nav.mapdata.fields import GeometryField, I18nField
from c3nav.mapdata.models import Space
from c3nav.mapdata.models.access import AccessRestrictionMixin, UseQForPermissionsManager, AccessRestrictionLogicMixin
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.base import GeometryMixin, CachedEffectiveGeometryMixin, CachedEffectiveGeometries, \
    CachedPoints, CachedBounds
from c3nav.mapdata.models.locations import LoadGroup, SpecificLocationGeometryTargetMixin
from c3nav.mapdata.permissions import MapPermissions, MapPermissionTaggedItem
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.geometry import unwrap_geom
from c3nav.mapdata.utils.json import format_geojson
from c3nav.routing.schemas import BeaconMeasurementDataSchema

if typing.TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager


class SpaceGeometryMixin(AccessRestrictionLogicMixin, GeometryMixin, models.Model):
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))

    class Meta:
        abstract = True

    @cached_property
    def level_id(self):
        if "space" in self._state.fields_cache:
            return self.space.level_id
        return None

    @cached_property
    def primary_level_id(self):
        if "space" in self._state.fields_cache:
            return self.space.primary_level_id
        return None

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        if hasattr(self, 'get_color'):
            from c3nav.mapdata.render.theme import ColorManager
            color = self.get_color(ColorManager.for_theme(None))
            if color:
                result['color'] = color
        if hasattr(self, 'opacity'):
            result['opacity'] = self.opacity
        return result

    @property
    def subtitle(self):
        if "space" in self._state.fields_cache:
            if "level" in self.space._state.fields_cache:
                return format_lazy(_('{space}, {level}'),
                                   space=self.space.title,
                                   level=self.space.level.title)
            return self.space.title
        return None

    @classmethod
    def q_for_permissions(cls, permissions: MapPermissions, prefix=''):
        return (
            super().q_for_permissions(permissions, prefix=prefix) &
            Space.q_for_permissions(permissions, prefix=prefix + 'space__')
        )

    @cached_property
    def effective_access_restrictions(self) -> set[int]:
        return (
            super().effective_access_restrictions |
            self.space.effective_access_restrictions
        )

    def register_change(self, force=False):
        space = self.space
        if force or self._state.adding or self.all_geometry_changed or self.geometry_changed:
            changed_geometries.register(space.level_id, space.geometry.buffer(0).intersection(
                unwrap_geom(self.geometry if force or self._state.adding else self.get_changed_geometry()).buffer(0)
            ))

    def register_delete(self):
        space = self.space
        changed_geometries.register(space.level_id, space.geometry.intersection(unwrap_geom(self.geometry)))

    def pre_save_changed_geometries(self):
        self.register_change()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)


class Column(SpaceGeometryMixin, AccessRestrictionMixin, models.Model):
    """
    An column in a space, also used to be able to create rooms within rooms.
    """
    geometry = GeometryField('polygon')

    @classmethod
    def q_for_permissions(cls, permissions: MapPermissions, prefix=''):
        """
        Permissions for columns are inverted. A column disappears when you have the permission.
        Is this weird? Heck yes. Maybe we should change it.
        This code doesn't filter by permissions though. This needs to be done during rendering.
        """
        return (
            Space.q_for_permissions(permissions, prefix=prefix + 'space__')
        )

    class Meta:
        verbose_name = _('Column')
        verbose_name_plural = _('Columns')
        default_related_name = 'columns'


class Area(CachedEffectiveGeometryMixin, SpaceGeometryMixin, SpecificLocationGeometryTargetMixin,
           AccessRestrictionMixin, models.Model):
    """
    An area in a space.
    """
    geometry = GeometryField('polygon')
    slow_down_factor = models.DecimalField(_('slow down factor'), max_digits=6, decimal_places=2, default=1,
                                           validators=[MinValueValidator(Decimal('0.01'))],
                                           help_text=_('values of overlapping areas get multiplied!'))
    main_point = GeometryField('point', null=True, blank=True,
                               help_text=_('main routing point (optional)'))

    load_group_contribute = models.ForeignKey(LoadGroup, on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    class Meta:
        verbose_name = _('Area')
        verbose_name_plural = _('Areas')
        default_related_name = 'areas'

    @classmethod
    def recalculate_effective_geometries(cls):
        # this function is intentionally not fully optimized yet. this could be changed, but please write tests first
        for area in cls.objects.prefetch_related("space", "space__level"):
            results: list[MapPermissionTaggedItem[Polygon | MultiPolygon]] = []
            # we are caching resulting polygons by their area to find duplicates
            results_by_area: dict[float, list[MapPermissionTaggedItem[Polygon | MultiPolygon]]] = {}

            # go through all possible space geometries, starting with the least restricted ones
            for space_geometry, access_restriction_ids in reversed(area.space.cached_effective_geometries):
                # further restrict with the access restrictions of this area
                item_access_restrictions = access_restriction_ids | area.effective_access_restrictions

                # crop this area to this version of the space
                geometry = area.geometry.intersection(shape(space_geometry))

                # no geometry left? goodbye
                if geometry.is_empty:
                    continue

                # seach whether we had this same polygon as a result before
                for previous_result in results_by_area.get(geometry.area, []):
                    if (item_access_restrictions >= results_by_area
                            and previous_result.value.equals_exact(geometry, 1e-3)):
                        # if the found polygon matches and has a subset of restrictions, no need to store this one
                        break

                # create and store item
                item = MapPermissionTaggedItem(
                    value=geometry,
                    access_restrictions=access_restriction_ids
                )
                results_by_area.setdefault(geometry.area, []).append(item)
                results.append(item)

            # we need to reverse the list back to make the logic work
            area.cached_effective_geometries = list(reversed(results))
            area.save()


class Stair(SpaceGeometryMixin, models.Model):
    """
    A stair
    """
    geometry = GeometryField('linestring')

    class Meta:
        verbose_name = _('Stair')
        verbose_name_plural = _('Stairs')
        default_related_name = 'stairs'


class Ramp(SpaceGeometryMixin, models.Model):
    """
    A ramp
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Ramp')
        verbose_name_plural = _('Ramps')
        default_related_name = 'ramps'


# todo: move to other file? this is NOT a geometry!
class ObstacleGroup(TitledMixin, models.Model):
    color = models.CharField(max_length=32, null=True, blank=True)
    in_legend = models.BooleanField(default=False, verbose_name=_('show in legend (if color set)'))

    class Meta:
        verbose_name = _('Obstacle Group')
        verbose_name_plural = _('Obstacle Groups')
        default_related_name = 'groups'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig = {"color": self.color}

    def register_changed_geometries(self):
        for obj in self.obstacles.select_related('space'):
            obj.register_change(force=True)
        for obj in self.lineobstacles.select_related('space'):
            obj.register_change(force=True)

    def pre_save_changed_geometries(self):
        if not self._state.adding and any(getattr(self, attname) != value for attname, value in self._orig.items()):
            self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries()

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


class Obstacle(SpaceGeometryMixin, models.Model):
    """
    An obstacle
    """
    group = models.ForeignKey(ObstacleGroup, null=True, blank=True, on_delete=models.SET_NULL)
    geometry = GeometryField('polygon')
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, default=0.8,
                                 validators=[MinValueValidator(Decimal('0'))])
    altitude = models.DecimalField(_('altitude above ground'), max_digits=6, decimal_places=2, default=0,
                                   validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        verbose_name = _('Obstacle')
        verbose_name_plural = _('Obstacles')
        default_related_name = 'obstacles'
        ordering = ('altitude', 'height')

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        from c3nav.mapdata.render.theme import ColorManager
        color = self.get_color(ColorManager.for_theme(None))
        if color:
            result['color'] = color
        return result

    @property
    def color(self):
        from c3nav.mapdata.render.theme import ColorManager
        return self.get_color(ColorManager.for_theme(None))

    def get_color(self, color_manager: 'ThemeColorManager'):
        return (
            color_manager.obstaclegroup_fill_color(self.group)
            if self.group is not None
            else color_manager.obstacles_default_fill
        )


class LineObstacle(SpaceGeometryMixin, models.Model):
    """
    An obstacle that is a line with a specific width
    """
    group = models.ForeignKey(ObstacleGroup, null=True, blank=True, on_delete=models.SET_NULL)
    geometry = GeometryField('linestring')
    width = models.DecimalField(_('width'), max_digits=4, decimal_places=2, default=0.15)
    height = models.DecimalField(_('height'), max_digits=6, decimal_places=2, default=0.8,
                                 validators=[MinValueValidator(Decimal('0'))])
    altitude = models.DecimalField(_('altitude above ground'), max_digits=6, decimal_places=2, default=0,
                                   validators=[MinValueValidator(Decimal('0'))])

    class Meta:
        verbose_name = _('Line Obstacle')
        verbose_name_plural = _('Line Obstacles')
        default_related_name = 'lineobstacles'
        ordering = ('altitude', 'height')

    def get_geojson_properties(self, *args, **kwargs) -> dict:
        result = super().get_geojson_properties(*args, **kwargs)
        from c3nav.mapdata.render.theme import ColorManager
        color = self.get_color(ColorManager.for_theme(None))
        if color:
            result['color'] = color
        return result

    @property
    def color(self):
        from c3nav.mapdata.render.theme import ColorManager
        return self.get_color(ColorManager.for_theme(None))

    def get_color(self, color_manager: 'ThemeColorManager'):
        # TODO: should line obstacles use border color?
        return (
            color_manager.obstaclegroup_fill_color(self.group)
            if self.group is not None
            else color_manager.obstacles_default_fill
        )

    @property
    def buffered_geometry(self):
        return self.geometry.buffer(float(self.width / 2), join_style=JOIN_STYLE.mitre, cap_style=CAP_STYLE.flat)

    def to_geojson(self, *args, **kwargs):
        result = super().to_geojson(*args, **kwargs)
        result['original_geometry'] = result['geometry']
        result['geometry'] = format_geojson(mapping(self.buffered_geometry))
        return result


class POI(SpaceGeometryMixin, SpecificLocationGeometryTargetMixin, AccessRestrictionMixin, models.Model):
    """
    A point of interest
    """
    geometry = GeometryField('point')

    class Meta:
        verbose_name = _('Point of Interest')
        verbose_name_plural = _('Points of Interest')
        default_related_name = 'pois'

    @property
    def x(self):
        return self.geometry.x

    @property
    def y(self):
        return self.geometry.y

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        if self.level_id is None:
            return {}
        return {self.level_id: self.geometry}

    @property
    def effective_geometry(self) -> Point:
        return self.geometry

    @property
    def cached_effective_geometries(self) -> list[MapPermissionTaggedItem[Point]]:
        return [MapPermissionTaggedItem(
            value=self.geometry,
            access_restrictions=frozenset(self.effective_access_restrictions),
        )]

    @property
    def cached_points(self) -> CachedPoints:
        return [MapPermissionTaggedItem(
            value=self.geometry.coords[0],
            access_restrictions=frozenset(self.effective_access_restrictions),
        )]

    @property
    def cached_bounds(self) -> CachedBounds:
        return CachedBounds(*(
            (MapPermissionTaggedItem(value=round(value, 2), access_restrictions=frozenset(self.effective_access_restrictions)), )
            for value in self.geometry.bounds
        ))


class Hole(SpaceGeometryMixin, models.Model):
    """
    A hole in the ground of a space, e.g. for stairs.
    """
    geometry = GeometryField('polygon')

    class Meta:
        verbose_name = _('Hole')
        verbose_name_plural = _('Holes')
        default_related_name = 'holes'


class AltitudeMarker(SpaceGeometryMixin, models.Model):
    """
    An altitude marker
    """
    geometry = GeometryField('point')
    groundaltitude = models.ForeignKey('mapdata.GroundAltitude', on_delete=models.CASCADE,
                                       verbose_name=_('altitude'))

    class Meta:
        verbose_name = _('Altitude Marker')
        verbose_name_plural = _('Altitude Markers')
        default_related_name = 'altitudemarkers'

    @property
    def altitude(self) -> Decimal:
        return self.groundaltitude.altitude

    @property
    def title(self):
        return f'#{self.pk}: {self.groundaltitude.title}'


class LeaveDescription(models.Model):
    """
    A description for leaving a space to another space
    """
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))
    target_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('target space'),
                                     related_name='enter_descriptions')
    description = I18nField(_('description'), plural_name='descriptions')

    objects = UseQForPermissionsManager()

    class Meta:
        verbose_name = _('Leave description')
        verbose_name_plural = _('Leave descriptions')
        default_related_name = 'leave_descriptions'
        unique_together = (
            ('space', 'target_space')
        )

    @cached_property
    def title(self):
        return self.target_space.title

    @classmethod
    def q_for_permissions(cls, permissions: MapPermissions, prefix=''):
        return (
            Space.q_for_permissions(permissions, prefix=prefix + 'space__')
            & Space.q_for_permissions(permissions, prefix=prefix + 'target_space__')
        )


class CrossDescription(models.Model):
    """
    A description for crossing a space from one space to another space
    """
    space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('space'))
    origin_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('origin space'),
                                     related_name='leave_cross_descriptions')
    target_space = models.ForeignKey('mapdata.Space', on_delete=models.CASCADE, verbose_name=_('target space'),
                                     related_name='cross_enter_descriptions')
    description = I18nField(_('description'), plural_name='descriptions')

    objects = UseQForPermissionsManager()

    class Meta:
        verbose_name = _('Cross description')
        verbose_name_plural = _('Cross descriptions')
        default_related_name = 'cross_descriptions'
        unique_together = (
            ('space', 'origin_space', 'target_space')
        )

    @cached_property
    def title(self):
        return '%s → %s' % (self.origin_space.title, self.target_space.title)

    @classmethod
    def q_for_permissions(cls, permissions: MapPermissions, prefix=''):
        return (
            Space.q_for_permissions(permissions, prefix=prefix + 'space__')
            & Space.q_for_permissions(permissions, prefix=prefix + 'origin_space__')
            & Space.q_for_permissions(permissions, prefix=prefix + 'target_space__')
        )


class BeaconMeasurement(SpaceGeometryMixin, models.Model):
    """
    A Beacon (WiFI / iBeacon) measurement
    """
    geometry = GeometryField('point')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                               verbose_name=_('author'))
    comment = models.TextField(null=True, blank=True, verbose_name=_('comment'))
    data: BeaconMeasurementDataSchema = SchemaField(BeaconMeasurementDataSchema,
                                                    verbose_name=_('Measurement list'),
                                                    default=BeaconMeasurementDataSchema())

    fill_quest = models.BooleanField(_('create a quest to fill this'), default=False)

    class Meta:
        verbose_name = _('Beacon Measurement')
        verbose_name_plural = _('Beacon Measurements')
        default_related_name = 'beacon_measurements'

    @property
    def all_geometry_changed(self):
        return False

    @property
    def geometry_changed(self):
        return False

    @staticmethod
    def contribute_bssid_to_beacons(items: list["BeaconMeasurement"]):
        map_name = {}
        for item in items:
            for scan in item.data.wifi:
                for peer in scan:
                    if peer.ap_name:
                        map_name.setdefault(peer.ap_name, []).append(peer.bssid)
        for beacon in RangingBeacon.objects.filter(ap_name__in=map_name.keys(),
                                                   beacon_type=RangingBeacon.BeaconType.EVENT_WIFI):
            print(beacon, "add ssids", set(map_name[beacon.ap_name]))
            beacon.addresses = list(set(beacon.addresses) | set(map_name[beacon.ap_name]))
            beacon.save()

    def save(self, *args, **kwargs):
        self.contribute_bssid_to_beacons([self])
        return super().save(*args, **kwargs)


class RangingBeacon(SpaceGeometryMixin, models.Model):
    """
    A ranging beacon
    """
    class BeaconType(models.TextChoices):
        EVENT_WIFI = "event_wifi", _("Event WiFi AP")
        DECT = "dect", _("DECT antenna")

    geometry = GeometryField('point')

    beacon_type = models.CharField(_('beacon type'), choices=BeaconType.choices,
                                   null=True, blank=True, max_length=16)

    node_number = models.PositiveSmallIntegerField(_('Node Number'), unique=True, null=True, blank=True)

    addresses: list[MacAddress] = SchemaField(list[MacAddress], verbose_name=_('Mac Address / BSSIDs'), default=list,
                                              blank=True, help_text=_("uses node's value if not set"))
    bluetooth_address = models.CharField(_('Bluetooth Address'), unique=True, null=True, blank=True,
                                         max_length=17,
                                         validators=[RegexValidator(
                                             regex='^([a-f0-9]{2}:){5}[a-f0-9]{2}$',
                                             message='Must be a lower-case mac address',
                                             code='invalid_bluetooth_address'
                                         )],
                                         help_text=_("uses node's value if not set"))
    ibeacon_uuid = models.UUIDField(_('iBeacon UUID'), null=True, blank=True,
                                    help_text=_("uses node's value if not set"))
    ibeacon_major = models.PositiveIntegerField(_('iBeacon major value'), null=True, blank=True,
                                    help_text=_("uses node's value if not set"))
    ibeacon_minor = models.PositiveIntegerField(_('iBeacon minor value'), null=True, blank=True,
                                                help_text=_("uses node's value if not set"))
    uwb_address = models.CharField(_('UWB Address'), unique=True, null=True, blank=True,
                                   max_length=23,
                                   validators=[RegexValidator(
                                       regex='^([a-f0-9]{2}:){7}[a-f0-9]{2}$',
                                       message='Must be a lower-case 8-byte UWB address',
                                       code='invalid_uwb_address'
                                   )],
                                   help_text=_("uses node's value if not set"))

    altitude = models.DecimalField(_('altitude above ground'), max_digits=6, decimal_places=2, default=0,
                                   validators=[MinValueValidator(Decimal('0'))])
    ap_name = models.CharField(null=True, blank=True, verbose_name=_('AP name'), max_length=32)
    comment = models.TextField(null=True, blank=True, verbose_name=_('comment'))

    altitude_quest = models.BooleanField(_('altitude quest'), default=True)

    num_clients = models.IntegerField(_('current number of clients'), default=0)
    max_observed_num_clients = models.IntegerField(_('highest observed number of clients'), default=0)

    class Meta:
        verbose_name = _('Ranging beacon')
        verbose_name_plural = _('Ranging beacons')
        default_related_name = 'ranging_beacons'

    @property
    def all_geometry_changed(self):
        return False

    @property
    def geometry_changed(self):
        return False

    @property
    def title(self):
        segments = []
        if self.node_number is not None:
            segments.append(self.node_number)
        if self.ap_name is not None:
            segments.append(f'"{self.ap_name}"')
        if segments:
            title = ' - '.join(segments).strip()
        else:
            title = f'#{self.pk}'
        if self.addresses:
            ssids = self.addresses[0] + (', …' if len(self.addresses) > 1 else '')
            title += f' ({ssids})'
        if self.comment:
            title += f' ({self.comment})'

        return f'{self.get_beacon_type_display() if self.beacon_type else self._meta.verbose_name} {title}'
