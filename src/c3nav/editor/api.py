from functools import wraps
from itertools import chain

from django.db.models import Prefetch, Q
from django.urls import Resolver404, resolve
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from rest_framework.authentication import SessionAuthentication
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ParseError, PermissionDenied, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet
from shapely import prepared
from shapely.ops import cascaded_union

from c3nav.api.utils import get_api_post_data
from c3nav.editor.forms import ChangeSetForm, RejectForm
from c3nav.editor.models import ChangeSet
from c3nav.editor.utils import LevelChildEditUtils, SpaceChildEditUtils
from c3nav.editor.views.base import etag_func
from c3nav.mapdata.api import api_etag
from c3nav.mapdata.models import Area, MapUpdate, Source
from c3nav.mapdata.models.geometry.space import POI
from c3nav.mapdata.utils.user import can_access_editor


class EditorViewSetMixin(ViewSet):
    def initial(self, request, *args, **kwargs):
        if not can_access_editor(request):
            raise PermissionDenied
        return super().initial(request, *args, **kwargs)


def api_etag_with_update_cache_key(**outkwargs):
    outkwargs.setdefault('cache_kwargs', {})['update_cache_key_match'] = bool

    def wrapper(func):
        func = api_etag(**outkwargs)(func)

        @wraps(func)
        def wrapped_func(self, request, *args, **kwargs):
            try:
                changeset = request.changeset
            except AttributeError:
                changeset = ChangeSet.get_for_request(request)
                request.changeset = changeset

            update_cache_key = request.changeset.raw_cache_key_without_changes
            update_cache_key_match = request.GET.get('update_cache_key') == update_cache_key
            return func(self, request, *args,
                        update_cache_key=update_cache_key, update_cache_key_match=update_cache_key_match,
                        **kwargs)
        return wrapped_func
    return wrapper


