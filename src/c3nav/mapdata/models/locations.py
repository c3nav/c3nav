import operator
import string
import time
from collections import deque, defaultdict
from dataclasses import dataclass
from datetime import timedelta
from decimal import Decimal
from functools import reduce, cached_property
from itertools import chain, batched, product, repeat
from operator import attrgetter, itemgetter
from typing import TYPE_CHECKING, Optional, TypeAlias, Union, Sequence, NewType, NamedTuple, Generator, Self, Iterable

from django.conf import settings
from django.core.cache import cache
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models, transaction
from django.db.models import Q
from django.db.models.aggregates import Count
from django.db.models.constraints import CheckConstraint, UniqueConstraint
from django.db.models.expressions import F, OuterRef, Subquery, When, Case, Value
from django.db.models.query import Prefetch
from django.db.models.signals import m2m_changed
from django.db.utils import IntegrityError
from django.dispatch.dispatcher import receiver
from django.urls import reverse
from django.utils import timezone
from django.utils import translation
from django.utils.crypto import get_random_string
from django.utils.functional import lazy
from django.utils.text import format_lazy
from django.utils.translation import gettext_lazy as _, get_language, get_language_info
from django_pydantic_field import SchemaField
from shapely.geometry import shape

from c3nav.api.schema import GeometriesByLevelSchema, PolygonSchema, MultiPolygonSchema, GeometriesByLevel, PointSchema
from c3nav.mapdata.fields import I18nField, lazy_get_i18n_value
from c3nav.mapdata.grid import grid
from c3nav.mapdata.models.access import AccessRestrictionMixin
from c3nav.mapdata.models.base import TitledMixin
from c3nav.mapdata.models.geometry.base import CachedBounds, LazyMapPermissionFilteredBounds
from c3nav.mapdata.permissions import MapPermissionGuardedSequence, MapPermissionTaggedItem, \
    MapPermissionGuardedTaggedValue, MapPermissionGuardedTaggedValueSequence, \
    MapPermissionMaskedTaggedValue, MapPermissionGuardedTaggedSequence
from c3nav.mapdata.schemas.locations import GridSquare, DynamicLocationState
from c3nav.mapdata.schemas.model_base import LocationPoint, BoundsByLevelSchema, \
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


ColorByTheme: TypeAlias = dict[int, FillAndBorderColor]
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


class LocationTagOrderMixin(models.Model):
    class Meta:
        abstract = True

    effective_downwards_breadth_first_order = models.PositiveIntegerField(default=2**31-1, editable=False)
    effective_downwards_depth_first_pre_order = models.PositiveIntegerField(default=2**31-1, editable=False)
    effective_downwards_depth_first_post_order = models.PositiveIntegerField(default=2**31-1, editable=False)
    effective_upwards_breadth_first_order = models.PositiveIntegerField(default=2 ** 31 - 1, editable=False)
    effective_upwards_depth_first_pre_order = models.PositiveIntegerField(default=2 ** 31 - 1, editable=False)
    effective_upwards_depth_first_post_order = models.PositiveIntegerField(default=2 ** 31 - 1, editable=False)


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


class LocationTagRelation(LocationTagOrderMixin, models.Model):
    """ Automatically populated. Indicating that there is (at least) one relation path between two locations """
    ancestor = models.ForeignKey("LocationTag", on_delete=models.CASCADE,
                                 related_name="downwards_relations")
    descendant = models.ForeignKey("LocationTag", on_delete=models.CASCADE,
                                   related_name="upwards_relations")

    # look, this field is genuinely just for fun, cause we can, probably not useful
    first_adjacencies = models.ManyToManyField("LocationTagAdjacency", related_name="provides_relations",
                                               through="LocationTagRelationPathSegment")

    class Meta:
        constraints = (
            # todo: wouldn't it be nice to actual declare multi-field foreign key constraints here, manually?
            UniqueConstraint(fields=("ancestor", "descendant"), name="unique_location_tag_relation"),
            CheckConstraint(check=~Q(ancestor=F("descendant")), name="no_circular_location_tag_relation"),
        )


class LocationTagRelationPathSegment(models.Model):
    """ Automatically populated. One relation path for the given relation, ending with the given adjacency. """
    prev_path = models.ForeignKey("self", on_delete=models.CASCADE, related_name="+", null=True)
    adjacency = models.ForeignKey("LocationTagAdjacency", on_delete=models.CASCADE, related_name="+")
    relation = models.ForeignKey("LocationTagRelation", on_delete=models.CASCADE, related_name="paths")
    # rename to num_predecessors?
    num_hops = models.PositiveSmallIntegerField(db_index=True)

    class Meta:
        constraints = (
            # todo: wouldn't it be nice to actual declare multi-field foreign key constraints here, manually?
            UniqueConstraint(fields=("prev_path", "adjacency"), name="relation_path_unique_prev_path_adjacency"),
            UniqueConstraint(fields=("prev_path", "relation"), name="relation_path_unique_prev_path_relation"),
            CheckConstraint(check=Q(prev_path__isnull=True, num_hops=0) |
                                  Q(prev_path__isnull=False, num_hops__gt=0), name="relation_path_enforce_num_hops"),
        )

    def __str__(self):
        return (f"{self.pk}: num_hops={self.num_hops} "
                f"prev_path={self.prev_path if "prev_path" in self._state.fields_cache else self.prev_path_id !r}" +
                (f" ancestor={self.relation.ancestor_id} descendant={self.relation.descendant_id}"
                 if "relation" in self._state.fields_cache else f" relation={self.relation_id}") +
                (f" parent={self.adjacency.parent_id} child={self.adjacency.child_id}"
                 if "adjacency" in self._state.fields_cache else f" adjacency={self.adjacency_id}"))


