import string
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import cached_property
from itertools import chain, batched
from typing import TYPE_CHECKING, Optional, TypeAlias, Union, Iterable

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.constraints import CheckConstraint, UniqueConstraint
from django.db.models.expressions import F, OuterRef, Exists
from django.db.models.signals import m2m_changed
from django.db.utils import IntegrityError
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.functional import lazy
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, get_language, get_language_info
from django_pydantic_field import SchemaField
from shapely.geometry import shape

from c3nav.api.schema import GeometriesByLevelSchema, PolygonSchema, MultiPolygonSchema, GeometriesByLevel, PointSchema
from c3nav.mapdata.fields import I18nField, lazy_get_i18n_value
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin, UseQForPermissionsManager
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.base import CachedBounds, LazyMapPermissionFilteredBounds
from c3nav.mapdata.permissions import MapPermissionGuardedSequence, MapPermissionTaggedItem, \
    MapPermissionGuardedTaggedValue, MapPermissionGuardedTaggedValueSequence, \
    MapPermissionMaskedTaggedValue, MapPermissionGuardedTaggedSequence, AccessRestrictionsEval, NoAccessRestrictions, \
    AccessRestrictionsAllIDs, AccessRestrictionsOr
from c3nav.mapdata.schemas.locations import GridSquare, DynamicLocationState
from c3nav.mapdata.schemas.model_base import LocationPoint, BoundsByLevelSchema, \
    DjangoCompatibleLocationPoint
from c3nav.mapdata.utils.cache.proxied import per_request_cache
from c3nav.mapdata.utils.fields import LocationById
from c3nav.mapdata.utils.geometry.modify import merge_bounds

if TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager  # noqa
    from c3nav.mapdata.models import Level, Space, Area, POI  # noqa
    from c3nav.mapdata.locations import CustomLocation  # noqa


validate_slug = RegexValidator(
    r'^[a-z0-9-]*[a-z]+[a-z0-9-]*\Z',
    # Translators: "letters" means latin letters: a-z and A-Z.
    _('Enter a valid location slug consisting of lowercase letters, numbers or hyphens, with at least one letter.'),
    'invalid'
)


class LocationSlug(models.Model):
    slug = models.SlugField(_('Slug'), unique=True, max_length=50, validators=[validate_slug])
    redirect = models.BooleanField(default=False)
    target = models.ForeignKey('LocationTag', on_delete=models.CASCADE, related_name='slug_set')

    class Meta:
        verbose_name = _('Location Slug')
        verbose_name_plural = _('Location Slug')
        default_related_name = 'locationslugs'

        constraints = [
            models.UniqueConstraint(fields=["target"], condition=Q(redirect=False),
                                    name="unique_non_redirect_slugs")
        ]


StaticLocationTagTarget: TypeAlias = Union["Level", "Space", "Area", "POI"]
LocationTarget: TypeAlias = Union["DynamicLocationTagTarget", "StaticLocationTagTarget"]


@dataclass(frozen=True)
class FillAndBorderColor:
    fill: str | None
    border: str | None


# todo: make it possibel for the guarded lists to be serializable on their own?
ColorByTheme: TypeAlias = dict[int, list[MapPermissionTaggedItem[FillAndBorderColor]]]
CachedStrings: TypeAlias = list[MapPermissionTaggedItem[str]]
CachedTitles: TypeAlias = list[MapPermissionTaggedItem[dict[str, str]]]
CachedLocationTargetIDs: TypeAlias = list[MapPermissionTaggedItem[tuple[str, int]]]

TaggedLocationGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema | PointSchema]]
TaggedMaskedLocationGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema]]


@dataclass(frozen=True)
class MaskedLocationTagGeometry:
    geometry: TaggedLocationGeometries
    masked_geometry: TaggedMaskedLocationGeometries
    space_id: int


CachedBoundsByLevel: TypeAlias = dict[int, CachedBounds]
CachedGeometriesByLevel: TypeAlias = dict[int, list[MaskedLocationTagGeometry | TaggedLocationGeometries]]
CachedLocationPoints: TypeAlias = list[list[MapPermissionTaggedItem[DjangoCompatibleLocationPoint]]]

CachedIDs: TypeAlias = list[MapPermissionTaggedItem[int]]


