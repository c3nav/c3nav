from collections import deque, defaultdict
from dataclasses import dataclass, replace as dataclass_replace
from itertools import chain
from operator import itemgetter
from typing import Sequence, NamedTuple, Self, Callable, Union

from django.conf import settings
from django.db.models.expressions import F, When, Case, Value, Exists, OuterRef
from django.db.models.query import Prefetch
from django.utils import translation

from c3nav.mapdata.models.geometry.base import CachedBounds
from c3nav.mapdata.models.locations import FillAndBorderColor, LocationTag, StaticLocationTagTarget, \
    CachedBoundsByLevel, CachedGeometriesByLevel, MaskedLocationTagGeometry, LocationTagInheritedValues, \
    CircularHierarchyError, LocationTagEffectiveAccessRestrictionSet, LocationTagTargetInheritedValues
from c3nav.mapdata.permissions import MapPermissionTaggedItem, AccessRestrictionsAllIDs, AccessRestrictionsEval, \
    NoAccessRestrictions, AccessRestrictionsOneID, InifiniteAccessRestrictions


@dataclass
class InheritedValues:
    ancestor_path: tuple[int, ...] = ()
    access_restriction_path: tuple[int | None, ...] = ()

    icon: str | None = None
    label_settings: int | None = None
    external_url_label: dict | None = None
    describing_title: dict | None = None
    colors: dict[int, FillAndBorderColor] | None = None
    access_restrictions: AccessRestrictionsEval = NoAccessRestrictions


class MultipleTagInheritedValues(NamedTuple):
    icon: tuple[MapPermissionTaggedItem[str], ...] = ()
    label_settings: tuple[MapPermissionTaggedItem[int], ...] = ()
    external_url_label: tuple[MapPermissionTaggedItem[dict], ...] = ()
    describing_title: tuple[MapPermissionTaggedItem[dict], ...] = ()
    colors: dict[int, tuple[MapPermissionTaggedItem[FillAndBorderColor], ...]] | None = None

    @staticmethod
    def _append[T](self_items: tuple[MapPermissionTaggedItem[T], ...],
                   value: T, access_restrictions: AccessRestrictionsEval) -> tuple[MapPermissionTaggedItem[T], ...]:
        if value is None or any((access_restrictions <= item.access_restrictions) for item in self_items):
            return self_items
        return (
            *self_items,
            MapPermissionTaggedItem(value, access_restrictions),
        )

    def append(self, item: InheritedValues) -> Self:
        self_colors = (self.colors or {})
        other_colors = (item.colors or {})
        return MultipleTagInheritedValues(
            icon=self._append(self.icon, item.icon, item.access_restrictions),
            label_settings=self._append(self.label_settings, item.label_settings, item.access_restrictions),
            external_url_label=self._append(self.external_url_label, item.external_url_label, item.access_restrictions),
            describing_title=self._append(self.describing_title, item.describing_title, item.access_restrictions),
            colors={
                theme: self._append(self_colors.get(theme, ()), other_colors.get(theme, None), item.access_restrictions)
                for theme in set(self_colors.keys()) | set(other_colors.keys())
            },
        )


def _ancestry_paths_to_ids(
    paths: Sequence[MapPermissionTaggedItem[tuple[int, ...]]],
    getter: Callable[[tuple[int, ...],], int],
) -> list[MapPermissionTaggedItem[int]]:
    return [
        MapPermissionTaggedItem(getter(item.value), access_restrictions=item.access_restrictions)
        for item in paths
    ]


