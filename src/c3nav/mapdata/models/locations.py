import string
import warnings
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from itertools import chain, batched, product, groupby
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, Optional, TypeAlias, Union, Sequence, NewType, NamedTuple, Iterator

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.aggregates import Min, Count
from django.db.models.constraints import CheckConstraint, UniqueConstraint
from django.db.models.expressions import Window, F, OuterRef, Subquery, When, Case, Value, Exists
from django.db.models.functions.window import RowNumber
from django.db.models.lookups import EndsWith
from django.db.models.query import Prefetch
from django.db.models.signals import m2m_changed
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils import translation
from django.utils.crypto import get_random_string
from django.utils.functional import cached_property, lazy
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, get_language, get_language_info
from django.utils.translation import ngettext_lazy
from django_pydantic_field import SchemaField

from c3nav.api.schema import GeometriesByLevelSchema, PolygonSchema, MultiPolygonSchema, GeometriesByLevel, PointSchema
from c3nav.mapdata.fields import I18nField, lazy_get_i18n_value
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin, UseQForPermissionsManager
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.base import CachedBounds, LazyMapPermissionFilteredBounds
from c3nav.mapdata.permissions import LazyMapPermissionFilteredSequence, MapPermissionTaggedItem, \
    MapPermissionGuardedTaggedValue, MapPermissionGuardedTaggedValueSequence, \
    MapPermissionsMaskedTaggedValue, MapPermissionGuardedTaggedSequence
from c3nav.mapdata.schemas.locations import GridSquare, DynamicLocationState
from c3nav.mapdata.schemas.model_base import BoundsSchema, LocationPoint, BoundsByLevelSchema, \
    DjangoCompatibleLocationPoint
from c3nav.mapdata.utils.cache.proxied import per_request_cache
from c3nav.mapdata.utils.fields import LocationById
from c3nav.mapdata.utils.geometry import merge_bounds

if TYPE_CHECKING:
    from c3nav.mapdata.render.theme import ThemeColorManager  # noqa
    from c3nav.mapdata.models import Level, Space, Area, POI
    from c3nav.mapdata.locations import CustomLocation


validate_slug = RegexValidator(
    r'^[a-z0-9-]*[a-z]+[a-z0-9-]*\Z',
    # Translators: "letters" means latin letters: a-z and A-Z.
    _('Enter a valid location slug consisting of lowercase letters, numbers or hyphens, with at least one letter.'),
    'invalid'
)


class LocationSlug(models.Model):
    slug = models.SlugField(_('Slug'), unique=True, max_length=50, validators=[validate_slug])
    redirect = models.BooleanField(default=False)
    target = models.ForeignKey('SpecificLocation', on_delete=models.CASCADE, related_name='slug_set')

    class Meta:
        verbose_name = _('Location Slug')
        verbose_name_plural = _('Location Slug')
        default_related_name = 'locationslugs'

        constraints = [
            models.UniqueConstraint(fields=["target"], condition=Q(redirect=False),
                                    name="unique_non_redirect_slugs")
        ]


class Location(AccessRestrictionMixin, TitledMixin, models.Model):
    # todo: merge this into SpecificLocation
    can_search = models.BooleanField(default=True, verbose_name=_('can be searched'))
    can_describe = models.BooleanField(default=True, verbose_name=_('can describe'))
    icon = models.CharField(_('icon'), max_length=32, null=True, blank=True, help_text=_('any material icons name'))
    external_url = models.URLField(_('external URL'), null=True, blank=True)

    class Meta:
        abstract = True

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
    def add_search(self):
        return ' '.join((
            *self.redirect_slugs,
            *self.other_titles,
        ))

    def details_display(self, **kwargs):
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
        return result

    @property
    def effective_slug(self):
        return self.slug or str(self.pk)

    @property
    def subtitle(self):
        return ''

    @property
    def grid_square(self):
        return None

    @property
    def effective_icon(self):
        return self.icon or None

    @property
    def external_url_label(self):
        return None


# class SpecificLocationManager(models.Manager):
#     def get_queryset(self):
#         return super().get_queryset().select_related(
#             'level', 'space', 'area', 'poi', 'dynamiclocation'
#         )  # .prefetch_related('slug_set')  # todo: put this back in?


possible_specific_locations = ('level', 'space', 'area', 'poi', 'dynamiclocation')  # todo: can we generate this?


StaticLocationTarget: TypeAlias = Union["Level", "Space", "Area", "POI"]
LocationTarget: TypeAlias = Union["DynamicLocationTarget", "StaticLocationTarget"]


@dataclass(frozen=True)
class FillAndBorderColor:
    fill: str | None
    border: str | None


ColorByTheme: TypeAlias = dict[int, FillAndBorderColor]
CachedTitles: TypeAlias = list[MapPermissionTaggedItem[dict[str, str]]]
CachedLocationTargetIDs: TypeAlias = list[MapPermissionTaggedItem[tuple[str, int]]]

TaggedLocationGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema | PointSchema]]
TaggedMaskedLocationGeometries: TypeAlias = list[MapPermissionTaggedItem[PolygonSchema]]


@dataclass(frozen=True)
class MaskedLocationGeometry:
    geometry: TaggedLocationGeometries
    masked_geometry: TaggedMaskedLocationGeometries
    space_id: int


CachedBoundsByLevel: TypeAlias = dict[int, CachedBounds]
CachedGeometriesByLevel: TypeAlias = dict[int, list[MaskedLocationGeometry | TaggedLocationGeometries]]
CachedLocationPoints: TypeAlias = list[list[MapPermissionTaggedItem[DjangoCompatibleLocationPoint]]]