class LocationTagAdjacency(models.Model):
    """
    A direct parent-child-relationship between two locations.
    """
    parent = models.ForeignKey("LocationTag", on_delete=models.PROTECT, related_name="+")
    child = models.ForeignKey("LocationTag", on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = (
            UniqueConstraint(fields=("parent", "child"), name="unique_location_tag_parent_child"),
            CheckConstraint(check=~Q(parent=F("child")), name="location_tag_parent_cant_be_child"),
        )


class LocationTagManager(UseQForPermissionsManager):
    def get_queryset(self):
        return super().get_queryset().select_related("inherited")

    def without_inherited(self):
        return super().get_queryset()

    def with_restrictions(self):
        return self.prefetch_related("effective_access_restriction_sets__access_restrictions")

    def bulk_create(self, *args, **kwargs):
        with transaction.atomic():
            results = super().bulk_create(*args, **kwargs)
            self.model._post_save((instance.pk for instance in results))
        return results

    def create(self, **kwargs):
        with transaction.atomic():
            result = super().create(**kwargs)
            self.model._post_save((result.pk, ))
        return result


class LocationTag(AccessRestrictionMixin, TitledMixin, models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.ListedLocationProtocol`.
    """
    locationtype = "tag"
    slug_as_id = False

    class CanReportMissing(models.TextChoices):
        DONT_OFFER = "dont_offer", _("don't offer")
        REJECT = "reject", _("offer in first step, then reject")
        SINGLE = "single", _("offer in first step, exclusive choice")
        MULTIPLE = "multiple", _("offer if nothing in the first step matches, multiple choice")

    class CanReportMistake(models.TextChoices):
        # todo: give inheritance options to this :)
        ALLOW = "allow", _("allow")
        REJECT = "reject", _("reject for all locations and sublocations")

    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can describe'))
    icon = models.CharField(_('icon'), max_length=32, null=True, blank=True, help_text=_('any material icons name'))
    external_url = models.URLField(_('external URL'), null=True, blank=True)

    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'))
    label_override = I18nField(_('Label override'), plural_name='label_overrides', blank=True, fallback_any=True)

    import_tag = models.CharField(_('import tag'), null=True, blank=True, max_length=64)
    import_block = models.BooleanField(_('don\'t change on import'), default=False)

    load_group_display = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='+', verbose_name=_('display load group'))
    include_in_random_location = models.BooleanField(_('include this and descendants with no children in '
                                                       'random location feature'), default=False)

    # imported from locationgroup start

    priority = models.IntegerField(default=0, db_index=True)

    can_report_missing = models.CharField(_('report missing location'), choices=CanReportMissing.choices,
                                          default=CanReportMissing.DONT_OFFER, max_length=16)
    can_report_mistake = models.CharField(_('report mistakes'), choices=CanReportMistake.choices,
                                          default=CanReportMistake.ALLOW, max_length=16)

    description = I18nField(_('description'), plural_name='descriptions', blank=True, fallback_any=True,
                            fallback_value="", help_text=_('to aid with selection in the report form'))
    report_help_text = I18nField(_('report help text'), plural_name='report_help_texts', blank=True, fallback_any=True,
                                 fallback_value="", help_text=_('to explain the report form or rejection'))

    color = models.CharField(null=True, blank=True, max_length=32, verbose_name=_('background color'))
    in_legend = models.BooleanField(default=False, verbose_name=_('show in legend (if color set)'))
    hub_import_type = models.CharField(max_length=100, verbose_name=_('hub import type'), null=True, blank=True,
                                       unique=True,
                                       help_text=_('import hub locations of this type as children of this location'))

    external_url_label = I18nField(_('external URL label'), plural_name='external_url_labels', blank=True,
                                   fallback_any=True, fallback_value="")
    external_url_labels: dict[str, str]

    load_group_contribute = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    # imported from locationgroup end

    parents = models.ManyToManyField("self", related_name="children", symmetrical=False,
                                              through="LocationTagAdjacency", through_fields=("child", "parent"))

    levels = models.ManyToManyField('Level', related_name="tags")
    spaces = models.ManyToManyField('Space', related_name="tags")
    areas = models.ManyToManyField('Area', related_name="tags")
    pois = models.ManyToManyField('POI', related_name="tags")

    # todo: move this into another model?
    cached_geometries: CachedGeometriesByLevel = SchemaField(schema=CachedGeometriesByLevel, null=True)
    cached_points: CachedLocationPoints = SchemaField(schema=CachedLocationPoints, null=True)
    cached_bounds: CachedBoundsByLevel = SchemaField(schema=CachedBoundsByLevel, null=True)
    cached_target_subtitles: CachedTitles = SchemaField(schema=CachedTitles, default=list)
    cached_all_static_targets: CachedLocationTargetIDs = SchemaField(schema=CachedLocationTargetIDs, default=list)
    cached_all_position_secrets: list[str] = SchemaField(schema=list[str], default=list)

    objects = LocationTagManager()

    class Meta:
        verbose_name = _('Location Tag')
        verbose_name_plural = _('Location Tags')
        default_related_name = 'location_tags'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deferred_fields = self.get_deferred_fields()
        self._orig = {
            key: getattr(self, key) for key in ("priority", "color") if key not in deferred_fields
        }

    @cached_property
    def effective_access_restrictions(self) -> AccessRestrictionsEval:
        if "effective_access_restriction_sets" not in getattr(self, '_prefetched_objects_cache', ()):
            raise ValueError("Can't provide LocationTag.effective_access_restrictions "
                             "without .with_restrictions() in Queryset")
        return AccessRestrictionsOr.build((
            AccessRestrictionsAllIDs.build(restriction.pk for restriction in restriction_set.access_restrictions.all())
            for restriction_set in self.effective_access_restriction_sets.all()
        ))

    """ Targets """

    @cached_property
    def static_targets(self) -> MapPermissionGuardedSequence[StaticLocationTagTarget]:
        """
        Get all static location targets
        """
        return MapPermissionGuardedSequence((
            *self.levels.all(),
            *self.spaces.all(),
            *self.areas.all(),
            *self.pois.all(),
        ))

    """ Main Properties """

    @cached_property
    def slug(self) -> str | None:
        try:
            return next(iter(locationslug.slug for locationslug in self.slug_set.all() if not locationslug.redirect))
        except StopIteration:
            return None

    @cached_property
    def redirect_slugs(self) -> set[str]:
        return set(locationslug.slug for locationslug in self.slug_set.all() if locationslug.redirect)

    @property
    def effective_slug(self):
        # todo: get rid of this
        return self.slug or str(self.pk)

    @property
    def add_search(self):
        return ' '.join((
            *self.redirect_slugs,
            *self.other_titles,
        ))

    def details_display(self, *, editor_url=True, **kwargs):
        result = {
            'id': self.pk,
            'display': [
                (_('Type'), str(self.__class__._meta.verbose_name)),
                (_('ID'), str(self.pk)),
                (_('Slug'), self.slug),
                *(
                    (_('Title ({lang})').format(lang=get_language_info(lang)['name_translated']), title)
                    for lang, title in sorted(self.titles.items(), key=lambda item: item[0] != get_language())
                ),
                (_('Parent tags'), list(self.display_superlocations)),
                (_('Access Restriction'), self.access_restriction_id and self.access_restriction.title),
                (_('searchable'), _('Yes') if self.can_search else _('No')),
                (_('can describe'), _('Yes') if self.can_describe else _('No')),
                (_('icon'), self.effective_icon),
            ]
        }
        if self.external_url:
            result['external_url'] = {
                'title': self.effective_external_url_label or _('Open external URL'),
                'url': self.external_url,
            }

        if grid.enabled:
            grid_square = self.grid_square
            if grid_square is not None:
                grid_square_title = (_('Grid Squares') if grid_square and '-' in grid_square else _('Grid Square'))
                result['display'].insert(3, (grid_square_title, grid_square or None))

        # todo: add groups again

        if editor_url:
            result['editor_url'] = reverse('editor.location_tags.edit', kwargs={'pk': self.pk})

        return result

    @cached_property
    def sublocations(self) -> MapPermissionGuardedTaggedSequence[int]:
        # todo: rename
        return MapPermissionGuardedTaggedSequence([
            MapPermissionTaggedItem(l.pk, l.effective_access_restrictions)
            for l in self.calculated_descendants.all()
        ])

    @cached_property
    def display_superlocations(self) -> MapPermissionGuardedTaggedSequence[dict]:
        # todo: rename?
        return MapPermissionGuardedTaggedSequence([
            MapPermissionTaggedItem({
                'id': l.pk,
                'slug': l.effective_slug,
                'title': l.title,  # todo: will translation be used here?
                'can_search': l.can_search,
            }, l.effective_access_restrictions)
            for l in self.calculated_ancestors.all()
        ])

    @cached_property
    def dynamic(self) -> int:
        return len(self.cached_all_position_secrets)

    @property
    def _has_inherited(self):
        with suppress(AttributeError):
            self.inherited
        return "inherited" in self._state.fields_cache

    @cached_property
    def effective_icon(self) -> str | None:
        if not self._has_inherited:  # todo: test that no inherited still works
            return self.icon
        return MapPermissionGuardedTaggedValue(self.inherited.icon, default=None).get()

    @cached_property
    def effective_label_settings_id(self) -> int | None:
        if not self._has_inherited:
            return self.label_settings_id
        return MapPermissionGuardedTaggedValue(self.inherited.label_settings_id, default=self.label_settings_id).get()

    @property
    def effective_external_url_labels(self) -> dict:
        if not self._has_inherited:
            return self.external_url_label
        return MapPermissionGuardedTaggedValue(self.inherited.external_url_label, default=self.external_url_labels).get()

    @cached_property
    def effective_external_url_label(self) -> str:
        # todo: remove duplicate code here
        if not self._has_inherited:
            return lazy_get_i18n_value(self.external_url_label,
                                       fallback_language=settings.LANGUAGE_CODE, fallback_any=True, fallback_value="")
        return lazy_get_i18n_value(
            lazy(MapPermissionGuardedTaggedValue(self.inherited.external_url_label,
                                                 default=self.external_url_labels).get, dict)(),
            fallback_language=settings.LANGUAGE_CODE, fallback_any=True, fallback_value=""
        )

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        if not self._has_inherited:
            return None
        color = MapPermissionGuardedTaggedValue(
            self.inherited.colors.get(color_manager.theme_id, {}), default=None
        ).get()
        return None if color is None else color.fill

    def get_color_sorted(self, color_manager: 'ThemeColorManager') -> tuple[int, str] | None:
        # todo: where is this used? get rid of it!
        color = self.get_color(color_manager)
        if color is None:
            return None
        return 0, color

    @property
    def describing_titles(self) -> dict:
        if not self._has_inherited:
            return {}
        return MapPermissionGuardedTaggedValue(self.inherited.describing_title, default={}).get()

    @cached_property
    def describing_title(self) -> str:
        # todo: remove duplicate code here
        if not self._has_inherited:
            return ""
        return lazy_get_i18n_value(
            lazy(MapPermissionGuardedTaggedValue(self.inherited.describing_title, default={}).get, dict)(),
            fallback_language=settings.LANGUAGE_CODE, fallback_any=True, fallback_value=""
        )

    @classmethod
    def q_for_permissions(cls, permissions: "MapPermissions", prefix=''):
        return (
            super().q_for_permissions(permissions, prefix) &
            (Q() if permissions.full else (
                #Q(effective_access_restriction_sets__isnull=True) | (
                (~Exists(LocationTagEffectiveAccessRestrictionSet.objects.filter(tag=OuterRef("pk")))) | (
                    Q() if not permissions.access_restrictions else
                    Exists(LocationTagEffectiveAccessRestrictionSet.objects.filter(
                        Q(tag=OuterRef("pk")) & ~Exists(
                            LocationTagEffectiveAccessRestrictionSet.access_restrictions.through.objects.filter(
                                locationtageffectiveaccessrestrictionset=OuterRef("pk")
                            ).exclude(accessrestriction__in=permissions.access_restrictions)
                        )
                    )
                ))
            ))
        )

    @cached_property
    def _all_static_target_ids(self) -> MapPermissionGuardedTaggedSequence[tuple[str, int]]:
        if not self.cached_all_static_targets:
            return MapPermissionGuardedTaggedSequence([])
        return MapPermissionGuardedTaggedSequence(self.cached_all_static_targets)


    """ Points / Bounds / Grid """

    @cached_property
    def _points(self) -> MapPermissionGuardedTaggedValueSequence[LocationPoint]:
        if not self.cached_points:
            return MapPermissionGuardedTaggedValueSequence([])
        return MapPermissionGuardedTaggedValueSequence([
            MapPermissionGuardedTaggedValue(points, default=None)
            for points in self.cached_points
        ])

    @property
    def points(self) -> list[LocationPoint]:
        return list(self._points)

    @property
    def dynamic_points(self) -> list[LocationPoint]:
        return list(filter(None,
            # todo: this needs to be cached
            (position.dynamic_point for position in Position.objects.filter(
                secret__in=self.cached_all_position_secrets
            ))
        ))

    @cached_property
    def _bounds(self) -> dict[int, LazyMapPermissionFilteredBounds]:
        return {
            level_id: LazyMapPermissionFilteredBounds(
                *(MapPermissionGuardedTaggedValue(item, default=None) for item in level_bounds)
            )
            for level_id, level_bounds in self.cached_bounds.items()
        }

    @property
    def bounds(self) -> BoundsByLevelSchema:
        if not self.cached_bounds:
            return {}
        return {
            level_id: tuple(batched((round(i, 2) for i in level_bounds), 2))
            for level_id, level_bounds in (
                # get bounds fo reach level
                (cached_level_id, tuple(item.get() for item in cached_level_bounds))
                for cached_level_id, cached_level_bounds in self._bounds.items()
            ) if not any((v is None) for v in level_bounds)
        }

    @property
    def dynamic_bounds(self) -> BoundsByLevelSchema:
        return merge_bounds(
            self.bounds,
            # todo: this needs to be cached
            *filter(None, (position.bounds for position in Position.objects.filter(
                secret__in=self.cached_all_position_secrets
            )))
        )

    @staticmethod
    def get_grid_square(*, bounds) -> GridSquare:
        # todo: move this outside of class?
        # todo: maybe only merge bounds if it's all in one level… but for multi-level rooms its nice! find solution?
        if not bounds:
            return ""
        zipped = tuple(zip(*(chain(*level_bounds) for level_bounds in bounds.values())))
        return grid.get_squares_for_bounds((min(zipped[0]), min(zipped[1]), max(zipped[2]), max(zipped[3])))

    @property
    def grid_square(self) -> GridSquare:
        return self.get_grid_square(bounds=self.bounds)

    @property
    def dynamic_grid_square(self) -> GridSquare:
        return self.get_grid_square(bounds=self.dynamic_bounds)

    @cached_property
    def _geometries_by_level(self) -> GeometriesByLevel:
        # todo: eventually include dynamic targets in here?
        if not self.cached_geometries:
            return {}
        return {
            level_id: MapPermissionGuardedTaggedValueSequence([
                (
                    MapPermissionMaskedTaggedValue[
                        MapPermissionGuardedTaggedValue[PolygonSchema | MultiPolygonSchema | PointSchema, None],
                    ](
                        value=MapPermissionGuardedTaggedValue(
                            [MapPermissionTaggedItem(shape(g.value), g.access_restrictions)
                             for g in geometries.geometry],
                            default=None
                        ),
                        masked_value=MapPermissionGuardedTaggedValue(
                            [MapPermissionTaggedItem(shape(g.value), g.access_restrictions)
                             for g in geometries.masked_geometry],
                            default=None),
                        space_id=geometries.space_id
                    )
                    if isinstance(geometries, MaskedLocationTagGeometry)
                    else MapPermissionMaskedTaggedValue(MapPermissionGuardedTaggedValue(
                        [MapPermissionTaggedItem(shape(g.value), g.access_restrictions)
                         for g in geometries],
                        default=None))
                )
                for geometries in level_geometries
            ])
            for level_id, level_geometries in self.cached_geometries.items()
        }

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        return {level_id: list(level_geometries) for level_id, level_geometries in self._geometries_by_level.items()}

    """ Subtitle """

    @cached_property
    def static_target_subtitle(self) -> str:
        return lazy_get_i18n_value(
            lazy(MapPermissionGuardedTaggedValue(self.cached_target_subtitles, default={}).get, dict)(),
            fallback_language=settings.LANGUAGE_CODE, fallback_any=True, fallback_value=""
        )

    @cached_property
    def dynamic_target_subtitle(self) -> str | None:
        static_target_subtitle = str(self.static_target_subtitle)
        if static_target_subtitle:
            return static_target_subtitle
        if not static_target_subtitle:
            # todo: this needs to be cached
            if len(self.cached_all_position_secrets) == 1:
                return Position.objects.filter(secret=self.cached_all_position_secrets[0]).dynamic_subtitle
        # todo: make this work better for multiple targets
        return None

    def _build_subtitle(self, *, target_subtitle: Optional[str], grid_square: GridSquare) -> str:
        # get subtitle from highest ranked describing group
        subtitle = str(self.describing_title) or None

        # add grid square if available
        if grid_square:
            subtitle = (
                format_lazy(_('{describing_group}, {grid_square}'),
                            describing_group=subtitle,
                            grid_square=self.grid_square)
                if subtitle else self.grid_square
            )

        # add subtitle from target(s)
        if target_subtitle:
            subtitle = (
                format_lazy(_('{subtitle}, {space_level_etc}'), subtitle=subtitle, space_level_etc=target_subtitle)
                if subtitle else target_subtitle
            )

        # fallback if there is no subtitle  # todo: this could probably be better?
        if subtitle is not None:
            return subtitle
        # todo: make tags invisible if all targets are invisible
        return (
            _('Location')
            if len(self._all_static_target_ids) + len(self.cached_all_position_secrets) <= 1
            else _('Locations')
        )

    @property
    def subtitle(self) -> str:
        try:
            return self._build_subtitle(
                target_subtitle=str(self.static_target_subtitle),
                grid_square=self.grid_square,
            )
        except:
            import traceback
            traceback.print_exc()
            raise

    @property
    def dynamic_subtitle(self) -> str:
        return self._build_subtitle(
            target_subtitle=self.dynamic_target_subtitle,
            grid_square=self.dynamic_grid_square,
        )

    """ Other Stuff """

    @property
    def dynamic_state(self) -> Optional[DynamicLocationState]:
        if not self.dynamic:
            return None
        return DynamicLocationState(
            subtitle=self.dynamic_subtitle,
            grid_square=self.dynamic_grid_square,
            dynamic_points=self.dynamic_points,
            bounds=self.dynamic_bounds,
            nearby=None,  # todo: add nearby information
        )

    """ Changed Geometries """

    def register_changed_geometries(self, force=False):
        # todo: maybe not just if force but also if some property changed?
        if force:
            # todo: targets need to be read correctly
            for target in self.static_targets:
                target.register_change(force=True)

    def pre_save_changed_geometries(self):
        if not self._state.adding and any(getattr(self, attname) != value for attname, value in self._orig.items()):
            self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        with transaction.atomic():
            super().save(*args, **kwargs)
            self._post_save((self.pk, ))

    @classmethod
    def _post_save(cls, pks: Iterable[int]):
        pass

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries(force=True)

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


class LocationTagEffectiveAccessRestrictionSet(models.Model):
    tag = models.ForeignKey(LocationTag, on_delete=models.CASCADE, related_name="effective_access_restriction_sets")
    access_restrictions = models.ManyToManyField("AccessRestriction", related_name="+")


class LocationTagInheritedValues(models.Model):
    tag = models.OneToOneField(LocationTag, on_delete=models.CASCADE, related_name="inherited")
    icon: CachedStrings = SchemaField(schema=CachedStrings, default=list)
    label_settings_id: CachedIDs = SchemaField(schema=CachedIDs, default=list)
    external_url_label: CachedTitles = SchemaField(schema=CachedTitles, default=list)
    describing_title: CachedTitles = SchemaField(schema=CachedTitles, default=list)
    colors: ColorByTheme = SchemaField(schema=ColorByTheme, default=dict)

    class Meta:
        verbose_name = _('Location Tag Inherited Values')
        verbose_name_plural = _('Location Tags Inherited Values')


class LocationTagTargetInheritedValues(models.Model):
    level = models.OneToOneField('Level', related_name="inherited", null=True, on_delete=models.CASCADE)
    space = models.OneToOneField('Space', related_name="inherited", null=True, on_delete=models.CASCADE)
    area = models.OneToOneField('Area', related_name="inherited", null=True, on_delete=models.CASCADE)
    poi = models.OneToOneField('POI', related_name="inherited", null=True, on_delete=models.CASCADE)
    tags: CachedIDs = SchemaField(schema=CachedIDs, default=list)

    class Meta:
        verbose_name = _('Location Tag Target Inherited Values')
        verbose_name_plural = _('Location Tag Targets Inherited Values')
        constraints = (
            CheckConstraint(check=(
                Q(level__isnull=False, space__isnull=True, area__isnull=True, poi__isnull=True)
                | Q(level__isnull=True, space__isnull=False, area__isnull=True, poi__isnull=True)
                | Q(level__isnull=True, space__isnull=True, area__isnull=False, poi__isnull=True)
                | Q(level__isnull=True, space__isnull=True, area__isnull=True, poi__isnull=False)
            ), name="target_inherited_values_has_unique_target"),
        )


class CircularHierarchyError(IntegrityError):
    pass


# todo: check which one of these are still needed


def locationtag_parents_removed(instance: LocationTag, pk_set: set[int]):
    """
    parents were removed from the location
    """
    # get removed adjacencies, this is why we do this before  … todo get rid of this. could we do it after then?
    #LocationTagRelation.objects.annotate(count=Count("paths")).filter(descendant_id=instance.pk, count=0).delete()

    # notify changed geometries… todo: this should definitely use the descendants thing
    instance.register_changed_geometries(force=True)


def locationtag_children_removed(instance: LocationTag, pk_set: set[int] = None):
    """
    children were removed from the location
    """
    if pk_set is None:
        # todo: this is a hack, can be done nicer… todo get rid of this anyways
        pass #pk_set = set(LocationTagRelation.objects.filter(ancestor_id=instance.pk).values_list("pk", flat=True))

    # todo: ged rid of this… could we do it after then?
    # LocationTagRelation.objects.annotate(count=Count("paths")).filter(ancestor_id=instance.pk, count=0).delete()

    # notify changed geometries… todo: this should definitely use the descendants thing
    for obj in LocationTag.objects.filter(pk__in=pk_set):
        obj.register_changed_geometries(force=True)


@receiver(m2m_changed, sender=LocationTag.levels.through)
@receiver(m2m_changed, sender=LocationTag.spaces.through)
@receiver(m2m_changed, sender=LocationTag.areas.through)
@receiver(m2m_changed, sender=LocationTag.pois.through)
def locationtag_targets_changed(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if not reverse:
        # the targets of a location tag were changed
        if action not in ('post_clear',):
            raise NotImplementedError
        query = model.objects.filter(pk__in=pk_set)
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        if issubclass(model, SpaceGeometryMixin):
            query = query.select_related('space')  # todo… ??? needed?
        for obj in query:
            obj.register_change(force=True)
    else:
        # the location tags of a target were changed
        instance.register_change(force=True)


class LocationTagTargetMixin(models.Model):
    class Meta:
        abstract = True

    @property
    def _has_inherited(self):
        with suppress(AttributeError):
            self.inherited
        return "inherited" in self._state.fields_cache

    @cached_property
    def sorted_tags(self) -> MapPermissionGuardedSequence[LocationTag]:
        """
        highest priority first
        """
        if "tags" not in getattr(self, '_prefetched_objects_cache', ()):
            raise ValueError(f'Accessing sorted_tags on {self} despite no prefetch_related.')
        if not self._has_inherited:
            raise ValueError(f'Accessing sorted_tags on {self} despite no select_related for inherited.')

        tags_by_id = {tag.pk: tag for tag in self.tags.all()}
        return MapPermissionGuardedSequence(
            tuple(tag for tag in (
                tags_by_id.get(tag_id) for tag_id in set(MapPermissionGuardedTaggedSequence(self.inherited.tags))
            ) if tag is not None)
        )

    @property
    def title(self) -> str:
        # todo: precalculate?
        return self.sorted_tags[0].title if self.sorted_tags else str(self)

    @property
    def subtitle(self):
        raise NotImplementedError

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        try:
            return next(iter(filter(None, (tag.get_color(color_manager) for tag in self.sorted_tags))))
        except StopIteration:
            return None

    def get_color_sorted(self, color_manager) -> tuple[int, str] | None:
        try:
            return next(iter(filter(None, (tag.get_color_sorted(color_manager) for tag in self.sorted_tags))))
        except StopIteration:
            return None

    def get_location(self, can_describe=False) -> Optional[LocationTag]:
        # todo: do we want to get rid of this?
        return next(iter((*(tag for tag in self.sorted_tags if tag.can_describe), None)))


CachedEffectiveGeometries = list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema]]


class LabelSettings(models.Model):
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    min_zoom = models.DecimalField(_('min zoom'), max_digits=3, decimal_places=1, default=-10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    max_zoom = models.DecimalField(_('max zoom'), max_digits=3, decimal_places=1, default=10,
                                   validators=[MinValueValidator(Decimal('-10')),
                                               MaxValueValidator(Decimal('10'))])
    font_size = models.IntegerField(_('font size'), default=12,
                                    validators=[MinValueValidator(12),
                                                MaxValueValidator(30)])

    class Meta:
        verbose_name = _('Label Settings')
        verbose_name_plural = _('Label Settings')
        default_related_name = 'labelsettings'
        ordering = ('min_zoom', '-font_size')


class LoadGroup(models.Model):
    name = models.CharField(_('Name'), unique=True, max_length=50)  # a slugfield would forbid periods

    @property
    def title(self):
        return self.name

    class Meta:
        verbose_name = _('Load group')
        verbose_name_plural = _('Load groups')
        default_related_name = 'labelgroup'


class DynamicLocationTagTarget(LocationTagTargetMixin, models.Model):
    tag = models.ForeignKey("LocationTag", null=True, on_delete=models.CASCADE, related_name="dynamic_targets")
    position_secret = models.CharField(_('position secret'), max_length=32)

    class Meta:
        verbose_name = _("Dynamic location tag target")
        verbose_name_plural = _("Dynamic location tag targets")
        default_related_name = "dynamic_location_tag_targets"


def get_position_secret():
    return get_random_string(32, string.ascii_letters+string.digits)


class Position(models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.LocationProtocol`.
    """
    objects = None
    locationtype = "position"
    slug_as_id = True

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    name = models.CharField(_('name'), max_length=32)
    short_name = models.CharField(_('abbreviation'), help_text=_('two characters maximum'), max_length=2)
    secret = models.CharField(_('secret'), unique=True, max_length=32, default=get_position_secret)
    last_coordinates_update = models.DateTimeField(_('last coordinates update'), null=True)
    timeout = models.PositiveSmallIntegerField(_('timeout (in seconds)'), default=0, blank=True,
                                               help_text=_('0 for no timeout'))
    coordinates_id = models.CharField(_('coordinates'), null=True, blank=True, max_length=48)

    coordinates: "CustomLocation" = LocationById()

    dynamic = 1
    subtitle = _('Position')
    effective_icon = "my_location"
    grid_square = None

    can_search = True
    can_describe = False

    geometries_by_level = {}

    class Meta:
        verbose_name = _('Dynamic position')
        verbose_name_plural = _('Dynamic position')
        default_related_name = 'dynamic_positions'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.timeout and self.last_coordinates_update:
            end_time = self.last_coordinates_update + timedelta(seconds=self.timeout)
            if timezone.now() >= end_time:
                self.coordinates = None
                self.last_coordinates_update = end_time

    @property
    def slug(self):
        return 'm:%s' % self.secret

    @property
    def effective_slug(self):
        return self.slug

    @property
    def title(self):
        return self.name

    @property
    def dynamic_subtitle(self):
        custom_location = self.coordinates
        if not custom_location:
            return _('currently unavailable')
        return '%s, %s, %s' % (
            _('Position'),
            custom_location.title,
            custom_location.subtitle,
        )

    @property
    def dynamic_grid_square(self):
        custom_location = self.coordinates
        if not custom_location:
            return None
        return custom_location.grid_square

    @property
    def dynamic_bounds(self):
        custom_location = self.coordinates
        if not custom_location:
            return None
        return custom_location.bounds

    @property
    def dynamic_point(self) -> Optional[LocationPoint]:
        custom_location = self.coordinates
        if not custom_location:
            return None
        return custom_location.point

    @property
    def dynamic_state(self) -> DynamicLocationState:
        custom_location = self.coordinates
        if not custom_location:
            return DynamicLocationState(
                subtitle=_('currently unavailable'),
                grid_square=None,
                dynamic_points=[],
                bounds={},
                nearby=None,
            )
        return DynamicLocationState(
            subtitle='%s, %s, %s' % (
                _('Position'),
                custom_location.title,
                custom_location.subtitle,
            ),
            grid_square=custom_location.grid_square,
            dynamic_points=[self.dynamic_point],
            bounds=custom_location.bounds,
            nearby=custom_location.nearby,
        )

    @property
    def points(self):
        return []

    @classmethod
    def user_has_positions(cls, user):
        if not user.is_authenticated:
            return False
        cache_key = 'user_has_positions:%d' % user.pk
        result = per_request_cache.get(cache_key, None)
        if result is None:
            result = cls.objects.filter(owner=user).exists()
            per_request_cache.set(cache_key, result, 600)
        return result

    # todo: expose short_name again somehow

    def details_display(self, **kwargs):
        return {
            'id': self.pk,
            'display': [
                (_('Type'), self.__class__._meta.verbose_name),
                (_('ID'), str(self.pk)),
                (_('Title'), self.name),
                (_('Slug'), self.slug),
                (_('searchable'), _('No')),
                (_('can describe'), _('No')),
                (_('icon'), None),
            ],
        }

    def save(self, *args, **kwargs):
        with transaction.atomic():
            super().save(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            super().delete(*args, **kwargs)
            transaction.on_commit(lambda: cache.delete('user_has_positions:%d' % self.owner_id))