class EditorViewSet(EditorViewSetMixin, ViewSet):
    """
    Editor API
    /geometries/ returns a list of geojson features, you have to specify ?level=<id> or ?space=<id>
    /geometrystyles/ returns styling information for all geometry types
    /bounds/ returns the maximum bounds of the map
    /{path}/ insert an editor path to get an API represantation of it. POST requests on forms are possible as well
    """
    lookup_field = 'path'
    lookup_value_regex = r'.+'

    @staticmethod
    def _get_level_geometries(level):
        buildings = level.buildings.all()
        buildings_geom = cascaded_union([building.geometry for building in buildings])
        spaces = {space.pk: space for space in level.spaces.all()}
        holes_geom = []
        for space in spaces.values():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)
            columns = [column.geometry for column in space.columns.all()]
            if columns:
                columns_geom = cascaded_union([column.geometry for column in space.columns.all()])
                space.geometry = space.geometry.difference(columns_geom)
            holes = [hole.geometry for hole in space.holes.all()]
            if holes:
                space_holes_geom = cascaded_union(holes)
                holes_geom.append(space_holes_geom.intersection(space.geometry))
                space.geometry = space.geometry.difference(space_holes_geom)

        for building in buildings:
            building.original_geometry = building.geometry

        if holes_geom:
            holes_geom = cascaded_union(holes_geom)
            holes_geom_prep = prepared.prep(holes_geom)
            for obj in buildings:
                if holes_geom_prep.intersects(obj.geometry):
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

    @staticmethod
    def area_sorting_func(area):
        groups = tuple(area.groups.all())
        if not groups:
            return (0, 0, 0)
        return (1, groups[0].category.priority, groups[0].hierarchy, groups[0].priority)

    # noinspection PyPep8Naming
    @action(detail=False, methods=['get'])
    @api_etag_with_update_cache_key(etag_func=etag_func, cache_parameters={'level': str, 'space': str})
    def geometries(self, request, update_cache_key, update_cache_key_match, *args, **kwargs):
        Level = request.changeset.wrap_model('Level')
        Space = request.changeset.wrap_model('Space')
        Column = request.changeset.wrap_model('Column')
        Hole = request.changeset.wrap_model('Hole')
        AltitudeMarker = request.changeset.wrap_model('AltitudeMarker')
        Building = request.changeset.wrap_model('Building')
        Door = request.changeset.wrap_model('Door')
        LocationGroup = request.changeset.wrap_model('LocationGroup')
        WifiMeasurement = request.changeset.wrap_model('WifiMeasurement')

        level = request.GET.get('level')
        space = request.GET.get('space')
        if level is not None:
            if space is not None:
                raise ValidationError('Only level or space can be specified.')

            level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)

            edit_utils = LevelChildEditUtils(level, request)
            if not edit_utils.can_access_child_base_mapdata:
                raise PermissionDenied

            levels, levels_on_top, levels_under = self._get_levels_pk(request, level)
            # don't prefetch groups for now as changesets do not yet work with m2m-prefetches
            levels = Level.objects.filter(pk__in=levels).filter(Level.q_for_request(request))
            # graphnodes_qs = request.changeset.wrap_model('GraphNode').objects.all()
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
                Prefetch('spaces__wifi_measurements', WifiMeasurement.objects.only('geometry', 'space')),
                # Prefetch('spaces__graphnodes', graphnodes_qs)
            )

            levels = {s.pk: s for s in levels}

            level = levels[level.pk]
            levels_under = [levels[pk] for pk in levels_under]
            levels_on_top = [levels[pk] for pk in levels_on_top]

            # todo: permissions
            # graphnodes = tuple(chain(*(space.graphnodes.all()
            #                            for space in chain(*(level.spaces.all() for level in levels.values())))))
            # graphnodes_lookup = {node.pk: node for node in graphnodes}

            # graphedges = request.changeset.wrap_model('GraphEdge').objects.all()
            # graphedges = graphedges.filter(Q(from_node__in=graphnodes) | Q(to_node__in=graphnodes))
            # graphedges = graphedges.select_related('waytype')

            # this is faster because we only deserialize graphnode geometries once
            # missing_graphnodes = graphnodes_qs.filter(pk__in=set(chain(*((edge.from_node_id, edge.to_node_id)
            #                                                              for edge in graphedges))))
            # graphnodes_lookup.update({node.pk: node for node in missing_graphnodes})
            # for edge in graphedges:
            #     edge._from_node_cache = graphnodes_lookup[edge.from_node_id]
            #     edge._to_node_cache = graphnodes_lookup[edge.to_node_id]

            # graphedges = [edge for edge in graphedges if edge.from_node.space_id != edge.to_node.space_id]

            results = chain(
                *(self._get_level_geometries(l) for l in levels_under),
                self._get_level_geometries(level),
                *(self._get_level_geometries(l) for l in levels_on_top),
                *(space.altitudemarkers.all() for space in level.spaces.all()),
                *(space.wifi_measurements.all() for space in level.spaces.all())
                # graphedges,
                # graphnodes,
            )
        elif space is not None:
            space_q_for_request = Space.q_for_request(request)
            qs = Space.objects.filter(space_q_for_request)
            space = get_object_or_404(qs.select_related('level', 'level__on_top_of'), pk=space)
            level = space.level

            edit_utils = SpaceChildEditUtils(space, request)
            if not edit_utils.can_access_child_base_mapdata:
                raise PermissionDenied

            if request.user_permissions.can_access_base_mapdata:
                doors = [door for door in level.doors.filter(Door.q_for_request(request)).all()
                         if door.geometry.intersects(space.geometry)]
                doors_space_geom = cascaded_union([door.geometry for door in doors]+[space.geometry])

                levels, levels_on_top, levels_under = self._get_levels_pk(request, level.primary_level)
                if level.on_top_of_id is not None:
                    levels = chain([level.pk], levels_on_top)
                other_spaces = Space.objects.filter(space_q_for_request, level__pk__in=levels).only(
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

                if level.on_top_of_id is None:
                    other_spaces_lower = [s for s in other_spaces if s.level_id in levels_under]
                    other_spaces_upper = [s for s in other_spaces if s.level_id in levels_on_top]
                else:
                    other_spaces_lower = [s for s in other_spaces if s.level_id == level.on_top_of_id]
                    other_spaces_upper = []
                other_spaces = [s for s in other_spaces if s.level_id == level.pk]

                space.bounds = True

                # deactivated for performance reasons
                buildings = level.buildings.all()
                # buildings_geom = cascaded_union([building.geometry for building in buildings])
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
                graphnodes = request.changeset.wrap_model('GraphNode').objects.all()
                graphnodes = graphnodes.filter((Q(space__in=all_other_spaces)) | Q(space__pk=space.pk))

                space_graphnodes = tuple(node for node in graphnodes if node.space_id == space.pk)

                graphedges = request.changeset.wrap_model('GraphEdge').objects.all()
                space_graphnodes_ids = tuple(node.pk for node in space_graphnodes)
                graphedges = graphedges.filter(Q(from_node__pk__in=space_graphnodes_ids) |
                                               Q(to_node__pk__in=space_graphnodes_ids))
                graphedges = graphedges.select_related('from_node', 'to_node', 'waytype').only(
                    'from_node__geometry', 'to_node__geometry', 'waytype__color'
                )
            else:
                graphnodes = []
                graphedges = []

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
            areas = sorted(areas, key=self.area_sorting_func)

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
                space.obstacles.all().only('geometry', 'space', 'color'),
                space.lineobstacles.all().only('geometry', 'width', 'space', 'color'),
                space.columns.all().only('geometry', 'space'),
                space.altitudemarkers.all().only('geometry', 'space'),
                space.wifi_measurements.all().only('geometry', 'space'),
                space.pois.filter(POI.q_for_request(request)).only('geometry', 'space').prefetch_related(
                    Prefetch('groups', LocationGroup.objects.only(
                        'color', 'category', 'priority', 'hierarchy', 'category__priority', 'category__allow_pois'
                    ).filter(color__isnull=False))
                ),
                other_spaces_upper,
                graphedges,
                graphnodes
            )
        else:
            raise ValidationError('No level or space specified.')

        return Response(list(chain(
            [('update_cache_key', update_cache_key)],
            (self.conditional_geojson(obj, update_cache_key_match) for obj in results)
        )))

    def conditional_geojson(self, obj, update_cache_key_match):
        if update_cache_key_match and not obj._affected_by_changeset:
            return obj.get_geojson_key()

        result = obj.to_geojson(instance=obj)
        result['properties']['changed'] = obj._affected_by_changeset
        return result

    @action(detail=False, methods=['get'])
    @api_etag(etag_func=MapUpdate.current_cache_key, cache_parameters={})
    def geometrystyles(self, request, *args, **kwargs):
        return Response({
            'building': '#aaaaaa',
            'space': '#eeeeee',
            'hole': 'rgba(255, 0, 0, 0.3)',
            'door': '#ffffff',
            'area': '#55aaff',
            'stair': '#a000a0',
            'ramp': 'rgba(160, 0, 160, 0.2)',
            'obstacle': '#999999',
            'lineobstacle': '#999999',
            'column': 'rgba(0, 0, 50, 0.3)',
            'poi': '#4488cc',
            'shadow': '#000000',
            'graphnode': '#009900',
            'graphedge': '#00CC00',
            'altitudemarker': '#0000FF',
            'wifimeasurement': '#DDDD00',
        })

    @action(detail=False, methods=['get'])
    @api_etag(etag_func=etag_func, cache_parameters={})
    def bounds(self, request, *args, **kwargs):
        return Response({
            'bounds': Source.max_bounds(),
        })

    def __getattr__(self, name):
        # allow POST and DELETE methods for the editor API

        if getattr(self, 'get', None).__name__ in ('list', 'retrieve'):
            if name == 'post' and (self.resolved.url_name.endswith('.create') or
                                   self.resolved.url_name.endswith('.edit')):
                return self.post_or_delete
            if name == 'delete' and self.resolved.url_name.endswith('.edit'):
                return self.post_or_delete
        raise AttributeError

    def post_or_delete(self, request, *args, **kwargs):
        # django-rest-framework doesn't automatically do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        return self.retrieve(request, *args, **kwargs)

    def list(self, request, *args, **kwargs):
        return self.retrieve(request, *args, **kwargs)

    @cached_property
    def resolved(self):
        resolved = None
        path = self.kwargs.get('path', '')
        if path:
            try:
                resolved = resolve('/editor/'+path+'/')
            except Resolver404:
                pass

        if not resolved:
            try:
                resolved = resolve('/editor/'+path)
            except Resolver404:
                pass

        self.request.sub_resolver_match = resolved

        return resolved

    def retrieve(self, request, *args, **kwargs):
        resolved = self.resolved
        if not resolved:
            raise NotFound(_('No matching editor view endpoint found.'))

        if not getattr(resolved.func, 'api_hybrid', False):
            raise NotFound(_('Matching editor view point does not provide an API.'))

        get_api_post_data(request)

        response = resolved.func(request, api=True, *resolved.args, **resolved.kwargs)
        return response