def recalculate_locationtag_effective_inherited_values():
    # todo: how cool would it be if this thing new which parts of the location graph actually needed to be re-done?
    tags_by_id: dict[int, LocationTag] = {}
    next_tags: deque[tuple[int, frozenset[int], InheritedValues]] = deque()

    from c3nav.mapdata.models import Level, Space, Area, POI
    for tag in LocationTag.objects.without_inherited().only(
            "pk", "access_restriction_id",
            "icon", "color", "label_settings_id", "external_url_label", "titles", "can_describe",
    ).order_by("-priority", "pk").prefetch_related(
            Prefetch("children", LocationTag.objects.order_by("-priority", "pk")),
            "levels", "spaces", "areas", "pois", "theme_colors",
    ).annotate(no_parents=~Exists(LocationTag.objects.filter(children=OuterRef("pk")))):
        tags_by_id[tag.pk] = tag
        if tag.no_parents:
            next_tags.append((tag.pk, frozenset({tag.pk}), InheritedValues()))

    color_order = 0

    result_for_tags: dict[int, MultipleTagInheritedValues] = {}
    restrictions_for_tags: dict[int, AccessRestrictionsEval] = defaultdict(lambda: InifiniteAccessRestrictions)
    ancestor_paths_for_tags: dict[int, dict[tuple[int, ...], MapPermissionTaggedItem[tuple[int, ...]]]] = defaultdict(dict)
    descendant_paths_for_tags: dict[int, dict[tuple[int, ...], MapPermissionTaggedItem[tuple[int, ...]]]] = defaultdict(dict)
    color_order_for_tags: dict[int, int | None] = {}
    public_tags: set[int] = set()
    not_done_tags = set(tags_by_id.keys())

    known_targets: dict[tuple[str, int], Union[Level, Space, Area, POI]] = {}
    tags_for_targets: dict[tuple[str, int], deque[MapPermissionTaggedItem[int]]] = defaultdict(deque)

    while next_tags:
        tag_id, tags_so_far, values_so_far = next_tags.popleft()
        tag = tags_by_id[tag_id]
        not_done_tags.discard(tag_id)

        ancestor_path = values_so_far.ancestor_path + (tag_id,)
        access_restrictions = (
            values_so_far.access_restrictions &
            AccessRestrictionsOneID.build(tag.access_restriction_id)
        )

        for i, ancestor_id in enumerate(values_so_far.ancestor_path):
            ancestor_paths_for_tags[tag_id][values_so_far.ancestor_path[i:]] = MapPermissionTaggedItem(
                values_so_far.ancestor_path[i:],
                access_restrictions=AccessRestrictionsAllIDs.build(values_so_far.access_restriction_path[i:]),
            )
            descendant_paths_for_tags[ancestor_id][ancestor_path[i+1:]] = MapPermissionTaggedItem(
                ancestor_path[i+1:],
                access_restrictions=AccessRestrictionsAllIDs.build(values_so_far.access_restriction_path[i+1:]),
            )

        if not access_restrictions:
            public_tags.add(tag_id)
            restrictions_for_tags.pop(tag_id, None)
        elif tag_id not in public_tags:
            restrictions_for_tags[tag_id] |= access_restrictions

        has_colors = tag.color or tag.theme_colors.all()
        color_order_for_tags.setdefault(tag_id, color_order)

        values_so_far = dataclass_replace(
            values_so_far,
            ancestor_path=ancestor_path,
            icon=(tag.icon or "").strip() or values_so_far.icon,
            label_settings=tag.label_settings_id or values_so_far.label_settings,
            external_url_label=tag.external_url_labels or values_so_far.external_url_label,
            colors={
                **(values_so_far.colors or {}),
                **({
                    **{theme_color.theme_id: FillAndBorderColor(order=color_order,
                                                                fill=theme_color.fill_color,
                                                                border=theme_color.border_color)
                       for theme_color in tag.theme_colors.all()},
                    **({0: FillAndBorderColor(order=color_order, fill=tag.color, border=None)}
                       if tag.color else {}),
                } if has_colors else {})
            } or None,
            access_restrictions=access_restrictions,
            access_restriction_path=values_so_far.access_restriction_path + (tag.access_restriction_id, )
        )

        result_for_tags[tag_id] = result_for_tags.get(tag_id, MultipleTagInheritedValues()).append(values_so_far)

        if tag.titles and tag.can_describe:
            values_so_far = dataclass_replace(
                values_so_far,
                describing_title=tag.titles,
            )

        for target in chain(tag.levels.all(), tag.spaces.all(), tag.areas.all(), tag.pois.all()):
            key = (target._meta.model_name, target.pk)
            known_targets[key] = target
            tags_for_targets[key].append(MapPermissionTaggedItem(tag_id, access_restrictions))

        for child in reversed(tag.children.all()):
            if child.pk in tags_so_far:
                raise CircularHierarchyError
            next_tags.appendleft((child.pk, tags_so_far | {child.pk}, values_so_far))

    if not_done_tags:
        raise CircularHierarchyError

    # todo: improve this, only update what's needed etc?
    LocationTagInheritedValues.objects.bulk_create(
        [
            LocationTagInheritedValues(
                tag_id=tag_id,
                icon=list(values.icon),
                label_settings_id=list(values.label_settings),
                external_url_label=list(values.external_url_label),
                describing_title=list(values.describing_title),
                colors={theme_id: list(colors) for theme_id, colors in (values.colors or {}).items()},

                ancestor_paths=list(ancestor_paths_for_tags[tag_id].values()),
                ancestors=_ancestry_paths_to_ids(list(ancestor_paths_for_tags[tag_id].values()), itemgetter(0)),
                descendant_paths=list(descendant_paths_for_tags[tag_id].values()),
                descendants=_ancestry_paths_to_ids(list(descendant_paths_for_tags[tag_id].values()), itemgetter(-1)),
            ) for tag_id, values in result_for_tags.items()
        ],
        update_conflicts=True,
        update_fields=(
            "icon",
            "label_settings_id",
            "external_url_label",
            "describing_title",
            "colors",
            "ancestors",
            "ancestor_paths",
            "descendants",
            "descendant_paths",
        ),
        unique_fields=("tag_id", )
    )
    LocationTagInheritedValues.objects.exclude(tag_id__in=result_for_tags.keys()).delete()

    # todo: improve this in a similar way
    new_target_inherited_values = []
    for target_key, tags in tags_for_targets.items():
        target = known_targets[target_key]
        tags = list(tags)
        new_colors: dict[int, list[MapPermissionTaggedItem[FillAndBorderColor]]] = defaultdict(list)
        for tag_item in tags:
            for theme_id, theme_colors in result_for_tags[tag_item.value].colors.items():
                new_theme_colors = new_colors[theme_id]
                for new_color in theme_colors:
                    new_item = MapPermissionTaggedItem(
                        new_color.value,
                        access_restrictions=(
                            tag_item.access_restrictions
                            & new_color.access_restrictions
                            & AccessRestrictionsOneID.build(target.access_restriction_id)
                        ),
                    )
                    if any((color.access_restrictions <= new_item.access_restrictions) for color in new_theme_colors):
                        continue
                    new_theme_colors.append(new_item)
        if target.has_inherited:
            tags_changed = (tags != target.inherited.tags)
            colors_changed = (new_colors != target.inherited.colors)
        else:
            tags_changed = True
            colors_changed = True
        if tags_changed or colors_changed:
            new_target_inherited_values.append(
                LocationTagTargetInheritedValues(
                    **{f"{target_key[0]}_id": target_key[1]},
                    tags=list(tags),
                    colors=dict(new_colors),
                )
            )
        if colors_changed and not isinstance(target, Level):
            target.register_change(force=True)

    LocationTagTargetInheritedValues.objects.exclude(
        pk__in=[target.inherited.pk for target in known_targets.values() if target.has_inherited]
    ).delete()
    LocationTagTargetInheritedValues.objects.bulk_create(
        new_target_inherited_values,
        update_conflicts=True,
        update_fields=("tags", "colors"),
        unique_fields=("level", "space", "area", "poi"),
    )

    # todo: improve this as well…?
    existing_restriction_set_id_to_tag = dict(
        LocationTagEffectiveAccessRestrictionSet.objects.values_list("pk", "tag")
    )
    restrictions_per_existing_set = {set_id: set() for set_id in existing_restriction_set_id_to_tag.keys()}

    m2m_qs = LocationTagEffectiveAccessRestrictionSet.access_restrictions.through.objects.values_list(
        "locationtageffectiveaccessrestrictionset_id",
        "accessrestriction_id",
    )
    for set_id, restriction_id in m2m_qs:
        restrictions_per_existing_set.get(set_id, set()).add(restriction_id)

    set_by_tag_and_restrictions: dict[tuple[int, frozenset[int]], int] = {}
    for set_id, restrictions in restrictions_per_existing_set.items():
        set_by_tag_and_restrictions[(existing_restriction_set_id_to_tag[set_id], frozenset(restrictions))] = set_id

    remaining_set_ids: set[int] = set(existing_restriction_set_id_to_tag.keys())
    sets_to_create: deque[tuple[int, frozenset[int]]] = deque()
    for tag_id, expected_restrictions in restrictions_for_tags.items():
        for expected_set in expected_restrictions.flatten():
            set_id = set_by_tag_and_restrictions.get((tag_id, expected_set), None)
            if set_id is None:
                sets_to_create.append((tag_id, expected_set))
            else:
                remaining_set_ids.discard(set_id)

    if sets_to_create:
        create_set_tag_ids, create_set_restrictions = zip(*sets_to_create)

        created_tag_ids: tuple[int, ...] = tuple(
            created_set.pk for created_set in LocationTagEffectiveAccessRestrictionSet.objects.bulk_create(tuple(
                LocationTagEffectiveAccessRestrictionSet(tag_id=tag_id) for tag_id in create_set_tag_ids
            ))
        )
        LocationTagEffectiveAccessRestrictionSet.access_restrictions.through.objects.bulk_create(tuple(chain.from_iterable(
            (
                LocationTagEffectiveAccessRestrictionSet.access_restrictions.through(
                    locationtageffectiveaccessrestrictionset_id=set_id,
                    accessrestriction_id=access_restriction_id,
                )
                for access_restriction_id in expected_access_restrictions
            ) for set_id, expected_access_restrictions in zip(created_tag_ids, create_set_restrictions)
        )))
    LocationTagEffectiveAccessRestrictionSet.objects.filter(pk__in=remaining_set_ids).delete()