class SimpleLocationTagRelationPathSegmentTuple(NamedTuple):
    prev: Optional["SimpleLocationTagRelationPathSegmentTuple"]
    ancestor: int | None
    parent: int
    tag: int
    num_hops: int


class LocationTag(LocationTagOrderMixin, AccessRestrictionMixin, TitledMixin, models.Model):
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

    load_group_contribute = models.ForeignKey("LoadGroup", on_delete=models.SET_NULL, null=True, blank=True,
                                              verbose_name=_('contribute to load group'))

    # imported from locationgroup end

    parents = models.ManyToManyField("self", related_name="children", symmetrical=False,
                                              through="LocationTagAdjacency", through_fields=("child", "parent"))
    calculated_ancestors = models.ManyToManyField("self", related_name="calculated_descendants", symmetrical=False,
                                                  through="LocationTagRelation", through_fields=("descendant", "ancestor"),
                                                  editable=False)

    levels = models.ManyToManyField('Level', related_name="tags")
    spaces = models.ManyToManyField('Space', related_name="tags")
    areas = models.ManyToManyField('Area', related_name="tags")
    pois = models.ManyToManyField('POI', related_name="tags")

    effective_minimum_access_restrictions: frozenset[int] = SchemaField(schema=frozenset[int], default=frozenset)

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

    def get_color(self, color_manager: 'ThemeColorManager') -> str | None:
        color = self.cached_effective_colors.get(color_manager.theme_id, None)
        return None if color is None else color.fill

    def get_color_sorted(self, color_manager: 'ThemeColorManager') -> tuple[int, str] | None:
        color = self.get_color(color_manager)
        if color is None:
            return None
        return self.effective_depth_first_post_order, color

    @classmethod
    def evaluate_location_tag_relations(cls):
        build_children_by_parent: dict[int | None, deque[int]] = defaultdict(deque)
        adjacency_ids: dict[tuple[int, int], int] = {}
        for pk, parent_id, child_id in LocationTagAdjacency.objects.values_list("pk", "parent_id", "child_id"):
            adjacency_ids[(parent_id, child_id)] = pk
            build_children_by_parent[parent_id].append(child_id)
        children_by_parent: dict[int | None, frozenset[int]] = {
            parent_id: frozenset(children_ids) for parent_id, children_ids in build_children_by_parent.items()
        }

        fail = False

        # create ancestors
        expected_paths: dict[int, tuple[SimpleLocationTagRelationPathSegmentTuple, ...]] = {}
        num_hops = 0
        last_paths: tuple[SimpleLocationTagRelationPathSegmentTuple, ...] = tuple(chain.from_iterable(
            (
                SimpleLocationTagRelationPathSegmentTuple(ancestor=parent_id, parent=parent_id, tag=child_id,
                                                          prev=None, num_hops=0)
                for child_id in child_ids
            ) for parent_id, child_ids in children_by_parent.items()
        ))
        while last_paths:
            cyclic_paths = tuple(p for p in last_paths if p.ancestor == p.tag)
            last_paths = tuple(p for p in last_paths if p.ancestor != p.tag)
            for path in cyclic_paths:
                print(f"INCONSISTENCY! Circular hierarchy! Breaking parent→child {path.parent}→{path.tag}")
                fail = True
            expected_paths[num_hops] = last_paths

            num_hops += 1
            last_paths = tuple(chain.from_iterable(
                (
                    SimpleLocationTagRelationPathSegmentTuple(ancestor=prev.ancestor, parent=prev.tag, tag=child_id,
                                                              prev=prev, num_hops=num_hops)
                    for child_id in child_ids
                ) for prev, child_ids in zip(last_paths, (children_by_parent.get(path.tag, frozenset()) for path in last_paths))
            ))

        expected_relations = {(path.ancestor, path.tag) for path in chain.from_iterable(expected_paths.values())}
        relation_ids = {
            (ancestor_id, descendant_id): pk
            for pk, ancestor_id, descendant_id in LocationTagRelation.objects.values_list("pk", "ancestor_id", "descendant_id")
        }
        existing_relations = set(relation_ids.keys())

        missing_relations = expected_relations - existing_relations
        if missing_relations:
            print("INCONSISTENCY: Missing relations, creating:", missing_relations)
            fail = True
            relation_ids.update({
                relation.pk: (relation.ancestor_id, relation.descendant_id)
                for relation in LocationTagRelation.objects.bulk_create((
                    LocationTagRelation(
                        ancestor_id=ancestor_id,
                        descendant_id=descendant_id,
                    ) for ancestor_id, descendant_id in missing_relations
                ))
            })

        extra_relations = existing_relations - expected_relations
        if extra_relations:
            print("INCONSISTENCY: Extra relations, deleting:", missing_relations)
            fail = True
            LocationTagRelation.objects.filter(
                pk__in=(relation_ids[extra_relation] for extra_relation in extra_relations)
            ).delete()
            for extra_relation in missing_relations:
                del relation_ids[extra_relation]

        num_deleted, num_deleted_per_model = LocationTagRelationPathSegment.objects.exclude(
            # exclude things where things make sense
            Q(adjacency__child=F("relation__descendant")) & (
                (Q(prev_path__isnull=True) | (Q(adjacency__parent=F("prev_path__adjacency__child"))
                                              & Q(relation__ancestor=F("prev_path__relation__ancestor"))
                                              & Q(num_hops=F("prev_path__num_hops")+1)))
                | (Q(prev_path__isnull=False) | Q(adjacency__parent=F("relation__ancestor")))
            )
        ).delete()
        if num_deleted:
            print("INCONSISTENCY: Invalid paths that don't fit modeling constraints, deleting", num_deleted, "of them")
            fail = True

        existing_paths_by_id = {
            pk: fields for pk, *fields in LocationTagRelationPathSegment.objects.values_list(
                "pk", "prev_path_id", "relation__ancestor_id",
                "adjacency__parent_id", "adjacency__child_id", "num_hops",
            )
        }
        existing_paths_by_num_hops_and_id: dict[int, dict[int, SimpleLocationTagRelationPathSegmentTuple]] = {}
        existing_path_id_by_tuple: dict[SimpleLocationTagRelationPathSegmentTuple | None, int | None] = {None: None}

        paths_by_num_hops: dict[int, list[tuple]] = {}
        for id, path in existing_paths_by_id.items():
            paths_by_num_hops.setdefault(path[4], []).append((id, path))

        for num_hops, paths in sorted(paths_by_num_hops.items(), key=itemgetter(0)):
            num_hops_paths = {}
            existing_paths_by_num_hops_and_id[num_hops] = num_hops_paths

            last_num_hops_paths = {} if num_hops == 0 else existing_paths_by_num_hops_and_id.get(num_hops - 1, {})

            for pk, (prev_path_id, ancestor_id, parent_id, child_id, n) in paths:
                t = SimpleLocationTagRelationPathSegmentTuple(
                    prev=None if prev_path_id is None else last_num_hops_paths[prev_path_id],
                    ancestor=ancestor_id,
                    parent=parent_id,
                    tag=child_id,
                    num_hops=num_hops,
                )
                num_hops_paths[pk] = t
                existing_path_id_by_tuple[t] = pk

        delete_ids: deque[int] = deque()

        max_num_hops = max(chain(existing_paths_by_num_hops_and_id.keys(), expected_paths.keys()), default=0)
        for num_hops in range(max_num_hops+1):
            existing_paths_for_hops = frozenset(existing_paths_by_num_hops_and_id.get(num_hops, {}).values())
            expected_paths_for_hops = frozenset(expected_paths.get(num_hops, ()))

            missing_paths = tuple(expected_paths_for_hops - existing_paths_for_hops)
            if missing_relations:
                print("INCONSISTENCY: Missing paths, creating:", missing_paths)
                fail = True
                existing_path_id_by_tuple.update(
                    dict(zip(missing_paths, (created_path.pk for created_path in LocationTagRelationPathSegment.objects.bulk_create((
                        LocationTagRelationPathSegment(
                            prev_path=existing_path_id_by_tuple[missing_path.prev],
                            adjacency=adjacency_ids[(missing_path.parent, missing_path.tag)],
                            relation=relation_ids[(missing_path.ancestor, missing_path.tag)],
                            num_hops=num_hops,
                        ) for missing_path in missing_paths
                    )))))
                )

            extra_paths = existing_paths_for_hops - expected_paths_for_hops
            if extra_relations:
                print("INCONSISTENCY: Extra paths, deleting:", extra_paths)
                delete_ids.extend(existing_path_id_by_tuple[extra_path] for extra_path in extra_paths)
                fail = True

        if delete_ids:
            LocationTagRelationPathSegment.objects.filter(pk__in=delete_ids).delete()

        if fail:
            raise ValueError("verify_location_relation failed")

        cls.recalculate_effective_order()

    class EffectiveOrder(NamedTuple):
        depth_first_pre_order: dict[int | None, dict[int, int]]
        depth_first_post_order: dict[int | None, dict[int, int]]
        breadth_first_order: dict[int | None, dict[int, int]]

        depth_first_pre_order: dict[int | None, dict[int, int]]
        depth_first_post_order: dict[int | None, dict[int, int]]
        breadth_first_order: dict[int | None, dict[int, int]]

        @staticmethod
        def calc_breadth_first_order(root_tag_ids: list[int],
                                     children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
            result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order
            next_tags: deque[tuple[set[int], list[int]]] = deque([(set(), root_tag_ids)])
            #print("breadth first")
            while next_tags:
                #print(next_tags, children_for_parent, result)
                ancestor_ids, tag_ids = next_tags.popleft()
                for tag_id in tag_ids:
                    result[None].setdefault(tag_id, len(result[None]))
                    for ancestor_id in ancestor_ids:
                        result[ancestor_id].setdefault(tag_id, len(result[ancestor_id]))
                    next_tags.append((ancestor_ids | {tag_id}, children_for_parent[tag_id]))

            return result

        @staticmethod
        def calc_depth_first_post_order(root_tag_ids: list[int],
                                        children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
            result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order
            next_tags: deque[tuple[tuple[int, ...], int, list[int]]] = deque([((None, ), None, root_tag_ids)])
            # print("root_tag_ids=", root_tag_ids, "children_for_parent=", children_for_parent)
            # print("depth first")

            def add(ancestors: set, descendant_id: int):
                new_ancestors = ancestors | {descendant_id}
                for child_id in children_for_parent[descendant_id]:
                    add(new_ancestors, child_id)
                for ancestor_id in ancestors:
                    result[ancestor_id].setdefault(descendant_id, len(result[ancestor_id]))

            start_ancestors = {None}
            for root_id in root_tag_ids:
                add(start_ancestors, root_id)

            return result

        @staticmethod
        def calc_depth_first_pre_order(root_tag_ids: list[int],
                                       children_for_parent: dict[int, list[int]]) -> dict[int | None, dict[int, int]]:
            result: dict[int | None, dict[int, int]] = defaultdict(dict)  # dict to maintain insertion order

            def add(ancestors: set, descendant_id: int):
                new_ancestors = ancestors | {descendant_id}
                for ancestor_id in ancestors:
                    result[ancestor_id].setdefault(descendant_id, len(result[ancestor_id]))
                for child_id in children_for_parent[descendant_id]:
                    add(new_ancestors, child_id)

            start_ancestors = {None}
            for root_id in root_tag_ids:
                add(start_ancestors, root_id)

            return result

        @classmethod
        def calculate(cls, root_tag_ids: list[int], children_for_parent: dict[int, list[int]]) -> Self:
            return cls(
                breadth_first_order=cls.calc_breadth_first_order(root_tag_ids, children_for_parent),
                depth_first_pre_order=cls.calc_depth_first_pre_order(root_tag_ids, children_for_parent),
                depth_first_post_order=cls.calc_depth_first_post_order(root_tag_ids, children_for_parent),
            )

    @staticmethod
    def _tuples_by_value(tuples: dict[tuple[int, int], int]) -> dict[int, set[tuple[int, int]]]:
        result: dict[int, set[tuple[int, int]]] = defaultdict(set)
        for t, val in tuples.items():
            result[val].add(t)
        return result

    @classmethod
    def recalculate_effective_order(cls):
        pks, priorities, num_parents, num_children = zip(
            *LocationTag.objects.annotate(
                Count("parents"),
                Count("children"),
            ).values_list("pk", "priority", "parents__count", "children__count").order_by("-priority")
        )
        root_tag_ids = [pk for pk, parents in zip(pks, num_parents) if parents == 0]
        leaf_tag_ids = [pk for pk, children in zip(pks, num_children) if children == 0]

        children_for_parent: dict[int, list[int]] = defaultdict(list)
        for parent_id, child_id in LocationTagAdjacency.objects.order_by(
            "-child__priority", "child_id"
        ).values_list(
            "parent_id", "child_id"
        ):
            children_for_parent[parent_id].append(child_id)

        parents_for_child: dict[int, list[int]] = defaultdict(list)
        for parent_id, child_id in LocationTagAdjacency.objects.order_by(
            "-parent__priority", "parent_id"
        ).values_list(
            "parent_id", "child_id"
        ):
            parents_for_child[child_id].append(parent_id)

        downwards_orders = cls.EffectiveOrder.calculate(root_tag_ids, children_for_parent)
        upwards_orders = cls.EffectiveOrder.calculate(leaf_tag_ids, parents_for_child)

        orders_by_name = ("downwards", downwards_orders), ("upwards", upwards_orders)
        #print(orders_by_name)
        global_orders_by_name: dict[str, dict[int, int]] = dict(chain.from_iterable((
            (
                (f"{dir_name}_{order_name}", order)
                for order_name, order in (
                    ("breadth_first_order", orders.breadth_first_order.pop(None)),
                    ("depth_first_pre_order", orders.depth_first_pre_order.pop(None)),
                    ("depth_first_post_order", orders.depth_first_post_order.pop(None)),
                )
            ) for dir_name, orders in orders_by_name)
        ))

        local_orders_by_name: dict[str, dict[int, set[tuple[int, int]]]] = dict(chain.from_iterable((
            (
                (f"downwards_{order_name}", cls._tuples_by_value(dict(chain.from_iterable(
                    (((ancestor, descendant), i) for descendant, i in descendants.items())
                    for ancestor, descendants in downwards.items()
                )))),
                (f"upwards_{order_name}", cls._tuples_by_value(dict(chain.from_iterable(
                     (((descendant, ancestor), i) for descendant, i in descendants.items())
                     for ancestor, descendants in upwards.items()
                )))),
            ) for order_name, downwards, upwards in (
                ("breadth_first_order", *(d.breadth_first_order for dir_name, d in orders_by_name)),
                ("depth_first_pre_order", *(d.depth_first_pre_order for dir_name, d in orders_by_name)),
                ("depth_first_post_order", *(d.depth_first_post_order for dir_name, d in orders_by_name)),
            )
        )))

        field = models.PositiveIntegerField()
        LocationTag.objects.update(**{
            f"effective_{order_name}": Case(
                *(
                    When(pk=tag_id, then=Value(i, output_field=field))
                    for tag_id, i in order.items()
                ),
                default=Value(2 ** 31 - 1, output_field=field),
            )
            for order_name, order in global_orders_by_name.items()
        })
        print("local_orders_by_name", local_orders_by_name)
        LocationTagRelation.objects.update(**{
            f"effective_{order_name}": Case(
                *(
                    When(condition=reduce(operator.or_, (Q(ancestor_id=ancestor_id, descendant_id=descendant_id)
                                                         for ancestor_id, descendant_id in tuples)),
                         then=Value(i, output_field=field))
                    for i, tuples in order.items()
                ),
                default=Value(2 ** 31 - 1, output_field=field),
            )
            for order_name, order in local_orders_by_name.items()
        })

    @classmethod
    def calculate_effective_x(cls, name: str, default=..., null=...):
        output_field = cls._meta.get_field(f"effective_{name}")
        cls.objects.annotate(**{
            f"parent_effective_{name}": Subquery(LocationTagRelation.objects.filter(
                descendant=OuterRef("pk"),
            ).exclude(
                **{f"ancestor__{name}__isnull": True} if null is ... else {f"ancestor__{name}": null},
            ).order_by("effective_upwards_depth_first_pre_order").values(f"ancestor__{name}")[:1]),
            f"new_effective_{name}": (
                Case(
                    When(condition=~Q(**({f"{name}__isnull": True} if null is ... else {f"{name}": null})),
                         then=F(name)),
                    When(condition=~Q(**({f"parent_effective_{name}__isnull": True} if null is ...
                                         else {f"parent_effective_{name}": null})),
                         then=F(f"parent_effective_{name}")),
                    default=F(f"{name}") if default is ... else Value(default, output_field=output_field),
                    output_field=output_field)
            )
        }).update(**{f"effective_{name}": F(f"new_effective_{name}")})

    @classmethod
    def _bulk_cached_update[T](cls, name: str, values: Sequence[tuple[set[int], T]], default: T):
        output_field = cls._meta.get_field(name)
        cls.objects.annotate(
            **{f"new_{name}": Case(
                *(When(pk__in=pks, then=Value(value, output_field=output_field)) for pks, value in values),
                default=Value(default, output_field=output_field),
            )}
        ).update(**{name: F(f"new_{name}")})

    @classmethod
    def calculate_cached_effective_color(cls):
        # collect ids for each value so we can later bulk-update
        colors: dict[tuple[tuple[int, FillAndBorderColor], ...], set[int]] = {}
        for tag in cls.objects.prefetch_related(
                Prefetch("calculated_ancestors", LocationTag.objects.order_by(
                    'downwards_relations__effective_upwards_depth_first_pre_order'
                ).prefetch_related("theme_colors")),
                "theme_colors",
            ):
            tag_colors: ColorByTheme = {}
            for ancestor in chain((tag, ), tag.calculated_ancestors.all()):
                # add colors from this ancestor
                if ancestor.color and 0 not in tag_colors:
                    tag_colors[0] = FillAndBorderColor(fill=ancestor.color, border=None)
                tag_colors.update({
                    theme_color.theme_id: FillAndBorderColor(fill=theme_color.fill_color,
                                                             border=theme_color.border_color)
                    for theme_color in ancestor.theme_colors.all()
                    if (theme_color.theme_id not in tag_colors
                        and theme_color.fill_color or theme_color.border_color)
                })
            colors.setdefault(tuple(sorted(tag_colors.items())), set()).add(tag.pk)

        cls._bulk_cached_update(
            name="cached_effective_colors",
            values=tuple((pks, dict(colors)) for colors, pks in colors.items()),
            default={}
        )

    @classmethod
    def calculate_cached_describing_titles(cls):
        all_describing_titles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
        for tag in cls.objects.prefetch_related(
                Prefetch("calculated_ancestors", LocationTag.objects.order_by(
                    'downwards_relations__effective_upwards_depth_first_pre_order'
                )),
            ):
            tag_describing_titles: list[tuple[tuple[tuple[str, str], ...], frozenset[int]]] = []
            for ancestor in tag.calculated_ancestors.all():
                if not (ancestor.can_describe and ancestor.titles):
                    continue
                restrictions: frozenset[int] = (
                    frozenset((ancestor.access_restriction_id,)) if ancestor.access_restriction_id else frozenset()
                )
                titles: tuple[tuple[str, str], ...] = tuple(ancestor.titles.items())  # noqa
                if not restrictions or all((restrictions-other_restrictions)
                                           for titles, other_restrictions in tag_describing_titles):
                    # new restriction set was not covered by previous ones
                    tag_describing_titles.append((titles, restrictions))
                if not restrictions:
                    # no access restrictions? that's it, no more ancestors to evaluate
                    break
            all_describing_titles.setdefault(tuple(tag_describing_titles), set()).add(tag.pk)
        cls._bulk_cached_update(
            name="cached_describing_titles",
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
        cls.calculate_effective_x("external_url_labels", default={}, null={})
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
    def recalculate_minimum_access_restrictions(cls):
        all_minimum_access_restrictions: dict[tuple[int, ...], set[int]] = {}
        from c3nav.mapdata.models import Level, Space, Area, POI
        for tag in cls.objects.prefetch_related(
                Prefetch("levels", Level.objects.all()),
                Prefetch("spaces", Space.objects.select_related("level")),
                Prefetch("areas", Area.objects.select_related("space", "space__level")),
                Prefetch("pois", POI.objects.select_related("space", "space__level")),
        ):
            all_minimum_access_restrictions.setdefault(  # noqa
                tuple(reduce(
                    operator.and_,
                    (target.effective_access_restrictions for target in tag.static_targets),
                )) if tag.static_targets else (), set()
            ).add(tag.pk)
        cls._bulk_cached_update(
            name="effective_minimum_access_restrictions",
            values=tuple(
                (pks, frozenset(minimum_access_restrictions))
                for minimum_access_restrictions, pks in all_minimum_access_restrictions.items()
            ),
            default=frozenset()
        )

    @cached_property
    def effective_access_restrictions(self) -> frozenset[int]:
        return super().effective_access_restrictions | self.effective_minimum_access_restrictions

    @classmethod
    def recalculate_all_static_targets(cls):
        all_static_target_ids: dict[tuple[tuple[tuple[str, int], frozenset[int]], ...], set[int]] = {}
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            all_static_target_ids.setdefault(tuple(sorted(
                ((target._meta.model_name, target.pk), target.effective_access_restrictions)
                for target in obj.static_targets
            )), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="cached_all_static_targets",
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

        for obj in cls.objects.prefetch_related("dynamic_targets"):
            all_position_secrets.setdefault(tuple(sorted(
                target.position_secret for target in obj.dynamic_targets.all()
            )), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="cached_all_position_secrets",
            values=tuple((pks, list(secrets)) for secrets, pks in all_position_secrets.items()),
            default=[]
        )

    """ Points / Bounds / Grid """

    @classmethod
    def recalculate_points(cls):
        for obj in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level"):
            obj: LocationTag
            new_points = [
                # we are filtering out versions of this targets points for users who lack certain permissions,
                list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                    (MapPermissionTaggedItem( # add primary level to turn the xy coordinates into a location point
                        value=(target.primary_level_id, *item.value),
                        access_restrictions=item.access_restrictions
                    ) for item in target.cached_points),
                    access_restrictions=obj.effective_access_restrictions,
                )) for target in obj.static_targets
            ]
            if obj.cached_points != new_points:
                obj.cached_points = new_points
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
            obj: LocationTag
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

            if obj.cached_bounds != result:
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
        for tag in cls.objects.prefetch_related("levels", "spaces__level", "areas__space__level", "pois__space__level",
                                                "levels__tags", "spaces__tags", "areas__tags", "pois__tags",):
            tag: LocationTag
            result: CachedGeometriesByLevel = {}
            for target in tag.static_targets:
                try:
                    mask = not target.base_mapdata_accessible
                except AttributeError:
                    mask = False
                # we are filtering out versions of this target's geometries for users who lack certain permissions,
                # because being able to see this tag implies certain permissions
                if mask:
                    result.setdefault(target.primary_level_id, []).append(MaskedLocationTagGeometry(
                        geometry=list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_effective_geometries, tag.effective_access_restrictions
                        )),
                        masked_geometry=list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_simplified_geometries, tag.effective_access_restrictions
                        )),
                        space_id=target.id,
                    ))
                else:
                    result.setdefault(target.primary_level_id, []).append(
                        list(MapPermissionTaggedItem.add_restrictions_and_skip_redundant(
                            target.cached_effective_geometries, tag.effective_access_restrictions
                        ))
                    )
            if tag.cached_geometries != result:
                tag.cached_geometries = result
                tag.save()

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

    @classmethod
    def recalculate_target_subtitles(cls):
        # todo: make this work better for multiple targets
        all_target_subtitles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
        for obj in cls.objects.prefetch_related("levels",
                                                "spaces__level", "spaces__tags", "spaces__level__tags",
                                                "areas__space__tags", "areas__space__level__tags",
                                                "pois__space__tags", "pois__space__level", "dynamic_targets"):
            obj: LocationTag
            tag_target_subtitles: list[tuple[tuple[tuple[str, str], ...], frozenset[int]]] = []
            static_targets: tuple[StaticLocationTagTarget, ...] = tuple(obj.static_targets)
            if len(static_targets) + len(obj.dynamic_targets.all()) == 1:
                main_static_target = static_targets[0]
                target_subtitle: list[tuple[str, str]] = []
                for language_code, language_name in settings.LANGUAGES:
                    with translation.override(language_code):
                        target_subtitle.append((language_code, str(main_static_target.subtitle)))
                tag_target_subtitles.append(
                    (tuple(target_subtitle), main_static_target.effective_access_restrictions)
                )
            all_target_subtitles.setdefault(tuple(tag_target_subtitles), set()).add(obj.pk)

        cls._bulk_cached_update(
            name="cached_target_subtitles",
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
        super().save(*args, **kwargs)

    def pre_delete_changed_geometries(self):
        self.register_changed_geometries(force=True)

    def delete(self, *args, **kwargs):
        self.pre_delete_changed_geometries()
        super().delete(*args, **kwargs)


# …eh… this should just work without the int | ? but pycharm doesn't like it then… maybe it's pointless
type TagID = int | NewType("LocationID", int)
type AdjacencyID = int | NewType("AdjacencyID", int)
type RelationID = int | NewType("RelationID", int)
type RelationPathID = int | NewType("RelationPathID", int)

type AffectedAdjacencies = tuple[tuple[TagID, AdjacencyID], ...]
type AffectedAdjacenciesLookup = dict[TagID, AdjacencyID]


class LocationTagAdjacencyTuple(NamedTuple):
    parent: TagID
    child: TagID


class LocationTagRelationTuple(NamedTuple):
    ancestor: TagID
    descendant: TagID


class LocationTagRelationPathSegmentTuple(NamedTuple):
    prev_path_id: RelationPathID | None
    adjacency_id: AdjacencyID
    relation_id: AdjacencyID
    num_hops: int


@receiver(m2m_changed, sender=LocationTag.parents.through)
def locationtag_adjacency_changed(sender, instance: LocationTag, pk_set: set[int], action: str, reverse: bool, **kwargs):
    match (action, reverse):
        case ("post_add", False):
            # new parents were added to the tag
            locationtag_adjacency_added({(pk, instance.pk) for pk in pk_set})
        case ("post_add", True):
            # new children were added to the tag
            locationtag_adjacency_added({(instance.pk, pk) for pk in pk_set})
        case ("post_remove" | "post_clear", False):
            locationtag_parents_removed(instance=instance, pk_set=pk_set)
        case ("post_remove" | "post_clear", True):
            locationtag_children_removed(instance=instance, pk_set=pk_set)


def unzip_paths_to_create(*data):
    if not data:
        return (), ()
    return zip(*data)


def generate_paths_to_create(
    created_relations: tuple[tuple[tuple[TagID, TagID], RelationID], ...],
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...],
    relevant_relations: tuple[tuple[RelationID, TagID, TagID], ...],
    parent_relations: dict[TagID, dict[TagID, RelationID]],
) -> Generator[tuple[LocationTagRelationPathSegment, ...], tuple[LocationTagRelationPathSegment, ...], None]:
    relations_by_id = {relation_id: LocationTagRelationTuple(ancestor_id, descendant_id)
                       for relation_id, ancestor_id, descendant_id in relevant_relations}

    # query all the paths we need
    # even chained paths should all be contained in here, since we have all the relations that "lead to" them
    relevant_paths_by_id: dict[RelationPathID, LocationTagRelationPathSegmentTuple] = {
        path_id: LocationTagRelationPathSegmentTuple(*path)
        for path_id, *path in LocationTagRelationPathSegment.objects.filter(
            relation_id__in=relations_by_id.keys()
        ).values_list(
            "pk", "prev_path_id", "adjacency_id", "relation_id", "num_hops", named=True
        )
    }

    created_relations_lookup = dict(created_relations)
    added_adjacencies_lookup: dict[tuple[TagID, TagID], AdjacencyID] = {
        (parent_id, child_id): pk for parent_id, child_id, pk in added_adjacencies
    }

    parent_relation_ids = set(
        chain(one_parent_relations.values() for one_parent_relations in parent_relations.values())
    )

    # build path chains
    path_ids_by_relation: dict[RelationID, set[RelationPathID]] = defaultdict(set)
    next_paths_for_path_id: dict[RelationPathID | None, set[RelationPathID]] = defaultdict(set)
    for path_id, path in relevant_paths_by_id.items():
        path_ids_by_relation[path.relation_id].add(path_id)
        if path.relation_id not in parent_relation_ids:
            next_paths_for_path_id[path.prev_path_id].add(path_id)

    paths_to_create, relations = unzip_paths_to_create(*chain(
        # for each new relation that spans just one of the added adjacencies, create the singular path segment
        ((
            LocationTagRelationPathSegment(
                prev_path_id=None,
                adjacency_id=added_adjacencies_lookup[parent, child],
                relation_id=created_relations_lookup[parent, child],
                num_hops=0
            ), (parent, child)
        ) for (parent, child), adjacency in added_adjacencies_lookup.items()),

        # for each new relation that ends with one of the added adjacencies, create the new last segment(s)
        chain.from_iterable((
            ((
                # the parent relation might have several paths, we continue all of them by one
                LocationTagRelationPathSegment(
                    prev_path_id=path_id,
                    adjacency_id=orig_adjacency_id,
                    relation_id=created_relations_lookup[ancestor, child],
                    num_hops=relevant_paths_by_id[path_id].num_hops + 1
                ), (parent, child)
            ) for path_id in path_ids_by_relation[parent_relation_id])
            for (ancestor, parent, child), orig_adjacency_id, parent_relation_id in chain.from_iterable(
                # generate sequence of new relation ancestor and descendant that shoulud have been added,
                # with adjacency id and relation id if of the parent
                (
                    ((ancestor, parent, child), adjacency_id, relation_id)
                    # for every added adjacency, iterate over the parent relations
                    for ancestor, relation_id in parent_relations[parent].items()
                )
                for (parent, child), adjacency_id in added_adjacencies_lookup.items()
            )
        ))
    ))
    created_paths = yield paths_to_create

    if len(created_paths) != len(paths_to_create):
        # this shouldn't happen
        raise ValueError

    if not next_paths_for_path_id:
        # we're done, only empty left
        yield ()
        return

    # get path segments to copy that have no predecessor
    # no predecessor implies: (ancestor, descendant) of its relation are (parent, child) of its adjacency
    # this is why we can use ancestor of the paths segments relation to get the parent of its adjacency
    first_paths_by_parent: dict[TagID, list[RelationPathID]] = {}
    for path_id in next_paths_for_path_id.pop(None, ()):
        first_paths_by_parent.setdefault(
            relations_by_id[relevant_paths_by_id[path_id].relation_id].ancestor, []
        ).append(path_id)

    # copy first path segments of the child's relations and connect them to the created paths segents
    paths_to_create, path_and_ancestor = unzip_paths_to_create(*chain.from_iterable(
        # continue each path we just created with the first path segments of all child relations
        ((
            (LocationTagRelationPathSegment(
                prev_path_id=prev_created_path.pk,
                # the adjacency is identical, since we are copying this path segment
                adjacency_id=path_to_copy.adjacency_id,
                # the relation is easy to look up, cause it's unique
                relation_id=created_relations_lookup[prev_ancestor, new_descendant],
                num_hops=path_to_copy.num_hops + prev_created_path.num_hops + 1
            ), (path_to_copy_id, prev_ancestor))
            for path_to_copy_id, path_to_copy, new_descendant in (
                (path_to_copy_id, path_to_copy, relations_by_id[path_to_copy.relation_id].descendant)
                for path_to_copy_id, path_to_copy in (
                    (path_to_copy_id, relevant_paths_by_id[path_to_copy_id])
                    for path_to_copy_id in first_paths_by_parent.get(prev_descendant, ())
                )
            )
        ) for prev_created_path, (prev_ancestor, prev_descendant) in zip(created_paths, relations))
    ))

    created_paths = yield paths_to_create

    if len(created_paths) != len(paths_to_create):
        # this shouldn't happen
        raise ValueError

    while paths_to_create:
        paths_to_create, path_and_ancestor = unzip_paths_to_create(*chain.from_iterable(
            # continue each path we just created with the next path segments
            ((
                (LocationTagRelationPathSegment(
                    prev_path_id=prev_created_path.pk,
                    # the adjacency is identical, since we are copying this path segment
                    adjacency_id=path_to_copy.adjacency_id,
                    # the relation is easy to look up, cause it's unique
                    relation_id=created_relations_lookup[prev_ancestor, new_descendant],
                    num_hops=prev_created_path.num_hops + 1
                ), (path_to_copy_id, prev_ancestor))
                for path_to_copy_id, path_to_copy, new_descendant in (
                    (path_to_copy_id, path_to_copy, relations_by_id[path_to_copy.relation_id].descendant)
                    for path_to_copy_id, path_to_copy in (
                        (path_to_copy_id, relevant_paths_by_id[path_to_copy_id])
                        for path_to_copy_id in next_paths_for_path_id[prev_copied_path]
                    )
                )
            ) for prev_created_path, (prev_copied_path, prev_ancestor) in zip(created_paths, path_and_ancestor))
        ))

        created_paths = yield paths_to_create

        if len(created_paths) != len(paths_to_create):
            # this shouldn't happen
            raise ValueError


