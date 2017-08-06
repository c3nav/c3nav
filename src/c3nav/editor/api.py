from itertools import chain

from django.db.models import Prefetch, Q
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet
from shapely.ops import cascaded_union

from c3nav.editor.models import ChangeSet
from c3nav.mapdata.models import Area, Door, Source
from c3nav.mapdata.models.geometry.space import POI


class EditorViewSet(ViewSet):
    """
    Editor API
    /geometries/ returns a list of geojson features, you have to specify ?level=<id> or ?space=<id>
    /geometrystyles/ returns styling information for all geometry types
    /bounds/ returns the maximum bounds of the map
    """
    @staticmethod
    def _get_level_geometries(level):
        buildings = level.buildings.all()
        buildings_geom = cascaded_union([building.geometry for building in buildings])
        spaces = {space.pk: space for space in level.spaces.all()}
        holes_geom = []
        for space in spaces.values():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)
            columns_geom = cascaded_union([column.geometry for column in space.columns.all()])
            space.geometry = space.geometry.difference(columns_geom)
            space_holes_geom = cascaded_union([hole.geometry for hole in space.holes.all()])
            holes_geom.append(space_holes_geom.intersection(space.geometry))
            space.geometry = space.geometry.difference(space_holes_geom)
        holes_geom = cascaded_union(holes_geom)

        for building in buildings:
            building.original_geometry = building.geometry
        for obj in buildings:
            obj.geometry = obj.geometry.difference(holes_geom)

        results = []
        results.extend(buildings)
        for door in level.doors.all():
            results.append(door)

        results.extend(spaces.values())
        return results

    @staticmethod
    def _get_levels_pk(request, level):
        # noinspection PyPep8Naming
        Level = request.changeset.wrap_model('Level')
        levels_under = ()
        levels_on_top = ()
        lower_level = level.lower(Level).first()
        primary_levels = (level,) + ((lower_level,) if lower_level else ())
        secondary_levels = Level.objects.filter(on_top_of__in=primary_levels).values_list('pk', 'on_top_of')
        if lower_level:
            levels_under = tuple(pk for pk, on_top_of in secondary_levels if on_top_of == lower_level.pk)
        if True:
            levels_on_top = tuple(pk for pk, on_top_of in secondary_levels if on_top_of == level.pk)
        levels = chain([level.pk], levels_under, levels_on_top)
        return levels, levels_on_top, levels_under

    # noinspection PyPep8Naming
    @list_route(methods=['get'])
    def geometries(self, request, *args, **kwargs):
        request.changeset = ChangeSet.get_for_request(request)

        Level = request.changeset.wrap_model('Level')
        Space = request.changeset.wrap_model('Space')

        level = request.GET.get('level')
        space = request.GET.get('space')
        if level is not None:
            if space is not None:
                raise ValidationError('Only level or space can be specified.')
            level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)

            levels, levels_on_top, levels_under = self._get_levels_pk(request, level)
            # don't prefetch groups for now as changesets do not yet work with m2m-prefetches
            levels = Level.objects.filter(pk__in=levels).filter(Level.q_for_request(request))
            graphnodes = request.changeset.wrap_model('GraphNode').objects.all()
            levels = levels.prefetch_related(
                Prefetch('spaces', request.changeset.wrap_model('Space').objects.filter(Space.q_for_request(request))),
                Prefetch('doors', request.changeset.wrap_model('Door').objects.filter(Door.q_for_request(request))),
                'buildings', 'spaces__holes', 'spaces__groups', 'spaces__columns',
                Prefetch('spaces__graphnodes', graphnodes)
            )

            levels = {s.pk: s for s in levels}

            level = levels[level.pk]
            levels_under = [levels[pk] for pk in levels_under]
            levels_on_top = [levels[pk] for pk in levels_on_top]

            # todo: permissions
            graphnodes = tuple(chain(*(space.graphnodes.all()
                                       for space in chain(*(level.spaces.all() for level in levels.values())))))

            graphedges = request.changeset.wrap_model('GraphEdge').objects.all()
            graphedges = graphedges.filter(Q(from_node__in=graphnodes) | Q(to_node__in=graphnodes))
            graphedges = graphedges.select_related('from_node', 'to_node', 'waytype')

            results = chain(
                *(self._get_level_geometries(l) for l in levels_under),
                self._get_level_geometries(level),
                *(self._get_level_geometries(l) for l in levels_on_top),
                graphedges,
                graphnodes,
            )

            return Response([obj.to_geojson(instance=obj) for obj in results])
        elif space is not None:
            space_q_for_request = Space.q_for_request(request)
            qs = Space.objects.filter(space_q_for_request)
            space = get_object_or_404(qs.select_related('level', 'level__on_top_of'), pk=space)
            level = space.level

            doors = [door for door in level.doors.filter(Door.q_for_request(request)).all()
                     if door.geometry.intersects(space.geometry)]
            doors_space_geom = cascaded_union([door.geometry for door in doors]+[space.geometry])

            levels, levels_on_top, levels_under = self._get_levels_pk(request, level.primary_level)
            other_spaces = Space.objects.filter(space_q_for_request, level__pk__in=levels).prefetch_related('groups')

            space = next(s for s in other_spaces if s.pk == space.pk)
            other_spaces = [s for s in other_spaces
                            if s.geometry.intersects(doors_space_geom) and s.pk != space.pk]
            all_other_spaces = other_spaces

            if level.on_top_of_id is None:
                other_spaces_lower = [s for s in other_spaces if s.level_id in levels_under]
                other_spaces_upper = [s for s in other_spaces if s.level_id in levels_on_top]
            else:
                other_spaces_lower = [s for s in other_spaces if s.level_id == level.on_top_of_id]
                other_spaces_upper = []
            other_spaces = [s for s in other_spaces if s.level_id == level.pk]

            space.bounds = True

            buildings = level.buildings.all()
            buildings_geom = cascaded_union([building.geometry for building in buildings])
            for other_space in other_spaces:
                if other_space.outside:
                    other_space.geometry = other_space.geometry.difference(buildings_geom)
            for other_space in chain(other_spaces, other_spaces_lower, other_spaces_upper):
                other_space.opacity = 0.4
                other_space.color = '#ffffff'
            for building in buildings:
                building.opacity = 0.5

            # todo: permissions
            graphnodes = request.changeset.wrap_model('GraphNode').objects.all()
            graphnodes = graphnodes.filter((Q(space__in=all_other_spaces)) | Q(space__pk=space.pk))

            space_graphnodes = tuple(node for node in graphnodes if node.space == space)

            graphedges = request.changeset.wrap_model('GraphEdge').objects.all()
            graphedges = graphedges.filter(Q(from_node__in=space_graphnodes) | Q(to_node__in=space_graphnodes))
            graphedges = graphedges.select_related('from_node', 'to_node', 'waytype')

            results = chain(
                buildings,
                other_spaces_lower,
                doors,
                other_spaces,
                [space],
                space.areas.filter(Area.q_for_request(request)).prefetch_related('groups'),
                space.holes.all(),
                space.stairs.all(),
                space.obstacles.all(),
                space.lineobstacles.all(),
                space.columns.all(),
                space.altitudemarkers.all(),
                space.pois.filter(POI.q_for_request(request)).prefetch_related('groups'),
                other_spaces_upper,
                graphedges,
                graphnodes
            )
            return Response(sum([self._get_geojsons(obj) for obj in results], ()))
        else:
            raise ValidationError('No level or space specified.')

    @staticmethod
    def _get_geojsons(obj):
        return (((obj.to_shadow_geojson(),) if hasattr(obj, 'to_shadow_geojson') else ()) +
                (obj.to_geojson(instance=obj),))

    @list_route(methods=['get'])
    def geometrystyles(self, request, *args, **kwargs):
        return Response({
            'building': '#929292',
            'space': '#d1d1d1',
            'hole': 'rgba(255, 0, 0, 0.3)',
            'door': '#ffffff',
            'area': 'rgba(85, 170, 255, 0.2)',
            'stair': 'rgba(160, 0, 160, 0.5)',
            'obstacle': '#999999',
            'lineobstacle': '#999999',
            'column': '#888888',
            'poi': '#4488cc',
            'shadow': '#000000',
            'graphnode': '#00BB00',
            'graphedge': '#00CC00',
            'altitudemarker': '#ffff00',
        })

    @list_route(methods=['get'])
    def bounds(self, request, *args, **kwargs):
        return Response({
            'bounds': Source.max_bounds(),
        })


class ChangeSetViewSet(ReadOnlyModelViewSet):
    """
    List change sets
    /current/ returns the current changeset.
    """
    queryset = ChangeSet.objects.all()

    def get_queryset(self):
        return ChangeSet.qs_for_request(self.request).select_related('last_update', 'last_state_update', 'last_change')

    def list(self, request, *args, **kwargs):
        return Response([obj.serialize() for obj in self.get_queryset().order_by('id')])

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_object().serialize())

    @list_route(methods=['get'])
    def current(self, request, *args, **kwargs):
        changeset = ChangeSet.get_for_request(request)
        return Response(changeset.serialize())

    @detail_route(methods=['get'])
    def changes(self, request, *args, **kwargs):
        changeset = self.get_object()
        changeset.fill_changes_cache()
        return Response([obj.serialize() for obj in changeset.iter_changed_objects()])
