import mimetypes
import operator
from functools import reduce, wraps

from django.core.cache import cache
from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.utils.translation import ugettext_lazy as _
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet, ViewSet

from c3nav.mapdata.models import AccessRestriction, Building, Door, Hole, LocationGroup, MapUpdate, Source, Space
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.level import LevelGeometryMixin
from c3nav.mapdata.models.geometry.space import POI, Area, Column, LineObstacle, Obstacle, SpaceGeometryMixin, Stair
from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.locations import (Location, LocationGroupCategory, LocationRedirect, LocationSlug,
                                            SpecificLocation)
from c3nav.mapdata.utils.models import get_submodels


def optimize_query(qs):
    if issubclass(qs.model, SpecificLocation):
        base_qs = LocationGroup.objects.select_related('category').only('id', 'titles', 'category')
        qs = qs.prefetch_related(Prefetch('groups', queryset=base_qs))
    return qs


def simple_api_cache(permissions=True, etag_func=AccessPermission.etag_func):
    def wrapper(func):
        @wraps(func)
        def wrapped_func(self, request, *args, **kwargs):
            etag = quote_etag(etag_func(request) if permissions else MapUpdate.current_cache_key())

            response = get_conditional_response(request, etag=etag)
            if response is None:
                response = func(self, request, *args, **kwargs)

            response['ETag'] = etag
            response['Cache-Control'] = 'no-cache'
            return response
        return wrapped_func
    return wrapper


class MapViewSet(ViewSet):
    """
    Map API
    /bounds/ returns the maximum bounds of the map
    """

    @list_route(methods=['get'])
    @simple_api_cache(permissions=False)
    def bounds(self, request, *args, **kwargs):
        return Response({
            'bounds': Source.max_bounds(),
        })


class MapdataViewSet(ReadOnlyModelViewSet):
    def get_queryset(self):
        qs = super().get_queryset()
        if hasattr(qs.model, 'qs_for_request'):
            return qs.model.qs_for_request(self.request)
        return qs

    @simple_api_cache()
    def list(self, request, *args, **kwargs):
        qs = optimize_query(self.get_queryset())
        geometry = ('geometry' in request.GET)
        if issubclass(qs.model, LevelGeometryMixin) and 'level' in request.GET:
            if not request.GET['level'].isdigit():
                raise ValidationError(detail={'detail': _('%s is not an integer.') % 'level'})
            try:
                level = Level.qs_for_request(request).get(pk=request.GET['level'])
            except Level.DoesNotExist:
                raise NotFound(detail=_('level not found.'))
            qs = qs.filter(level=level)
        if issubclass(qs.model, SpaceGeometryMixin) and 'space' in request.GET:
            if not request.GET['space'].isdigit():
                raise ValidationError(detail={'detail': _('%s is not an integer.') % 'space'})
            try:
                space = Space.qs_for_request(request).get(pk=request.GET['space'])
            except Space.DoesNotExist:
                raise NotFound(detail=_('space not found.'))
            qs = qs.filter(space=space)
        if issubclass(qs.model, LocationGroup) and 'category' in request.GET:
            kwargs = {('pk' if request.GET['category'].isdigit() else 'name'): request.GET['category']}
            try:
                category = LocationGroupCategory.objects.get(**kwargs)
            except LocationGroupCategory.DoesNotExist:
                raise NotFound(detail=_('category not found.'))
            qs = qs.filter(category=category)
        if issubclass(qs.model, SpecificLocation) and 'group' in request.GET:
            if not request.GET['group'].isdigit():
                raise ValidationError(detail={'detail': _('%s is not an integer.') % 'group'})
            try:
                group = LocationGroup.objects.get(pk=request.GET['group'])
            except LocationGroupCategory.DoesNotExist:
                raise NotFound(detail=_('group not found.'))
            qs = qs.filter(groups=group)
        if qs.model == Level and 'on_top_of' in request.GET:
            if request.GET['on_top_of'] == 'null':
                qs = qs.filter(on_top_of__isnull=False)
            else:
                if not request.GET['on_top_of'].isdigit():
                    raise ValidationError(detail={'detail': _('%s is not null or an integer.') % 'on_top_of'})
                try:
                    level = Level.objects.get(pk=request.GET['on_top_of'])
                except Level.DoesNotExist:
                    raise NotFound(detail=_('level not found.'))
                qs = qs.filter(on_top_of=level)
        return Response([obj.serialize(geometry=geometry) for obj in qs.order_by('id')])

    @simple_api_cache()
    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_object().serialize())

    @staticmethod
    def list_types(models_list, **kwargs):
        return Response([
            model.serialize_type(**kwargs) for model in models_list
        ])


class LevelViewSet(MapdataViewSet):
    """ Add ?on_top_of=<null or id> to filter by on_top_of, add ?group=<id> to filter by group. """
    queryset = Level.objects.all()

    @list_route(methods=['get'])
    @simple_api_cache(permissions=False)
    def geometrytypes(self, request):
        return self.list_types(get_submodels(LevelGeometryMixin))

    @detail_route(methods=['get'])
    @simple_api_cache()
    def svg(self, request, pk=None):
        level = self.get_object()
        response = HttpResponse(level.render_svg(request), 'image/svg+xml')
        return response


class BuildingViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Building.objects.all()


class SpaceViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level, add ?group=<id> to filter by group. """
    queryset = Space.objects.all()

    @list_route(methods=['get'])
    @simple_api_cache(permissions=False)
    def geometrytypes(self, request):
        return self.list_types(get_submodels(SpaceGeometryMixin))


class DoorViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Door.objects.all()


class HoleViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Hole.objects.all()


class AreaViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space, add ?group=<id> to filter by group. """
    queryset = Area.objects.all()


class StairViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Stair.objects.all()


class ObstacleViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Obstacle.objects.all()


class LineObstacleViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = LineObstacle.objects.all()


class ColumnViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Column.objects.all()


class POIViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space, add ?group=<id> to filter by group. """
    queryset = POI.objects.all()


class LocationGroupCategoryViewSet(MapdataViewSet):
    queryset = LocationGroupCategory.objects.all()


class LocationGroupViewSet(MapdataViewSet):
    """ Add ?category=<id or name> to filter by category. """
    queryset = LocationGroup.objects.all()


class LocationViewSet(RetrieveModelMixin, GenericViewSet):
    """
    only accesses locations that have can_search or can_describe set to true.
    add ?searchable to only show locations with can_search set to true ordered by relevance
    add ?detailed to show all attributes
    add ?geometry to show geometries
    /{id}/ add ?show_redirect=1 to suppress redirects and show them as JSON.
    """
    queryset = LocationSlug.objects.all()
    lookup_field = 'slug'

    def get_queryset(self, mode=None):
        queryset = super().get_queryset().order_by('id')

        conditions = []
        for model in get_submodels(Location):
            related_name = model._meta.default_related_name
            condition = Q(**{related_name+'__isnull': False})
            if mode == 'search':
                condition &= Q(**{related_name+'__can_search': True})
            elif mode == 'search-describe':
                condition &= Q(**{related_name+'__can_search': True}) | Q(**{related_name+'__can_describe': True})
            # noinspection PyUnresolvedReferences
            condition &= model.q_for_request(self.request, prefix=related_name+'__')
            conditions.append(condition)
        queryset = queryset.filter(reduce(operator.or_, conditions))

        # prefetch locationgroups
        base_qs = LocationGroup.qs_for_request(self.request).select_related('category')
        for model in get_submodels(SpecificLocation):
            queryset = queryset.prefetch_related(Prefetch(model._meta.default_related_name + '__groups',
                                                          queryset=base_qs))

        return queryset

    @simple_api_cache()
    def list(self, request, *args, **kwargs):
        searchable = 'searchable' in request.GET
        detailed = 'detailed' in request.GET
        geometry = 'geometry' in request.GET

        cache_key = 'mapdata:api:location:list:%d:%s' % (
            searchable + detailed*2 + geometry*4,
            AccessPermission.cache_key_for_request(self.request)
        )
        result = cache.get(cache_key, None)
        if result is None:
            queryset_cache_key = 'mapdata:api:location:queryset:%d:%s' % (
                searchable,
                AccessPermission.cache_key_for_request(self.request)
            )
            queryset = cache.get(queryset_cache_key, None)
            if queryset is None or 1:
                queryset = self.get_queryset(mode=('searchable' if searchable else 'searchable-describe'))

                queryset = tuple(obj.get_child() for obj in queryset)

                if searchable:
                    queryset = sorted(queryset, key=operator.attrgetter('order'), reverse=True)
                else:
                    queryset = tuple(queryset)

                # add locations to groups
                locationgroups = {obj.pk: obj for obj in queryset if isinstance(obj, LocationGroup)}
                for group in locationgroups.values():
                    group.locations = []
                for obj in queryset:
                    if not isinstance(obj, SpecificLocation):
                        continue
                    for group in obj.groups.all():
                        group = locationgroups.get(group.pk, None)
                        if group is not None:
                            group.locations.append(obj)

                # precache cached properties
                for obj in queryset:
                    # noinspection PyStatementEffect
                    obj.subtitle, obj.order

                cache.set(queryset_cache_key, queryset, 300)

            result = tuple(obj.serialize(include_type=True, detailed=detailed, geometry=geometry) for obj in queryset)
            cache.set(cache_key, result, 300)

        return Response(result)

    @simple_api_cache()
    def retrieve(self, request, slug=None, *args, **kwargs):
        result = Location.get_by_slug(slug, self.get_queryset())
        if result is None:
            raise NotFound
        result = result.get_child()
        if isinstance(result, LocationRedirect):
            if 'show_redirects' in request.GET:
                return Response(result.serialize(include_type=True))
            return redirect('../'+result.target.slug)  # todo: why does redirect/reverse not work here?
        return Response(result.serialize(include_type=True, detailed='detailed' in request.GET))

    @list_route(methods=['get'])
    @simple_api_cache(permissions=False)
    def types(self, request):
        return MapdataViewSet.list_types(get_submodels(Location), geomtype=False)


class SourceViewSet(MapdataViewSet):
    queryset = Source.objects.all()

    @detail_route(methods=['get'])
    @simple_api_cache()
    def image(self, request, pk=None):
        return self._image(request, pk=pk)

    def _image(self, request, pk=None):
        source = self.get_object()
        return HttpResponse(open(source.filepath, 'rb'), content_type=mimetypes.guess_type(source.name)[0])


class AccessRestrictionViewSet(MapdataViewSet):
    queryset = AccessRestriction.objects.all()