class CircularyHierarchyError(IntegrityError):
    pass


def locationtag_adjacency_added(adjacencies: set[tuple[TagID, TagID]]):
    # get added adjacencies
    added_adjacencies: tuple[tuple[TagID, TagID, AdjacencyID], ...] = tuple(LocationTagAdjacency.objects.filter(  # noqa
        Q.create([Q(parent_id=parent, child_id=child) for parent, child in adjacencies], connector=Q.OR)
    ).values_list("parent_id", "child_id", "pk"))

    # generate sets of all parents and all childrens of the added adjacenties
    parents: frozenset[TagID]
    children: frozenset[TagID]
    parents, children = (frozenset(ids) for ids in zip(*adjacencies))

    # get all downwards relations to any of the parents or from any of the children
    relevant_relations: tuple[tuple[RelationID, TagID, TagID], ...] = tuple(  # noqa
        LocationTagRelation.objects.filter(
            Q(ancestor_id__in=children) | Q(descendant_id__in=parents)
        ).values_list(
            "pk", "ancestor_id", "descendant_id"
        )
    )

    # sort relations into what parents or children they end at
    parent_relations: dict[TagID, dict[TagID, RelationID]] = defaultdict(dict)
    child_relations: dict[TagID, dict[TagID, RelationID]] = defaultdict(dict)
    parent_for_child_relations: dict[RelationID, TagID] = {}
    for pk, ancestor_id, descendant_id in relevant_relations:
        if ancestor_id in children:
            child_relations[ancestor_id][descendant_id] = pk
            parent_for_child_relations[pk] = descendant_id
        elif descendant_id in parents:
            parent_relations[descendant_id][ancestor_id] = pk

        else:
            raise ValueError

    relations_to_create: frozenset[tuple[TagID, TagID]] = frozenset(chain.from_iterable((
        chain(
            product(parent_relations[parent].keys(), child_relations[child].keys()),
            product(parent_relations[parent].keys(), (child, )),
            product((parent, ), child_relations[child].keys()),
        )
        for parent, child in adjacencies
    ))) | adjacencies
    if any((ancestor == descendant) for ancestor, descendant in relations_to_create):
        raise CircularyHierarchyError("Circular relations are now allowed")

    already_existing_relations: tuple[tuple[tuple[TagID, TagID], RelationID], ...] = tuple((
        ((ancestor_id, descendant_id), pk) for ancestor_id, descendant_id, pk in LocationTagRelation.objects.filter(
            # todo: more performant with index?
            Q.create([Q(ancestor_id=ancestor, descendant_id=descendant)
                      for ancestor, descendant in relations_to_create], Q.OR)
        ).values_list("ancestor_id", "descendant_id", "pk")
    ))
    if already_existing_relations:
        relations_to_create -= frozenset(tuple(zip(*already_existing_relations))[0])
    relations_to_create: tuple[tuple[TagID, TagID], ...] = tuple(relations_to_create)

    created_relations_ids: tuple[tuple[tuple[TagID, TagID], RelationID], ...] = tuple(
        ((created_relation.ancestor_id, created_relation.descendant_id), created_relation.id)
        for created_relation in LocationTagRelation.objects.bulk_create((
            LocationTagRelation(ancestor_id=ancestor, descendant_id=descendant)
            for ancestor, descendant in relations_to_create
        ))
    )

    # check that we really got as many relations back as we put into bulk_create()
    if len(created_relations_ids) != len(relations_to_create):
        raise ValueError ("location_hierarchy_changed post_add handler bulk_insert len() mismatch")

    # create new paths
    it = generate_paths_to_create(
        created_relations=already_existing_relations + created_relations_ids,
        added_adjacencies=added_adjacencies,
        relevant_relations=relevant_relations,
        parent_relations=parent_relations,
    )
    paths_to_create = next(it)
    while paths_to_create:
        created_paths = LocationTagRelationPathSegment.objects.bulk_create(paths_to_create)
        paths_to_create = it.send(tuple(created_paths))


