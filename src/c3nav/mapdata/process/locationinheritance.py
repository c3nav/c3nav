import operator
from functools import reduce
from itertools import chain
from typing import Sequence

from django.conf import settings
from django.db.models import Q
from django.db.models.expressions import F, OuterRef, Subquery, When, Case, Value
from django.db.models.query import Prefetch
from django.utils import translation

from c3nav.mapdata.models.locations import FillAndBorderColor, ColorByTheme, LocationTag, StaticLocationTagTarget, \
    LocationTagRelation
from c3nav.mapdata.permissions import MapPermissionTaggedItem


def calculate_locationtag_effective_x(name: str, default=..., null=...):
    output_field = LocationTag._meta.get_field(f"effective_{name}")
    LocationTag.objects.annotate(**{
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


def _locationtag_bulk_cached_update[T](name: str, values: Sequence[tuple[set[int], T]], default: T):
    output_field = LocationTag._meta.get_field(name)
    LocationTag.objects.annotate(
        **{f"new_{name}": Case(
            *(When(pk__in=pks, then=Value(value, output_field=output_field)) for pks, value in values),
            default=Value(default, output_field=output_field),
        )}
    ).update(**{name: F(f"new_{name}")})


def calculate_cached_effective_color():
    # collect ids for each value so we can later bulk-update
    colors: dict[tuple[tuple[int, FillAndBorderColor], ...], set[int]] = {}
    for tag in LocationTag.objects.prefetch_related(
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

    _locationtag_bulk_cached_update(
        name="cached_effective_colors",
        values=tuple((pks, dict(colors)) for colors, pks in colors.items()),
        default={}
    )


def calculate_cached_describing_titles():
    all_describing_titles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
    for tag in LocationTag.objects.prefetch_related(
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
    _locationtag_bulk_cached_update(
        name="cached_describing_titles",
        values=tuple(
            (pks, [
                MapPermissionTaggedItem(value=dict(titles), access_restrictions=restrictions)
                for titles, restrictions in entries
            ]) for entries, pks in all_describing_titles.items()
        ),
        default=[]
    )


def recalculate_locationtag_cached_from_parents():
    calculate_locationtag_effective_x("icon")
    calculate_locationtag_effective_x("external_url_labels", default={}, null={})
    calculate_locationtag_effective_x("label_settings")
    calculate_cached_effective_color()
    calculate_cached_describing_titles()


def recalculate_minimum_access_restrictions():
    all_minimum_access_restrictions: dict[tuple[int, ...], set[int]] = {}
    from c3nav.mapdata.models import Level, Space, Area, POI
    for tag in LocationTag.objects.prefetch_related(
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
    _locationtag_bulk_cached_update(
        name="effective_minimum_access_restrictions",
        values=tuple(
            (pks, frozenset(minimum_access_restrictions))
            for minimum_access_restrictions, pks in all_minimum_access_restrictions.items()
        ),
        default=frozenset()
    )


def recalculate_all_static_targets():
    all_static_target_ids: dict[tuple[tuple[tuple[str, int], frozenset[int]], ...], set[int]] = {}
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


def recalculate_all_position_secrets():
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


def recalculate_target_subtitles():
    # todo: make this work better for multiple targets
    all_target_subtitles: dict[tuple[tuple[tuple[tuple[str, str], ...], frozenset[int]], ...], set[int]] = {}
    for obj in LocationTag.objects.prefetch_related("levels",
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