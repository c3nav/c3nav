from dataclasses import dataclass
from itertools import chain
from typing import TYPE_CHECKING, Sequence

from django.db.models import Prefetch, Q
from shapely import prepared
from shapely.ops import unary_union

from c3nav.api.exceptions import API404, APIPermissionDenied
from c3nav.editor.utils import LevelChildEditUtils, SpaceChildEditUtils
from c3nav.mapdata.models import Level, Space, GraphNode, Door, LocationGroup, Building, GraphEdge, DataOverlayFeature
from c3nav.mapdata.models.geometry.space import Column, Hole, AltitudeMarker, BeaconMeasurement, RangingBeacon, Area, \
    POI
from c3nav.mapdata.utils.geometry import unwrap_geom


def space_sorting_func(space):
    groups = tuple(space.groups.all())
    if not groups:
        return (0, 0, 0)
    return (1, groups[0].category.priority, groups[0].hierarchy, groups[0].priority)


def _get_geometries_for_one_level(level):
    buildings = level.buildings.all()
    buildings_geom = unary_union([unwrap_geom(building.geometry) for building in buildings])
    spaces = {space.pk: space for space in level.spaces.all()}
    holes_geom = []
    for space in spaces.values():
        if space.outside:
            space.geometry = space.geometry.difference(buildings_geom)
        columns = [column.geometry for column in space.columns.all()]
        if columns:
            columns_geom = unary_union([unwrap_geom(column.geometry) for column in space.columns.all()])
            space.geometry = space.geometry.difference(columns_geom)
        holes = [unwrap_geom(hole.geometry) for hole in space.holes.all()]
        if holes:
            space_holes_geom = unary_union(holes)
            holes_geom.append(space_holes_geom.intersection(unwrap_geom(space.geometry)))
            space.geometry = space.geometry.difference(space_holes_geom)

    for building in buildings:
        building.original_geometry = building.geometry

    if holes_geom:
        holes_geom = unary_union(holes_geom)
        holes_geom_prep = prepared.prep(holes_geom)
        for obj in buildings:
            if holes_geom_prep.intersects(unwrap_geom(obj.geometry)):
                obj.geometry = obj.geometry.difference(holes_geom)

    results = []
    results.extend(buildings)
    for door in level.doors.all():
        results.append(door)

    results.extend(sorted(spaces.values(), key=space_sorting_func))

    results.extend(level.data_overlay_features.all())

    return results


@dataclass(slots=True)
class LevelsForLevel:
    levels: Sequence[int]  # IDs of all levels to render for this level, in order, including the level itself
    levels_on_top: Sequence[int]  # IDs of levels that are on top of this level (on_top_of field)
    levels_under: Sequence[int]  # IDs of the level below this level plus levels on top of it (on_top_of field)

    @classmethod
    def for_level(cls, request, level: Level, special_if_on_top=False):  # add typing
        # noinspection PyPep8Naming
        levels_under = ()
        levels_on_top = ()
        lower_level = level.lower(Level).first()
        primary_levels = (level,) + ((lower_level,) if lower_level else ())
        secondary_levels = Level.objects.filter(on_top_of__in=primary_levels).values_list('pk', 'on_top_of')
        if lower_level:
            levels_under = tuple(pk for pk, on_top_of in secondary_levels if on_top_of == lower_level.pk)
        if True:
            levels_on_top = tuple(pk for pk, on_top_of in secondary_levels if on_top_of == level.pk)

        levels = tuple(chain([level.pk], levels_under, levels_on_top))

        if special_if_on_top and level.on_top_of_id is not None:
            levels = tuple(chain([level.pk], levels_on_top))
            levels_under = (level.on_top_of_id, )
            levels_on_top = ()

        return cls(
            levels=levels,
            levels_under=levels_under,
            levels_on_top=levels_on_top,
        )


def area_sorting_func(area):
    groups = tuple(area.groups.all())
    if not groups:
        return (0, 0, 0)
    return (1, groups[0].category.priority, groups[0].hierarchy, groups[0].priority)


def conditional_geojson(obj, update_cache_key_match):
    if update_cache_key_match and not obj._affected_by_changeset:
        return obj.get_geojson_key()

    result = obj.to_geojson()
    result['properties']['changed'] = obj._affected_by_changeset
    return result