def _locationtag_bulk_cached_update[T](name: str, values: Sequence[tuple[set[int], T]], default: T):
    output_field = LocationTag._meta.get_field(name)
    LocationTag.objects.annotate(
        **{f"new_{name}": Case(
            *(When(pk__in=pks, then=Value(value, output_field=output_field)) for pks, value in values),
            default=Value(default, output_field=output_field),
        )}
    ).update(**{name: F(f"new_{name}")})


def recalculate_locationtag_all_static_targets():
    all_static_target_ids: dict[tuple[tuple[tuple[str, int], AccessRestrictionsEval], ...], set[int]] = {}
    for obj in LocationTag.objects.prefetch_related("levels", "spaces__level",
                                                    "areas__space__level", "pois__space__level"):
        all_static_target_ids.setdefault(tuple(sorted(
            ((target._meta.model_name, target.pk), target.effective_access_restrictions)
            for target in obj.static_targets
        )), set()).add(obj.pk)

    _locationtag_bulk_cached_update(
        name="cached_all_static_targets",
        values=tuple(
            (pks, [
                MapPermissionTaggedItem(value=value, access_restrictions=restrictions)
                for value, restrictions in entries
            ]) for entries, pks in all_static_target_ids.items()
        ),
        default=[]
    )


def recalculate_locationtag_all_position_secrets():
    all_position_secrets: dict[tuple[str, ...], set[int]] = {}

    for obj in LocationTag.objects.prefetch_related("dynamic_targets"):
        all_position_secrets.setdefault(tuple(sorted(
            target.position_secret for target in obj.dynamic_targets.all()
        )), set()).add(obj.pk)

    _locationtag_bulk_cached_update(
        name="cached_all_position_secrets",
        values=tuple((pks, list(secrets)) for secrets, pks in all_position_secrets.items()),
        default=[]
    )