class ChangeSetViewSet(EditorViewSetMixin, ReadOnlyModelViewSet):
    """
    List and manipulate changesets. All lists are ordered by last update descending. Use ?offset= to specify an offset.
    Don't forget to set X-Csrftoken for POST requests!

    / lists all changesets this user can see.
    /user/ lists changesets by this user
    /reviewing/ lists changesets this user is currently reviewing.
    /pending_review/ lists changesets this user can review.

    /current/ returns the current changeset.
    /direct_editing/ POST to activate direct editing (if available).
    /deactive/ POST to deactivate current changeset or deactivate direct editing

    /{id}/changes/ list all changes of a given changeset.
    /{id}/activate/ POST to activate given changeset.
    /{id}/edit/ POST to edit given changeset (provide title and description in POST data).
    /{id}/restore_object/ POST to restore an object deleted by this changeset (provide change id as id in POST data).
    /{id}/delete/ POST to delete given changeset.
    /{id}/propose/ POST to propose given changeset.
    /{id}/unpropose/ POST to unpropose given changeset.
    /{id}/review/ POST to review given changeset.
    /{id}/reject/ POST to reject given changeset (provide reject=1 in POST data for final rejection).
    /{id}/unreject/ POST to unreject given changeset.
    /{id}/apply/ POST to accept and apply given changeset.
    """
    queryset = ChangeSet.objects.all()

    def get_queryset(self):
        return ChangeSet.qs_for_request(self.request).select_related('last_update', 'last_state_update', 'last_change')

    def _list(self, request, qs):
        offset = 0
        if 'offset' in request.GET:
            if not request.GET['offset'].isdigit():
                raise ParseError('offset has to be a positive integer.')
            offset = int(request.GET['offset'])
        return Response([obj.serialize() for obj in qs.order_by('-last_update')[offset:offset+20]])

    def list(self, request, *args, **kwargs):
        return self._list(request, self.get_queryset())

    @action(detail=False, methods=['get'])
    def user(self, request, *args, **kwargs):
        return self._list(request, self.get_queryset().filter(author=request.user))

    @action(detail=False, methods=['get'])
    def reviewing(self, request, *args, **kwargs):
        return self._list(request, self.get_queryset().filter(
            assigned_to=request.user, state='review'
        ))

    @action(detail=False, methods=['get'])
    def pending_review(self, request, *args, **kwargs):
        return self._list(request, self.get_queryset().filter(
            state__in=('proposed', 'reproposed'),
        ))

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_object().serialize())

    @action(detail=False, methods=['get'])
    def current(self, request, *args, **kwargs):
        changeset = ChangeSet.get_for_request(request)
        return Response({
            'direct_editing': changeset.direct_editing,
            'changeset': changeset.serialize() if changeset.pk else None,
        })

    @action(detail=False, methods=['post'])
    def direct_editing(self, request, *args, **kwargs):
        # django-rest-framework doesn't automatically do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        if not ChangeSet.can_direct_edit(request):
            raise PermissionDenied(_('You don\'t have the permission to activate direct editing.'))

        changeset = ChangeSet.get_for_request(request)
        if changeset.pk is not None:
            raise PermissionDenied(_('You cannot activate direct editing if you have an active changeset.'))

        request.session['direct_editing'] = True

        return Response({
            'success': True,
        })

    @action(detail=False, methods=['post'])
    def deactivate(self, request, *args, **kwargs):
        # django-rest-framework doesn't automatically do this for logged out requests
        SessionAuthentication().enforce_csrf(request)

        request.session.pop('changeset', None)
        request.session['direct_editing'] = False

        return Response({
            'success': True,
        })

    @action(detail=True, methods=['get'])
    def changes(self, request, *args, **kwargs):
        changeset = self.get_object()
        changeset.fill_changes_cache()
        return Response([obj.serialize() for obj in changeset.iter_changed_objects()])

    @action(detail=True, methods=['post'])
    def activate(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_activate(request):
                raise PermissionDenied(_('You can not activate this change set.'))

            changeset.activate(request)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def edit(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_edit(request):
                raise PermissionDenied(_('You cannot edit this change set.'))

            form = ChangeSetForm(instance=changeset, data=get_api_post_data(request))
            if not form.is_valid():
                raise ParseError(form.errors)

            changeset = form.instance
            update = changeset.updates.create(user=request.user,
                                              title=changeset.title, description=changeset.description)
            changeset.last_update = update
            changeset.save()
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def restore_object(self, request, *args, **kwargs):
        data = get_api_post_data(request)
        if 'id' not in data:
            raise ParseError('Missing id.')

        restore_id = data['id']
        if isinstance(restore_id, str) and restore_id.isdigit():
            restore_id = int(restore_id)

        if not isinstance(restore_id, int):
            raise ParseError('id needs to be an integer.')

        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_edit(request):
                raise PermissionDenied(_('You can not edit changes on this change set.'))

            try:
                changed_object = changeset.changed_objects_set.get(pk=restore_id)
            except Exception:
                raise NotFound('could not find object.')

            try:
                changed_object.restore()
            except PermissionError:
                raise PermissionDenied(_('You cannot restore this object, because it depends on '
                                         'a deleted object or it would violate a unique contraint.'))

            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def propose(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            raise PermissionDenied(_('You need to log in to propose changes.'))

        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.title or not changeset.description:
                raise PermissionDenied(_('You need to add a title an a description to propose this change set.'))

            if not changeset.can_propose(request):
                raise PermissionDenied(_('You cannot propose this change set.'))

            changeset.propose(request.user)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def unpropose(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_unpropose(request):
                raise PermissionDenied(_('You cannot unpropose this change set.'))

            changeset.unpropose(request.user)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def review(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_start_review(request):
                raise PermissionDenied(_('You cannot review these changes.'))

            changeset.start_review(request.user)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def reject(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not not changeset.can_end_review(request):
                raise PermissionDenied(_('You cannot reject these changes.'))

            form = RejectForm(get_api_post_data(request))
            if not form.is_valid():
                raise ParseError(form.errors)

            changeset.reject(request.user, form.cleaned_data['comment'], form.cleaned_data['final'])
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def unreject(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_unreject(request):
                raise PermissionDenied(_('You cannot unreject these changes.'))

            changeset.unreject(request.user)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def apply(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_end_review(request):
                raise PermissionDenied(_('You cannot accept and apply these changes.'))

            changeset.apply(request.user)
            return Response({'success': True})

    @action(detail=True, methods=['post'])
    def delete(self, request, *args, **kwargs):
        changeset = self.get_object()
        with changeset.lock_to_edit(request) as changeset:
            if not changeset.can_delete(request):
                raise PermissionDenied(_('You cannot delete this change set.'))

            changeset.delete()
            return Response({'success': True})