# noinspection PyPep8Naming
def get_level_geometries_result(request, level_id: int, update_cache_key: str, update_cache_key_match: True):
    try:
        level = Level.objects.filter(Level.q_for_request(request)).get(pk=level_id)
    except Level.DoesNotExist:
        raise API404('Level not found')

    edit_utils = LevelChildEditUtils(level, request)  # todo: what's happening here?
    if not edit_utils.can_access_child_base_mapdata:
        raise APIPermissionDenied()

    levels_for_level = LevelsForLevel.for_level(request, level)
    # don't prefetch groups for now as changesets do not yet work with m2m-prefetches
    levels = Level.objects.filter(pk__in=levels_for_level.levels).filter(Level.q_for_request(request))
    graphnodes_qs = GraphNode.objects.all()
    levels = levels.prefetch_related(
        Prefetch('spaces', Space.objects.filter(Space.q_for_request(request)).only(
            'geometry', 'level', 'outside'
        )),
        Prefetch('doors', Door.objects.filter(Door.q_for_request(request)).only('geometry', 'level')),
        Prefetch('spaces__columns', Column.objects.filter(
            Q(access_restriction__isnull=True) | ~Column.q_for_request(request)
        ).only('geometry', 'space')),
        Prefetch('spaces__groups', LocationGroup.objects.only(
            'color', 'category', 'priority', 'hierarchy', 'category__priority', 'category__allow_spaces'
        )),
        Prefetch('buildings', Building.objects.only('geometry', 'level')),
        Prefetch('spaces__holes', Hole.objects.only('geometry', 'space')),
        Prefetch('spaces__altitudemarkers', AltitudeMarker.objects.only('geometry', 'space')),
        Prefetch('spaces__beacon_measurements', BeaconMeasurement.objects.only('geometry', 'space')),
        Prefetch('spaces__ranging_beacons', RangingBeacon.objects.only('geometry', 'space')),
        Prefetch('spaces__graphnodes', graphnodes_qs),
        Prefetch('data_overlay_features', DataOverlayFeature.objects.only('geometry', 'overlay_id', 'level'))
    )

    levels = {s.pk: s for s in levels}

    level = levels[level.pk]
    levels_under = [levels[pk] for pk in levels_for_level.levels_under]
    levels_on_top = [levels[pk] for pk in levels_for_level.levels_on_top]

    # todo: permissions?
    graphnodes = tuple(chain(*(space.graphnodes.all()
                               for space in chain(*(level.spaces.all() for level in levels.values())))))
    graphnodes_lookup = {node.pk: node for node in graphnodes}

    graphedges = GraphEdge.objects.all()
    graphedges = graphedges.filter(Q(from_node__in=graphnodes) | Q(to_node__in=graphnodes))
    graphedges = graphedges.select_related('waytype', 'from_node', 'to_node')

    # this is faster because we only deserialize graphnode geometries once
    missing_graphnodes = graphnodes_qs.filter(pk__in=set(chain(*((edge.from_node_id, edge.to_node_id)
                                                                 for edge in graphedges))))
    graphnodes_lookup.update({node.pk: node for node in missing_graphnodes})
    for edge in graphedges:
        edge._from_node_cache = graphnodes_lookup[edge.from_node_id]
        edge._to_node_cache = graphnodes_lookup[edge.to_node_id]

    graphedges = [edge for edge in graphedges if edge.from_node.space_id != edge.to_node.space_id]

    results = chain(
        *(_get_geometries_for_one_level(level) for level in levels_under),
        _get_geometries_for_one_level(level),
        *(_get_geometries_for_one_level(level) for level in levels_on_top),
        *(space.altitudemarkers.all() for space in level.spaces.all()),
        *(space.beacon_measurements.all() for space in level.spaces.all()),
        *(space.ranging_beacons.all() for space in level.spaces.all()),
        graphedges,
        graphnodes,
    )

    return list(chain(
        [('update_cache_key', update_cache_key)],
        (conditional_geojson(obj, update_cache_key_match) for obj in results)
    ))


