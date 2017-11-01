import mimetypes
from collections import namedtuple
from functools import wraps

from django.core.cache import cache
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import get_language
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
from c3nav.mapdata.utils.locations import (get_location_by_slug_for_request, searchable_locations_for_request,
                                           visible_locations_for_request)
from c3nav.mapdata.utils.models import get_submodels


def optimize_query(qs):
    if issubclass(qs.model, SpecificLocation):
        base_qs = LocationGroup.objects.select_related('category')
        qs = qs.prefetch_related(Prefetch('groups', queryset=base_qs))
    return qs


def api_etag(permissions=True, etag_func=AccessPermission.etag_func):
    def wrapper(func):
        @wraps(func)
        def wrapped_func(self, request, *args, **kwargs):
            etag = quote_etag(get_language()+':'+(etag_func(request) if permissions else MapUpdate.current_cache_key()))

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
    @api_etag(permissions=False)
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

    qs_filter = namedtuple('qs_filter', ('field', 'model', 'key', 'value'))

    def _get_keys_for_model(self, request, model, key):
        if hasattr(model, 'qs_for_request'):
            cache_key = 'mapdata:api:%s:%s:%s' % (model.__name__, key, AccessPermission.cache_key_for_request(request))
            qs = model.qs_for_request(request)
        else:
            cache_key = 'mapdata:api:%s:%s:%s' % (model.__name__, key, MapUpdate.current_cache_key())
            qs = model.objects.all()

        result = cache.get(cache_key, None)
        if result is not None:
            return result

        result = set(qs.values_list(key, flat=True))
        cache.set(cache_key, result, 300)

        return result

    def _get_list(self, request):
        qs = optimize_query(self.get_queryset())
        filters = []
        if issubclass(qs.model, LevelGeometryMixin) and 'level' in request.GET:
            filters.append(self.qs_filter(field='level', model=Level, key='pk', value=request.GET['level']))

        if issubclass(qs.model, SpaceGeometryMixin) and 'space' in request.GET:
            filters.append(self.qs_filter(field='space', model=Space, key='pk', value=request.GET['space']))

        if issubclass(qs.model, LocationGroup) and 'category' in request.GET:
            filters.append(self.qs_filter(field='category', model=LocationGroupCategory,
                                          key='pk' if request.GET['category'].isdigit() else 'name',
                                          value=request.GET['category']))

        if issubclass(qs.model, SpecificLocation) and 'group' in request.GET:
            filters.append(self.qs_filter(field='groups', model=LocationGroup, key='pk', value=request.GET['group']))

        if qs.model == Level and 'on_top_of' in request.GET:
            value = None if request.GET['on_top_of'] == 'null' else request.GET['on_top_of']
            filters.append(self.qs_filter(field='on_top_of', model=Level, key='pk', value=value))

        cache_key = 'mapdata:api:%s:%s' % (qs.model.__name__, AccessPermission.cache_key_for_request(request))
        for qs_filter in filters:
            cache_key += ';%s,%s' % (qs_filter.field, qs_filter.value)

        print(cache_key)

        results = cache.get(cache_key, None)
        if results is not None:
            return results

        for qs_filter in filters:
            if qs_filter.key == 'pk' and not qs_filter.value.isdigit():
                raise ValidationError(detail={
                    'detail': _('%(field)s is not an integer.') % {'field': qs_filter.field}
                })

        for qs_filter in filters:
            if qs_filter.value is not None:
                keys = self._get_keys_for_model(request, qs_filter.model, qs_filter.key)
                value = int(qs_filter.value) if qs_filter.key == 'pk' else qs_filter.value
                if value not in keys:
                    raise NotFound(detail=_('%(model)s not found.') % {'model': qs_filter.model._meta.verbose_name})

        results = tuple(qs.order_by('id'))
        cache.set(cache_key, results, 300)
        return results

    @api_etag()
    def list(self, request, *args, **kwargs):
        geometry = ('geometry' in request.GET)
        results = self._get_list(request)

        return Response([obj.serialize(geometry=geometry) for obj in results])

    @api_etag()
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
    @api_etag(permissions=False)
    def geometrytypes(self, request):
        return self.list_types(get_submodels(LevelGeometryMixin))

    @detail_route(methods=['get'])
    @api_etag()
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
    @api_etag(permissions=False)
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

    @api_etag()
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
            if searchable:
                locations = searchable_locations_for_request(self.request)
            else:
                locations = visible_locations_for_request(self.request).values()

            result = tuple(obj.serialize(include_type=True, detailed=detailed, geometry=geometry, simple_geometry=True)
                           for obj in locations)
            cache.set(cache_key, result, 300)

        return Response(result)

    @api_etag()
    def retrieve(self, request, slug=None, *args, **kwargs):
        show_redirects = 'show_redirects' in request.GET
        detailed = 'detailed' in request.GET
        geometry = 'geometry' in request.GET

        location = get_location_by_slug_for_request(slug, request)

        if location is None:
            raise NotFound

        if isinstance(location, LocationRedirect):
            if not show_redirects:
                return redirect('../' + location.target.slug)  # todo: why does redirect/reverse not work here?

        return Response(location.serialize(include_type=True, detailed=detailed,
                                           geometry=geometry, simple_geometry=True))

    @list_route(methods=['get'])
    @api_etag(permissions=False)
    def types(self, request):
        return MapdataViewSet.list_types(get_submodels(Location), geomtype=False)


class SourceViewSet(MapdataViewSet):
    queryset = Source.objects.all()

    @detail_route(methods=['get'])
    @api_etag()
    def image(self, request, pk=None):
        return self._image(request, pk=pk)

    def _image(self, request, pk=None):
        source = self.get_object()
        return HttpResponse(open(source.filepath, 'rb'), content_type=mimetypes.guess_type(source.name)[0])


class AccessRestrictionViewSet(MapdataViewSet):
    queryset = AccessRestriction.objects.all()