def recalculate_locationtag_target_subtitles():
    # todo: make this work better for multiple targets
    all_target_subtitles: dict[tuple[tuple[tuple[tuple[str, str], ...], AccessRestrictionsEval], ...], set[int]] = {}
    for obj in LocationTag.objects.prefetch_related("levels",
                                            "spaces__level", "spaces__tags", "spaces__level__tags",
                                            "areas__space__tags", "areas__space__level__tags",
                                            "pois__space__tags", "pois__space__level", "dynamic_targets"):
        obj: LocationTag
        tag_target_subtitles: list[tuple[tuple[tuple[str, str], ...], AccessRestrictionsEval]] = []
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

    _locationtag_bulk_cached_update(
        name="cached_target_subtitles",
        values=tuple(
            (pks, [
                MapPermissionTaggedItem(value=dict(titles), access_restrictions=restrictions)
                for titles, restrictions in entries
            ]) for entries, pks in all_target_subtitles.items()
        ),
        default=[]
    )


def recalculate_locationtag_points():
    for obj in LocationTag.objects.with_restrictions().prefetch_related(
            "levels", "spaces__level", "areas__space__level", "pois__space__level"
    ):
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


def recalculate_locationtag_bounds():
    for obj in LocationTag.objects.with_restrictions().prefetch_related("levels", "spaces__level",
                                                                        "areas__space__level", "pois__space__level"):
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


def recalculate_locationtag_geometries():
    for tag in LocationTag.objects.with_restrictions().prefetch_related("levels", "spaces__level",
                                                                        "areas__space__level", "pois__space__level",
                                                                        "levels__tags", "spaces__tags",
                                                                        "areas__tags", "pois__tags",):
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