def locationtag_parents_removed(instance: LocationTag, pk_set: set[int]):
    """
    parents were removed from the location
    """
    # get removed adjacencies, this is why we do this before
    LocationTagRelation.objects.annotate(count=Count("paths")).filter(descendant_id=instance.pk, count=0).delete()

    # notify changed geometries… todo: this should definitely use the descendants thing
    instance.register_changed_geometries(force=True)


def locationtag_children_removed(instance: LocationTag, pk_set: set[int] = None):
    """
    children were removed from the location
    """
    if pk_set is None:
        # todo: this is a hack, can be done nicer
        pk_set = set(LocationTagRelation.objects.filter(ancestor_id=instance.pk).values_list("pk", flat=True))

    LocationTagRelation.objects.annotate(count=Count("paths")).filter(ancestor_id=instance.pk, count=0).delete()

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

    @cached_property
    def sorted_tags(self) -> MapPermissionGuardedSequence[LocationTag]:
        """
        highest priority first
        """
        if "tags" not in getattr(self, '_prefetched_objects_cache', ()):
            raise ValueError(f'Accessing sorted_tags on {self} despite no prefetch_related.')
            # return LazyMapPermissionFilteredSequence(())
        # noinspection PyUnresolvedReferences
        return MapPermissionGuardedSequence(sorted(self.tags.all(), key=attrgetter("effective_depth_first_post_order")))

    @property
    def title(self) -> str:
        # todo: precalculate
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