class LocationParentage(models.Model):
    """
    A direct parent-child-relationship between two locations.
    """
    parent = models.ForeignKey("SpecificLocation", on_delete=models.PROTECT, related_name="+")
    child = models.ForeignKey("SpecificLocation", on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = (
            UniqueConstraint(fields=("parent", "child"), name="unique_location_parent_child"),
            CheckConstraint(check=~Q(parent=F("child")), name="location_parent_cant_be_child"),
        )


class LocationAncestry(models.Model):
    """ Automatically populated. Indicating that there is (at least) one ancestry between two locations """
    ancestor = models.ForeignKey("SpecificLocation", on_delete=models.CASCADE, related_name="+")
    descendant = models.ForeignKey("SpecificLocation", on_delete=models.CASCADE, related_name="+")

    # look, this field is genuinely just for fun, cause we can, probably not useful
    first_parentages = models.ManyToManyField("LocationParentage", related_name="provides_ancestries",
                                              through="LocationAncestryPath")

    class Meta:
        constraints = (
            # todo: wouldn't it be nice to actual declare multi-field foreign key constraints here, manually?
            UniqueConstraint(fields=("ancestor", "descendant"), name="unique_location_ancestry"),
            CheckConstraint(check=~Q(ancestor=F("descendant")), name="no_circular_location_ancestry"),
        )


class LocationAncestryPath(models.Model):
    """ Automatically populated. One ancestry path for the given ancestry, ending with the given parentage. """
    prev_path = models.ForeignKey("self", on_delete=models.CASCADE, related_name="+", null=True)
    parentage = models.ForeignKey("LocationParentage", on_delete=models.CASCADE, related_name="+")
    ancestry = models.ForeignKey("LocationAncestry", on_delete=models.PROTECT, related_name="paths")
    num_hops = models.PositiveSmallIntegerField()

    class Meta:
        constraints = (
            # todo: wouldn't it be nice to actual declare multi-field foreign key constraints here, manually?
            UniqueConstraint(fields=("prev_path", "parentage"), name="ancestry_path_unique_prev_path_parentage"),
            UniqueConstraint(fields=("prev_path", "ancestry"), name="ancestry_path_unique_prev_path_ancestry"),
            CheckConstraint(check=Q(prev_path__isnull=True, num_hops=0) |
                                  Q(prev_path__isnull=False, num_hops__gt=0), name="ancestry_path_enforce_num_hops"),
        )


class LocationAncestryPathTuple(NamedTuple):
    prev: Optional["LocationAncestryPathTuple"]
    ancestor: int | None
    parent: int
    location: int
    num_hops: int


class SpecificLocation(Location, models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.ListedLocationProtocol`.
    """
    locationtype = "specificlocation"
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

    # todo: get rid of this
    groups = models.ManyToManyField('mapdata.LocationGroup', verbose_name=_('Location Groups'), blank=True)
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'))
    label_override = I18nField(_('Label override'), plural_name='label_overrides', blank=True, fallback_any=True)
    import_block_data = models.BooleanField(_('don\'t change metadata on import'), default=False)
    import_block_geom = models.BooleanField(_('don\'t change geometry on import'), default=False)

    load_group_display = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                           related_name='+', verbose_name=_('display load group'))

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

    load_group_contribute = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    # imported from locationgroup end

    parents = models.ManyToManyField("self", related_name="children", symmetrical=False,
                                     through="LocationParentage", through_fields=("child", "parent"))
    calculated_ancestors = models.ManyToManyField("self", related_name="calculated_descendants", symmetrical=False,
                                                  through="LocationAncestry", through_fields=("descendant", "ancestor"),
                                                  editable=False)

    levels = models.ManyToManyField('Level', related_name='locations')
    spaces = models.ManyToManyField('Space', related_name='locations')
    areas = models.ManyToManyField('Area', related_name='locations')
    pois = models.ManyToManyField('POI', related_name='locations')

    effective_depth_first_order = models.PositiveIntegerField(default=2**31-1, editable=False)
    effective_priority_order = models.PositiveIntegerField(default=2**31-1, editable=False)
    effective_traversal_order = models.PositiveIntegerField(default=2**31-1, editable=False)

    effective_icon = models.CharField(_('icon'), max_length=32, null=True, editable=False)
    effective_label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, editable=False,
                                                 related_name='+', on_delete=models.CASCADE)
    effective_external_url_label = I18nField(_('external URL label'), null=True, editable=False,
                                             fallback_any=True, fallback_value="",
                                             plural_name='effective_external_url_labels')
    cached_effective_colors: ColorByTheme = SchemaField(schema=ColorByTheme, default=dict)
    cached_describing_titles: CachedTitles = SchemaField(schema=CachedTitles, default=list)

    cached_geometries: CachedGeometriesByLevel = SchemaField(schema=CachedGeometriesByLevel, null=True)
    cached_points: CachedLocationPoints = SchemaField(schema=CachedLocationPoints, null=True)
    cached_bounds: CachedBoundsByLevel = SchemaField(schema=CachedBoundsByLevel, null=True)
    cached_target_subtitles: CachedTitles = SchemaField(schema=CachedTitles, default=list)
    cached_all_static_targets: CachedLocationTargetIDs = SchemaField(schema=CachedLocationTargetIDs, default=list)
    cached_all_position_secrets: list[str] = SchemaField(schema=list[str], default=list)

    sublocations = []

    class Meta:
        verbose_name = _('Specific Location')
        verbose_name_plural = _('Specific Locations')
        default_related_name = 'specific_locations'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    """ Targets """

    @cached_property
    def static_targets(self) -> LazyMapPermissionFilteredSequence[StaticLocationTarget]:
        """
        Get all static location targets
        """
        return LazyMapPermissionFilteredSequence((
            *self.levels.all(),
            *self.spaces.all(),
            *self.areas.all(),
            *self.pois.all(),
        ))

    """ Main Properties """

    @cached_property
    def dynamic(self) -> int:
        return len(self.cached_all_position_secrets)

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        self.cached_effective_colors.get(color_manager.theme_id, None)

    def get_color_sorted(self, color_manager: 'ThemeColorManager') -> tuple[int, str] | None:
        # don't filter in the query here so prefetch_related works
        # todo: this still needs updating
        color = self.get_color(color_manager)
        if color is None:
            return None
        return self.effective_priority_order, color

    @classmethod
    def evaluate_location_ancestry(cls):
        build_children_by_parent: dict[int | None, deque[int]] = defaultdict(deque)
        parentage_ids: dict[tuple[int, int], int] = {}
        for pk, parent_id, child_id in LocationParentage.objects.values_list("pk", "parent_id", "child_id"):
            parentage_ids[(parent_id, child_id)] = pk
            build_children_by_parent[parent_id].append(child_id)
        children_by_parent: dict[int | None, frozenset[int]] = {
            parent_id: frozenset(children_ids) for parent_id, children_ids in build_children_by_parent.items()
        }

        fail = False

        # create ancestors
        expected_paths: dict[int, tuple[LocationAncestryPathTuple, ...]] = {}
        num_hops = 0
        last_paths: tuple[LocationAncestryPathTuple, ...] = tuple(chain.from_iterable(
            (
                LocationAncestryPathTuple(ancestor=parent_id, parent=parent_id, location=child_id,
                                          prev=None, num_hops=0)
                for child_id in child_ids
            ) for parent_id, child_ids in children_by_parent.items()
        ))
        while last_paths:
            paths_by_cyclic = {cyclic: tuple(paths)
                               for cyclic, paths in groupby(last_paths, key=lambda p: p.ancestor == p.location)}
            for path in paths_by_cyclic.get(True, ()):
                print(f"INCONSISTENCY! Circular hierarchy! Breaking parent→child {path.parent}→{path.location}")
                fail = True
            last_paths = paths_by_cyclic.get(False, ())
            expected_paths[num_hops] = last_paths

            num_hops += 1
            last_paths = tuple(chain.from_iterable(
                (
                    LocationAncestryPathTuple(ancestor=prev.ancestor, parent=prev.location, location=child_id,
                                              prev=prev, num_hops=num_hops)
                    for child_id in child_ids
                ) for prev, child_ids in zip(last_paths, (children_by_parent.get(path.location, frozenset()) for path in last_paths))
            ))

        expected_ancestries = {(path.ancestor, path.location) for path in chain.from_iterable(expected_paths.values())}
        ancestry_ids = {
            (ancestor_id, descendant_id): pk
            for pk, ancestor_id, descendant_id in LocationAncestry.objects.values_list("pk", "ancestor_id", "descendant_id")
        }
        existing_ancestries = set(ancestry_ids.keys())

        missing_ancestries = expected_ancestries - existing_ancestries
        if missing_ancestries:
            print("INCONSISTENCY: Missing ancestries, creating:", missing_ancestries)
            fail = True
            ancestry_ids.update({
                ancestry.pk: (ancestry.ancestor_id, ancestry.descendant_id)
                for ancestry in LocationAncestry.objects.bulk_create((
                    LocationAncestry(
                        ancestor_id=ancestor_id,
                        descendant_id=descendant_id,
                    ) for ancestor_id, descendant_id in missing_ancestries
                ))
            })

        extra_ancestries = existing_ancestries - expected_ancestries
        if extra_ancestries:
            print("INCONSISTENCY: Extra ancestries, deleting:", missing_ancestries)
            fail = True
            LocationAncestry.objects.filter(
                pk__in=(ancestry_ids[extra_ancestry] for extra_ancestry in extra_ancestries)
            ).delete()
            for extra_ancestry in missing_ancestries:
                del ancestry_ids[extra_ancestry]

        num_deleted, num_deleted_per_model = LocationAncestryPath.objects.exclude(
            # exclude things where things make sense
            Q(parentage__child=F("ancestry__descendant")) & (
                (Q(prev_path__isnull=True) | (Q(parentage__parent=F("prev_path__parentage__child"))
                                              & Q(ancestry__ancestor=F("prev_path__ancestry__ancestor"))
                                              & Q(num_hops=F("prev_path__num_hops")+1)))
                | (Q(prev_path__isnull=False) | Q(parentage__parent=F("ancestry__ancestor")))
            )
        ).delete()
        if num_deleted:
            print("INCONSISTENCY: Invalid paths that don't fit modeling constraints, deleting", num_deleted, "of them")
            fail = True

        existing_paths_by_id = {
            pk: fields for pk, *fields in LocationAncestryPath.objects.values_list(
                "pk", "prev_path_id", "ancestry__ancestor_id",
                "parentage__parent_id", "parentage__child_id", "num_hops",
            )
        }
        existing_paths_by_num_hops_and_id: dict[int, dict[int, LocationAncestryPathTuple]] = {}
        existing_path_id_by_tuple: dict[LocationAncestryPathTuple | None, int | None] = {None: None}

        for num_hops, paths in (
            sorted(groupby(existing_paths_by_id.items(), key=lambda p: p[1][4]))
        ):
            # todo: walrus operator?
            num_hops_paths = {}
            existing_paths_by_num_hops_and_id[num_hops] = num_hops_paths

            last_num_hops_paths = {} if num_hops == 0 else existing_paths_by_num_hops_and_id.get(num_hops - 1, {})

            for pk, (prev_path_id, ancestor_id, parent_id, child_id, n) in paths:
                t = LocationAncestryPathTuple(
                    prev=None if prev_path_id is None else last_num_hops_paths[prev_path_id],
                    ancestor=ancestor_id,
                    parent=parent_id,
                    location=child_id,
                    num_hops=num_hops,
                )
                num_hops_paths[pk] = t
                existing_path_id_by_tuple[t] = pk

        delete_ids: deque[int] = deque()

        max_num_hops = max(chain(existing_paths_by_num_hops_and_id.keys(), expected_paths.keys()))
        for num_hops in range(max_num_hops+1):
            existing_paths_for_hops = frozenset(existing_paths_by_num_hops_and_id.get(num_hops, {}).values())
            expected_paths_for_hops = frozenset(expected_paths.get(num_hops, ()))

            missing_paths = tuple(expected_paths_for_hops - existing_paths_for_hops)
            if missing_ancestries:
                print("INCONSISTENCY: Missing paths, creating:", missing_paths)
                fail = True
                existing_path_id_by_tuple.update(
                    dict(zip(missing_paths, (created_path.pk for created_path in LocationAncestryPath.objects.bulk_create((
                        LocationAncestryPath(
                            prev_path=existing_path_id_by_tuple[missing_path.prev],
                            parentage=parentage_ids[(missing_path.parent, missing_path.location)],
                            ancestry=ancestry_ids[(missing_path.ancestor, missing_path.location)],
                            num_hops=num_hops,
                        ) for missing_path in missing_paths
                    )))))
                )

            extra_paths = existing_paths_for_hops - expected_paths_for_hops
            if extra_ancestries:
                print("INCONSISTENCY: Extra paths, deleting:", extra_paths)
                delete_ids.extend(existing_path_id_by_tuple[extra_path] for extra_path in extra_paths)
                fail = True

        if delete_ids:
            LocationAncestryPath.objects.filter(pk__in=delete_ids).delete()

        if fail:
            raise ValueError("verify_location_ancestry failed")

        print("location ancestry valid")

        cls.recalculate_effective_order()

    @classmethod
    def recalculate_effective_order(cls):
        pks, priorities, num_parents = zip(
            *SpecificLocation.objects.annotate(
                Count("parents")
            ).values_list("pk", "priority", "parents__count").order_by("-priority")
        )
        root_location_ids = tuple(pk for pk, parents in zip(pks, num_parents) if parents == 0)

        children_for_parent = {
            parent_id: tuple(child_id for p, child_id in children)
            for parent_id, children in groupby(
                LocationParentage.objects.order_by("-child__priority").values_list("parent_id", "child_id"),
                key=itemgetter(1)
            )
        }

        # depth first
        locations_in_depth_first_order: deque[int] = deque(root_location_ids)
        done_locations: set[int] = set()
        next_locations: deque[int] = deque(root_location_ids)
        while next_locations:
            location_id = next_locations.popleft()
            new_children = tuple(child_id for child_id in children_for_parent.get(location_id, ())
                                 if child_id not in done_locations)
            done_locations.update(new_children)
            next_locations.extend(new_children)
            locations_in_depth_first_order.extend(new_children)

        # priority first
        locations_in_traversal_order: deque[int] = deque()
        locations_in_priority_order: deque[int] = deque()
        done_locations.clear()
        def add_locations(ids: tuple[int, ...]):
            for id_ in ids:
                if id_ in done_locations:
                    continue
                done_locations.add(id_)
                locations_in_traversal_order.append(id_)
                add_locations(children_for_parent.get(id_, ()))
                locations_in_priority_order.append(id_)

        field = models.PositiveIntegerField()
        for order_name, location_ids in (("depth_first", locations_in_depth_first_order),
                                         ("traversal", locations_in_traversal_order),
                                         ("priority", locations_in_priority_order)):
            SpecificLocation.objects.update(**{f"effective_{order_name}_order": Case(
         *(
                    When(pk=location_id, then=Value(i, output_field=field))
                    for i, location_id in enumerate(location_ids)
                ),
                default=Value(2**31-1, output_field=field),
            )})

    @classmethod
    def calculate_effective_x(cls, name: str, default=...):
        output_field = cls._meta.get_field(f"effective_{name}")
        cls.objects.annotate(**{
            f"parent_effective_{name}": Subquery(SpecificLocation.objects.filter(**{
                "calculated_descendants": OuterRef("pk"),
                f"{name}__isnull": False,
            }).order_by("effective_priority_order").values(name)[:1]),
            f"new_effective_{name}": (
                Case(When(**{f"{name}__isnull": False}, then=F(name)),
                     When(**{f"parent_effective_{name}__isnull": False}, then=F(f"parent_effective_{name}")),
                     default=F(f"{name}") if default is ... else Value(default, output_field=output_field),
                     output_field=output_field)
            )
        }).update(**{f"effective_{name}": F(f"new_effective_{name}")})

    @classmethod
    def _bulk_cached_update[T](cls, name: str, values: Sequence[tuple[set[int], T]], default: T):
        output_field = cls._meta.get_field(f"cached_{name}")
        cls.objects.annotate(
            **{f"new_{name}": Case(
                *(When(pk__in=pks, then=Value(value, output_field=output_field)) for pks, value in values),
                default=Value(default, output_field=output_field),
            )}
        ).update(**{f"cached_{name}": F(f"new_{name}")})

    @classmethod
    def calculate_cached_effective_color(cls):
        # collect ids for each value so we can later bulk-update
        colors: dict[tuple[tuple[int, FillAndBorderColor], ...], set[int]] = {}
        for specific_location in cls.objects.prefetch_related(
                Prefetch("calculated_ancestors", SpecificLocation.objects.order_by(
                    "effective_priority_order"
                ).prefetch_related("theme_colors"))
            ):
            location_colors: ColorByTheme = {}
            for ancestor in chain((specific_location, ), specific_location.calculated_ancestors.all()):
                # add colors from this ancestor
                if ancestor.color and 0 not in location_colors:
                    location_colors[0] = FillAndBorderColor(fill=ancestor.color, border=None)
                location_colors.update({
                    theme_color.theme_id: FillAndBorderColor(fill=theme_color.fill_color,
                                                             border=theme_color.border_color)
                    for theme_color in ancestor.theme_colors.all()
                    if (theme_color.theme_id not in location_colors
                        and theme_color.fill_color and theme_color.border_color)
                })
            colors.setdefault(tuple(sorted(location_colors.items())), set()).add(specific_location.pk)

        cls._bulk_cached_update(
            name="effective_colors",
            values=tuple((pks, dict(colors)) for colors, pks in colors.items()),
            default={}
        )

    @classmethod
    def calculate_cached_describing_titles(cls):
        all_describing_titles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
        for specific_location in cls.objects.prefetch_related(
                Prefetch("calculated_ancestors", SpecificLocation.objects.order_by("effective_priority_order"))
            ):
            location_describing_titles: list[tuple[tuple[tuple[str, str], ...], frozenset[int]]] = []
            for group in reversed(specific_location.groups.all()):
                if not (group.can_describe and group.titles):
                    continue
                restrictions: frozenset[int] = (
                    frozenset((group.access_restriction_id,)) if group.access_restriction_id else frozenset()
                )
                titles: tuple[tuple[str, str], ...] = tuple(group.titles.items())  # noqa
                if not restrictions or all((restrictions-other_restrictions)
                                           for titles, other_restrictions in location_describing_titles):
                    # new restriction set was not covered by previous ones
                    location_describing_titles.append((titles, restrictions))
                if not restrictions:
                    # no access restrictions? that's it, no more groups to evaluate
                    break
            all_describing_titles.setdefault(tuple(location_describing_titles), set()).add(specific_location.pk)
        cls._bulk_cached_update(
            name="describing_titles",
            values=tuple(
                (pks, [
                    MapPermissionTaggedItem(value=dict(titles), access_restrictions=restrictions)
                    for titles, restrictions in entries
                ]) for entries, pks in all_describing_titles.items()
            ),
            default=[]
        )

    @classmethod
    def recalculate_cached_from_parents(cls):
        cls.calculate_effective_x("icon")
        cls.calculate_effective_x("external_url_labels", "{}")
        cls.calculate_effective_x("label_settings")

        cls.calculate_cached_effective_color()
        cls.calculate_cached_describing_titles()

    @cached_property
    def describing_title(self) -> str:
        return lazy_get_i18n_value(
            lazy(MapPermissionGuardedTaggedValue(self.cached_describing_titles, default={}).get, dict)(),
            fallback_language=settings.LANGUAGE_CODE, fallback_any=True, fallback_value=""
        )

    @classmethod
    def recalculate_all_static_targets(cls):
        all_static_target_ids: dict[tuple[tuple[tuple[str, int], frozenset[int]], ...], set[int]] = {}
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            all_static_target_ids.setdefault(tuple(sorted(
                ((target._meta.model_name, target.pk), target.effective_access_restrictions)
                for target in obj.static_targets
            )), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="all_static_targets",
            values=tuple(
                (pks, [
                    MapPermissionTaggedItem(value=value, access_restrictions=restrictions)
                    for value, restrictions in entries
                ]) for entries, pks in all_static_target_ids.items()
            ),
            default=[]
        )

    @cached_property
    def _all_static_target_ids(self) -> MapPermissionGuardedTaggedSequence[tuple[str, int]]:
        if not self.cached_all_static_targets:
            return MapPermissionGuardedTaggedSequence([])
        return MapPermissionGuardedTaggedSequence(self.cached_all_static_targets)

    @classmethod
    def recalculate_all_position_secrets(cls):
        all_position_secrets: dict[tuple[str, ...], set[int]] = {}

        for obj in cls.objects.prefetch_related("dynamic_location_targets"):
            all_position_secrets.setdefault(tuple(sorted(
                target.position_secret for target in obj.dynamic_location_targets.all()
            )), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="all_position_secrets",
            values=tuple((pks, list(secrets)) for secrets, pks in all_position_secrets.items()),
            default=[]
        )

    """ Points / Bounds / Grid """

    @classmethod
    def recalculate_points(cls):
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            obj: SpecificLocation
            obj.cached_points = [
                # we are filtering out versions of this targets points for users who lack certain permissions,
                list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                    (MapPermissionTaggedItem( # add primary level to turn the xy coordinates into a location point
                        value=(target.primary_level_id, *item.value),
                        access_restrictions=item.access_restrictions
                    ) for item in target.cached_points),
                    access_restrictions=obj.effective_access_restrictions,
                )) for target in obj.static_targets
            ]
            obj.save()

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

    @classmethod
    def recalculate_bounds(cls):
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            obj: SpecificLocation
            # collect the cached bounds of all static targets, grouped by level
            collected_bounds: dict[int, deque[CachedBounds]] = defaultdict(deque)
            for target in obj.static_targets:
                collected_bounds[target.primary_level_id].append(target.cached_bounds)

            result: CachedBoundsByLevel = {}
            for level_id, collected_level_bounds in collected_bounds.items():
                result[level_id] = CachedBounds(*(
                    list(MapPermissionTaggedItem.skip_redundant(values, reverse=(i > 1)))  # sort reverse for maxx/maxy
                    # zip the collected bounds into 4 iterators of tagged items
                    for i, values in enumerate(chain(*items) for items in zip(*collected_level_bounds))
                ))
            obj.cached_bounds = result
            obj.save()

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

    @classmethod
    def recalculate_geometries(cls):
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            result: CachedGeometriesByLevel = {}
            for target in obj.static_targets:
                try:
                    mask = not target.base_mapdata_accessible
                except AttributeError:
                    mask = False
                # we are filtering out versions of this target's geometries for users who lack certain permissions,
                # because being able to see this location implies certain permissions
                if mask:
                    result.setdefault(target.primary_level_id, []).append(MaskedLocationGeometry(
                        geometry=list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_effective_geometries, obj.effective_access_restrictions
                        )),
                        masked_geometry=list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_simplified_geometries, obj.effective_access_restrictions
                        )),
                        space_id=target.id,
                    ))
                else:
                    result.setdefault(target.primary_level_id, []).append(
                        list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_effective_geometries, obj.effective_access_restrictions
                        ))
                    )
            obj.cached_geometries = result
            obj.save()

    @cached_property
    def _geometries_by_level(self) -> GeometriesByLevel:
        # todo: eventually include dynamic targets in here?
        if not self.cached_geometries:
            return {}
        return {
            level_id: MapPermissionGuardedTaggedValueSequence([
                (
                    MapPermissionsMaskedTaggedValue[
                        MapPermissionGuardedTaggedValue[PolygonSchema | MultiPolygonSchema | PointSchema, None],
                    ](
                        value=MapPermissionGuardedTaggedValue(geometries.geometry, default=None),
                        masked_value=MapPermissionGuardedTaggedValue(geometries.masked_geometry, default=None),
                        space_id=geometries.space_id
                    )
                    if isinstance(geometries, MaskedLocationGeometry)
                    else MapPermissionsMaskedTaggedValue(MapPermissionGuardedTaggedValue(geometries, default=None))
                )
                for geometries in level_geometries
            ])
            for level_id, level_geometries in self.cached_geometries.items()
        }

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        return {level_id: list(level_geometries) for level_id, level_geometries in self._geometries_by_level.items()}

    """ Subtitle """

    @classmethod
    def recalculate_target_subtitles(cls):
        # todo: make this work better for multiple targets
        all_target_subtitles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
        for obj in cls.objects.prefetch_related("levels",
                                                "spaces__level", "spaces__locations", "spaces__level__locations",
                                                "areas__space__locations", "areas__space__level__locations",
                                                "pois__space__locations", "pois__space__level",
                                                "dynamic_location_targets"):
            location_target_subtitles: list[tuple[tuple[tuple[str, str], ...], frozenset[int]]] = []
            static_targets = tuple(obj.static_targets)
            if len(static_targets) + len(obj.dynamic_location_targets.all()) == 1:
                main_static_target = static_targets[0]
                target_subtitle: list[tuple[str, str]] = []
                for language_code, language_name in settings.LANGUAGES:
                    with translation.override(language_code):
                        target_subtitle.append((language_code, str(main_static_target.subtitle)))
                location_target_subtitles.append(
                    (tuple(target_subtitle), main_static_target.effective_access_restrictions)
                )
            all_target_subtitles.setdefault(tuple(location_target_subtitles), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="target_subtitles",
            values=tuple(
                (pks, [
                    MapPermissionTaggedItem(value=dict(titles), access_restrictions=restrictions)
                    for titles, restrictions in entries
                ]) for entries, pks in all_target_subtitles.items()
            ),
            default=[]
        )

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

    def details_display(self, *, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)

        if grid.enabled:
            grid_square = self.grid_square
            if grid_square is not None:
                grid_square_title = (_('Grid Squares') if grid_square and '-' in grid_square else _('Grid Square'))
                result['display'].insert(3, (grid_square_title, grid_square or None))

        groupcategories = {}
        # todo: add this again
        #for group in self.sorted_groups:
        #    groupcategories.setdefault(group.category, []).append(group)

        for category, groups in sorted(groupcategories.items(), key=lambda item: item[0].priority):
            result['display'].insert(3, (
                category.title if category.single else category.title_plural,
                tuple({
                    'id': group.pk,
                    'slug': group.effective_slug,
                    'title': group.title,
                    'can_search': group.can_search,
                } for group in sorted(groups, key=attrgetter('priority'), reverse=True))
            ))

        if editor_url:
            result['editor_url'] = reverse('editor.specific_locations.edit', kwargs={'pk': self.pk})

        return result

    """ Changed Geometries """

    def register_changed_geometries(self, force=False):
        # todo: maybe not just if force but also if some property changed?
        if force:
            # todo: targets need to be read correctly
            for target in self.static_targets:
                target.register_change(force=True)

    def pre_save_changed_geometries(self):
        self.register_changed_geometries()

    def save(self, *args, **kwargs):
        self.pre_save_changed_geometries()
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries(force=True)

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


# …eh… this should just work without the int | ? but pycharm doesn't like it then… maybe it's pointless
type LocationID = int | NewType("LocationID", int)
type ParentageID = int | NewType("ParentageID", int)
type AncestryID = int | NewType("AncestryID", int)
type AncestryPathID = int | NewType("AncestryPathID", int)

type AffectedParentages = tuple[tuple[LocationID, ParentageID], ...]
type AffectedParentagesLookup = dict[LocationID, ParentageID]


@receiver(m2m_changed, sender=SpecificLocation.parents.through)
def location_parentage_changed(sender, instance: SpecificLocation, pk_set: set[int], action: str, reverse: bool,
                               **kwargs):
    match (action, reverse):
        case ("post_add", False):
            location_parents_added(instance=instance, pk_set=pk_set)
        case ("post_add", True):
            location_children_added(instance=instance, pk_set=pk_set)
        case ("post_remove" | "post_clear", False):
            location_parents_removed(instance=instance, pk_set=pk_set)
        case ("post_add" | "post_clear", True):
            location_children_removed(instance=instance, pk_set=pk_set)


def location_parents_added(instance: SpecificLocation, pk_set: set[int]):
    """
    new parents were added to the location
    """
    # get added parentages, this is why we do this after
    added_parentages: AffectedParentages = tuple(LocationParentage.objects.filter(  # noqa
        parent_id__in=pk_set, child=instance,
    ).values_list("parent_id", "pk"))

    # map IDs of parents to IDs of parentages
    added_parentages_lookup: AffectedParentagesLookup = dict(added_parentages)

    # get ancestries of added parents
    parent_ancestries: tuple[tuple[AncestryID, LocationID, LocationID], ...] = tuple(  # noqa
        LocationAncestry.objects.filter(descendant_id__in=pk_set).values_list(
            "pk", "ancestor_id", "descendant_id"
        )
    )

    # create ancestries from this new parentage
    created_ancestries: tuple[tuple[tuple[LocationID, LocationID], AncestryID], ...] = tuple(
        ((created_ancestry.ancestor_id, created_ancestry.descendant_id), created_ancestry.id)
        for created_ancestry in LocationAncestry.objects.bulk_create((
            # new ancestry from parent (might be duplicates, thus ignore_conflicts)
            *(LocationAncestry(ancestor_id=parent_id, descendant_id=instance.pk)
              for parent_id, parentage_id in added_parentages),
            # copy ancestries of parent (might be duplicates, thus ignore_conflicts)
            *(LocationAncestry(ancestor_id=ancestor_id, descendant_id=instance.pk)
              for ancestry_id, ancestor_id, descendant_id in parent_ancestries),
        ), ignore_conflicts=True)
    )

    # check that we really got as many ancestries back as wew put into bulk_create()
    if len(created_ancestries) == len(added_parentages) + len(parent_ancestries):
        raise ValueError("location_hierarchy_changed post_add handler bulk_insert len() mismatch")

    # map IDs of parents' ancestries to IDs of their copies
    copied_ancestries_id_lookup: dict[AncestryID, AncestryID] = dict(zip(
        (parent_ancestry_id for parent_ancestry_id, *fields in parent_ancestries),
        (created_ancestry_id for fields, created_ancestry_id in created_ancestries[len(added_parentages):]),
    ))

    # add hops to new ancestries
    LocationAncestryPath.objects.bulk_create((
        *(  # add path continuations for parent ancestries
            LocationAncestryPath(
                prev_path_id=path_id,
                parentage_id=added_parentages_lookup[parent_id],
                ancestry_id=copied_ancestries_id_lookup[ancestry_id],
                num_hops=num_hops+1,
            ) for path_id, parent_id, ancestry_id, num_hops in LocationAncestryPath.objects.filter(
                # Select all paths belonging to the parent ancestries
                ancestry_id__in=(ancestry_id for ancestry_id, *fields in parent_ancestries),
            ).values_list("pk", "ancestry__descendant_id", "ancestry_id", "num_hops")
        ),
        *(  # add path for new ancestries
            LocationAncestryPath(
                prev_path_id=None,
                parentage_id=added_parentages_lookup[parent_id],
                ancestry_id=ancestry_id,
                num_hops=0,
            ) for parent_id, ancestry_id in zip(
                # map parent ids to IDs of created direct ancestries
                (parent_ancestry_id for parent_ancestry_id, *fields in parent_ancestries),
                (created_ancestry_id for fields, created_ancestry_id in created_ancestries[len(added_parentages):]),
            )
        ),
    ))

    # notify changed geometries… todo: this should definitely use the descendants thing
    instance.register_changed_geometries(force=True)


def location_children_added(instance: SpecificLocation, pk_set: set[int]):
    """
    new children were added to the location
    """
    # get added parentages, this is why we do this after
    added_parentages: AffectedParentages = tuple(LocationParentage.objects.filter(  # noqa
        parent=instance, child_id__in=pk_set,
    ).values_list("child_id", "pk"))

    # map IDs of parents to IDs of parentages
    added_parentages_lookup: AffectedParentagesLookup = dict(added_parentages)

    # get this parent's ancestries
    parent_ancestries: tuple[tuple[AncestryID, LocationID], ...] = tuple(LocationAncestry.objects.filter(  # noqa
        descendant_id__in=pk_set
    ).values_list("pk", "ancestor_id"))

    # compute the product (all combintations of) parents ancestries and added children
    ancestries_to_copy: tuple[tuple[tuple[AncestryID, LocationID], LocationID], ...] = tuple(
        product(parent_ancestries, pk_set)
    )

    # create ancestries from this new parentage
    created_ancestries: tuple[tuple[LocationID, LocationID, AncestryID], ...] = tuple(
        (created_ancestry.ancestor_id, created_ancestry.descendant_id, created_ancestry.pk)
        for created_ancestry in LocationAncestry.objects.bulk_create((
            # new ancestry from parent (might be duplicates, thus ignore_conflicts)
            *((LocationAncestry(ancestor_id=instance.pk, descendant_id=child_id)
               for child_id, parentage_id in added_parentages)),
            # copy ancestries of parent (might be duplicates, thus ignore_conflicts)
            *((LocationAncestry(ancestor_id=ancestor_id, descendant_id=child_id)
               for (parent_ancestry_id, ancestor_id), child_id in ancestries_to_copy)),
        ), ignore_conflicts=True)
    )

    # check that we really got as many ancestries back as wew put into bulk_create()
    if len(created_ancestries) == len(added_parentages) + len(added_parentages) * len(parent_ancestries):
        raise ValueError("location_hierarchy_changed reverse post_add handler bulk_insert len() mismatch")

    # get a list of ancestries to copy and the resulting (potential) copy
    copied_ancestries = zip(ancestries_to_copy,
                            (ancestry_id for a, d, ancestry_id in created_ancestries[len(added_parentages):]))

    # map IDs of parents' ancestries and the child id that it was copied for to the IDs of the copy
    created_ancestries_id_mapping: dict[tuple[AncestryID, LocationID], AncestryID] = dict(
        ((parent_ancestry_id, child_id), created_ancestry_id)
        for ((parent_ancestry_id, ancestor_id), child_id), created_ancestry_id in copied_ancestries
    )

    # create paths for ancestries
    LocationAncestryPath.objects.bulk_create((
        *(  # copy hops from parent ancestries
            LocationAncestryPath(
                prev_path_id=path_id,
                parentage_id=added_parentages_lookup[child_id],
                ancestry_id=created_ancestries_id_mapping[(ancestry_id, child_id)],
                num_hops=num_hops + 1,
            ) for (path_id, ancestry_id, num_hops), (child_id, parentage_id) in product(
                # compute the product of the parent's ancestries' paths and the IDs of the added children and parentages
                # because we want continue each path on each per-child ancestry copy
                LocationAncestryPath.objects.filter(
                    ancestry_id__in=(pk for pk, ancestor_id in parent_ancestries),
                ).values_list("pk", "ancestry_id", "num_hops"),
                added_parentages,
            )
        ),
        *(  # add new parentage to new ancestries
            LocationAncestryPath(
                prev_path_id=None,
                parentage_id=parentage_id,
                ancestry_id=ancestry_id,
                num_hops=0,
            ) for ancestry_id, parentage_id in zip(
                # get the created direct ancestries (for the added parentages)
                (ancestry_id for fields, ancestry_id in created_ancestries[:len(added_parentages)]),
                # get the get the added parentages
                (parentage_id for child_id, parentage_id in added_parentages),
            )
        )
    ))

    # notify changed geometries… todo: this should definitely use the descendants thing
    for obj in SpecificLocation.objects.filter(pk__in=pk_set):
        obj.register_changed_geometries(force=True)


def location_parents_removed(instance: SpecificLocation, pk_set: set[int]):
    """
    parents were removed from the location
    """
    # get removed parentages, this is why we do this before
    LocationAncestry.objects.annotate(count=Count("paths")).filter(descendant_id=instance.pk, count=0).delete()

    # notify changed geometries… todo: this should definitely use the descendants thing
    instance.register_changed_geometries(force=True)


def location_children_removed(instance: SpecificLocation, pk_set: set[int] = None):
    """
    children were removed from the location
    """
    if pk_set is None:
        # todo: this is a hack, can be done nicer
        pk_set = set(LocationAncestry.objects.filter(ancestor_id=instance.pk).values_list("pk", flat=True))

    LocationAncestry.objects.annotate(count=Count("paths")).filter(ancestor_id=instance.pk, count=0).delete()

    # notify changed geometries… todo: this should definitely use the descendants thing
    for obj in SpecificLocation.objects.filter(pk__in=pk_set):
        obj.register_changed_geometries(force=True)


@receiver(m2m_changed, sender=SpecificLocation.levels.through)
@receiver(m2m_changed, sender=SpecificLocation.spaces.through)
@receiver(m2m_changed, sender=SpecificLocation.areas.through)
@receiver(m2m_changed, sender=SpecificLocation.pois.through)
def locations_targets_changed(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if not reverse:
        # the targets of a specific location were changed
        if action not in ('post_clear',):
            raise NotImplementedError
        query = model.objects.filter(pk__in=pk_set)
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        if issubclass(model, SpaceGeometryMixin):
            query = query.select_related('space')  # todo… ??? needed?
        for obj in query:
            obj.register_change(force=True)
    else:
        # the locations of a specific location target were changed
        instance.register_change(force=True)


class SpecificLocationTargetMixin(models.Model):
    class Meta:
        abstract = True

    @cached_property
    def sorted_locations(self) -> LazyMapPermissionFilteredSequence[SpecificLocation]:
        """
        highest priority first
        """
        if 'locations' not in getattr(self, '_prefetched_objects_cache', ()):
            warnings.warn('Accessing sorted_locations despite no prefetch_related. '
                          'Returning empty list.', RuntimeWarning)
            return LazyMapPermissionFilteredSequence(())
        # noinspection PyUnresolvedReferences
        return LazyMapPermissionFilteredSequence(sorted(self.locations.all(),
                                                        key=attrgetter("effective_priority_order")))

    @property
    def title(self) -> str:
        return self.sorted_locations[0].title if self.sorted_locations else str(self)

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        # todo: enhance performance using generator
        colors = list(filter(None, [location.get_color(color_manager) for location in self.sorted_locations]))
        if not colors:
            return None
        return colors[0]

    @property
    def geometries_by_level(self) -> GeometriesByLevelSchema:
        return {}

    @property
    def bounds(self) -> Optional[BoundsSchema]:
        # todo: remove
        return None

    @property
    def subtitle(self):
        raise NotImplementedError

    @cached_property
    def point(self) -> LocationPoint | None:
        return None

    def get_color_sorted(self, color_manager) -> tuple[int, str] | None:
        # todo: cache this in db?
        try:
            colors: Iterator[tuple[int, str]] = filter(None, (
                location.get_color_sorted(color_manager) for location in self.sorted_locations
            ))
            return next(iter(sorted(colors, key=itemgetter(0), reverse=True)))
        except StopIteration:
            return None

    def get_location(self, can_describe=False) -> Optional[SpecificLocation]:
        # todo: do we want to get rid of this?
        return next(iter((*(location for location in self.sorted_locations if location.can_describe), None)))


CachedEffectiveGeometries = list[MapPermissionTaggedItem[PolygonSchema | MultiPolygonSchema]]


class SpecificLocationGeometryTargetMixin(SpecificLocationTargetMixin):
    geometry = None

    class Meta:
        abstract = True


class LocationGroupCategory(models.Model):
    name = models.SlugField(_('Name'), unique=True, max_length=50)
    single = models.BooleanField(_('single selection'), default=False)
    title = I18nField(_('Title'), plural_name='titles', fallback_any=True)
    title_plural = I18nField(_('Title (Plural)'), plural_name='titles_plural', fallback_any=True)
    help_text = I18nField(_('Help text'), plural_name='help_texts', fallback_any=True, fallback_value='')
    allow_levels = models.BooleanField(_('allow levels'), db_index=True, default=True)
    allow_spaces = models.BooleanField(_('allow spaces'), db_index=True, default=True)
    allow_areas = models.BooleanField(_('allow areas'), db_index=True, default=True)
    allow_pois = models.BooleanField(_('allow pois'), db_index=True, default=True)
    allow_dynamic_locations = models.BooleanField(_('allow dynamic locations'), db_index=True, default=True)
    priority = models.IntegerField(default=0, db_index=True)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._orig = {"priority": self.priority}

    class Meta:
        verbose_name = _('Location Group Category')
        verbose_name_plural = _('Location Group Categories')
        default_related_name = 'locationgroupcategories'
        ordering = ('-priority', )

    def register_changed_geometries(self):
        for group in  self.groups.prefetch_related('groups__specific_locations'):
            group.register_changed_geometries()

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


class LocationGroupManager(UseQForPermissionsManager):
    def get_queryset(self):
        return super().get_queryset().select_related('category')


# todo: remove locationgroup model and everything related to it
class LocationGroup(Location, models.Model):
    """
    Implements :py:class:`c3nav.mapdata.schemas.locations.ListedLocationProtocol`.
    """
    locationtype = "locationgroup"
    slug_as_id = False

    class CanReportMissing(models.TextChoices):
        DONT_OFFER = "dont_offer", _("don't offer")
        REJECT = "reject", _("offer in first step, then reject")
        SINGLE = "single", _("offer in first step, exclusive choice")
        SINGLE_IMAGE = "image", _("offer in first step, then only query image")
        MULTIPLE = "multiple", _("offer if nothing in the first step matches, multiple choice")

    class CanReportMistake(models.TextChoices):
        ALLOW = "allow", _("allow")
        REJECT = "reject", _("reject for all locations with this group")

    category = models.ForeignKey(LocationGroupCategory, related_name='groups', on_delete=models.PROTECT,
                                 verbose_name=_('Category'))
    priority = models.IntegerField(default=0, db_index=True)
    hierarchy = models.IntegerField(default=0, db_index=True, verbose_name=_('hierarchy'))
    label_settings = models.ForeignKey('mapdata.LabelSettings', null=True, blank=True, on_delete=models.PROTECT,
                                       verbose_name=_('label settings'),
                                       help_text=_('unless location specifies otherwise'))
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
                                       help_text=_('assign this group to imported hub locations of this type'))
    external_url_label = I18nField(_('external URL label'), plural_name='external_url_labels', blank=True,
                                   fallback_any=True, fallback_value="")

    load_group_contribute = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    effective_order = models.PositiveIntegerField(default=2**31-1)

    objects = LocationGroupManager()

    class Meta:
        verbose_name = _('Location Group')
        verbose_name_plural = _('Location Groups')
        default_related_name = 'locationgroups'
        ordering = ('effective_order',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        deferred_fields = self.get_deferred_fields()
        self._orig = {
            key: getattr(self, key)
            for key in ("priority", "hierarchy", "category_id", "color")
            if key not in deferred_fields
        }

    def details_display(self, *, editor_url=True, **kwargs):
        result = super().details_display(**kwargs)
        result['display'].insert(3, (_('Category'), self.category.title))
        result['display'].extend([
            (_('color'), self.color),
            (_('priority'), str(self.priority)),
        ])
        if editor_url:
            result['editor_url'] = reverse('editor.locationgroups.edit', kwargs={'pk': self.pk})
        return result

    @property
    def title_for_forms(self):
        attributes = []
        if self.can_search:
            attributes.append(_('search'))
        if self.can_describe:
            attributes.append(_('describe'))
        if self.color:
            attributes.append(_('color'))
        if not attributes:
            attributes.append(_('internal'))
        return self.title + ' ('+', '.join(str(s) for s in attributes)+')'

    def register_changed_geometries(self):
        for obj in self.specific_locations.all():
            obj.register_change(force=True)

    @property
    def subtitle(self):
        result = self.category.title
        if hasattr(self, 'locations'):  # todo: improve?
            return format_lazy(_('{category_title}, {num_locations}'),
                               category_title=result,
                               num_locations=(ngettext_lazy('%(num)d location', '%(num)d locations', 'num') %
                                              {'num': len(self.locations)}))
        return result

    @cached_property
    def sublocations(self) -> list[int]:
        # noinspection PyUnresolvedReferences
        return [l.pk for l in self.specific_locations.all()]

    @property
    def effective_external_url_label(self):
        return self.external_url_label

    @classmethod
    def recalculate_effective_order(cls):
        cls.objects.update(effective_order=Subquery(
            cls.objects.filter(pk=OuterRef('pk')).annotate(
                new_effective_order=Window(
                    expression=RowNumber(),
                    order_by=('-category__priority', '-priority')
                )
            ).values('new_effective_order')[:1]
        ))

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


class DynamicLocationTarget(SpecificLocationTargetMixin, models.Model):
    location = models.ForeignKey("SpecificLocation", null=True, on_delete=models.CASCADE)
    position_secret = models.CharField(_('position secret'), max_length=32)

    class Meta:
        verbose_name = _("Dynamic location target")
        verbose_name_plural = _("Dynamic locations target")
        default_related_name = "dynamic_location_targets"


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