def get_space_geometries_result(request, space_id: int, update_cache_key: str, update_cache_key_match: bool):
    space_q_for_request = Space.q_for_request(request)
    qs = Space.objects.filter(space_q_for_request)

    try:
        space = qs.select_related('level', 'level__on_top_of').get(pk=space_id)
    except Space.DoesNotExist:
        raise API404('space not found')

    level = space.level

    edit_utils = SpaceChildEditUtils(space, request)
    if not edit_utils.can_access_child_base_mapdata:
        raise APIPermissionDenied

    if request.user_permissions.can_access_base_mapdata:
        doors = [door for door in level.doors.filter(Door.q_for_request(request)).all()
                 if unwrap_geom(door.geometry).intersects(unwrap_geom(space.geometry))]
        doors_space_geom = unary_union(
            [unwrap_geom(door.geometry) for door in doors] +
            [unwrap_geom(space.geometry)]
        )

        levels_for_level = LevelsForLevel.for_level(request, level.primary_level, special_if_on_top=True)
        other_spaces = Space.objects.filter(space_q_for_request, level__pk__in=levels_for_level.levels).only(
            'geometry', 'level'
        ).prefetch_related(
            Prefetch('groups', LocationGroup.objects.only(
                'color', 'category', 'priority', 'hierarchy', 'category__priority', 'category__allow_spaces'
            ).filter(color__isnull=False))
        )

        space = next(s for s in other_spaces if s.pk == space.pk)
        other_spaces = [s for s in other_spaces
                        if s.geometry.intersects(doors_space_geom) and s.pk != space.pk]
        all_other_spaces = other_spaces

        other_spaces_lower = [s for s in other_spaces if s.level_id in levels_for_level.levels_under]
        other_spaces_upper = [s for s in other_spaces if s.level_id in levels_for_level.levels_on_top]
        other_spaces = [s for s in other_spaces if s.level_id == level.pk]

        space.bounds = True

        # deactivated for performance reasons
        buildings = level.buildings.all()
        # buildings_geom = unary_union([building.geometry for building in buildings])
        # for other_space in other_spaces:
        #     if other_space.outside:
        #         other_space.geometry = other_space.geometry.difference(buildings_geom)
        for other_space in chain(other_spaces, other_spaces_lower, other_spaces_upper):
            other_space.opacity = 0.4
            other_space.color = '#ffffff'
        for building in buildings:
            building.opacity = 0.5
    else:
        buildings = []
        doors = []
        other_spaces = []
        other_spaces_lower = []
        other_spaces_upper = []
        all_other_spaces = []

    # todo: permissions
    if request.user_permissions.can_access_base_mapdata:
        graph_nodes = GraphNode.objects.all()
        graph_nodes = graph_nodes.filter((Q(space__in=all_other_spaces)) | Q(space__pk=space.pk))

        space_graph_nodes = tuple(node for node in graph_nodes if node.space_id == space.pk)

        graph_edges = GraphEdge.objects.all()
        space_graphnodes_ids = tuple(node.pk for node in space_graph_nodes)
        graph_edges = graph_edges.filter(Q(from_node__pk__in=space_graphnodes_ids) |
                                         Q(to_node__pk__in=space_graphnodes_ids))
        graph_edges = graph_edges.select_related('from_node', 'to_node', 'waytype').only(
            'from_node__geometry', 'to_node__geometry', 'waytype__color'
        )
    else:
        graph_nodes = []
        graph_edges = []

    areas = space.areas.filter(Area.q_for_request(request)).only(
        'geometry', 'space'
    ).prefetch_related(
        Prefetch('groups', LocationGroup.objects.order_by(
            '-category__priority', '-hierarchy', '-priority'
        ).only(
            'color', 'category', 'priority', 'hierarchy', 'category__priority', 'category__allow_areas'
        ))
    )
    for area in areas:
        area.opacity = 0.5
    areas = sorted(areas, key=area_sorting_func)

    results = chain(
        buildings,
        other_spaces_lower,
        doors,
        other_spaces,
        [space],
        areas,
        space.holes.all().only('geometry', 'space'),
        space.stairs.all().only('geometry', 'space'),
        space.ramps.all().only('geometry', 'space'),
        space.obstacles.all().only('geometry', 'space').prefetch_related('group'),
        space.lineobstacles.all().only('geometry', 'width', 'space').prefetch_related('group'),
        space.columns.all().only('geometry', 'space'),
        space.altitudemarkers.all().only('geometry', 'space'),
        space.beacon_measurements.all().only('geometry', 'space'),
        space.ranging_beacons.all().only('geometry', 'space'),
        space.pois.filter(POI.q_for_request(request)).only('geometry', 'space').prefetch_related(
            Prefetch('groups', LocationGroup.objects.only(
                'color', 'category', 'priority', 'hierarchy', 'category__priority', 'category__allow_pois'
            ).filter(color__isnull=False))
        ),
        other_spaces_upper,
        graph_edges,
        graph_nodes
    )

    return list(chain(
        [('update_cache_key', update_cache_key)],
        (conditional_geojson(obj, update_cache_key_match) for obj in results)
    ))
