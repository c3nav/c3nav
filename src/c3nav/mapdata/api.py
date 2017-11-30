import mimetypes
from collections import namedtuple
from functools import wraps

from django.core.cache import cache
from django.db.models import Prefetch
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.cache import get_conditional_response
from django.utils.http import quote_etag, urlsafe_base64_encode
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
from c3nav.mapdata.models.geometry.space import (POI, Area, Column, LineObstacle, Obstacle, Ramp, SpaceGeometryMixin,
                                                 Stair)
from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.locations import (Location, LocationGroupCategory, LocationRedirect, LocationSlug,
                                            SpecificLocation)
from c3nav.mapdata.utils.locations import (get_location_by_id_for_request, get_location_by_slug_for_request,
                                           searchable_locations_for_request, visible_locations_for_request)
from c3nav.mapdata.utils.models import get_submodels


def optimize_query(qs):
    if issubclass(qs.model, SpecificLocation):
        base_qs = LocationGroup.objects.select_related('category')
        qs = qs.prefetch_related(Prefetch('groups', queryset=base_qs))
    return qs


def api_etag(permissions=True, etag_func=AccessPermission.etag_func, cache_parameters=None):
    def wrapper(func):
        @wraps(func)
        def wrapped_func(self, request, *args, **kwargs):
            response_format = self.perform_content_negotiation(request)[0].format
            etag_user = (':'+str(request.user.pk or 0)) if response_format == 'api' else ''
            raw_etag = '%s%s:%s:%s' % (response_format, etag_user, get_language(),
                                       (etag_func(request) if permissions else MapUpdate.current_cache_key()))
            etag = quote_etag(raw_etag)

            response = get_conditional_response(request, etag=etag)
            if response is None:
                cache_key = 'mapdata:api:'+request.path_info[5:].replace('/', '-').strip('-')+':'+raw_etag
                if cache_parameters is not None:
                    for param, type_ in cache_parameters.items():
                        value = int(param in request.GET) if type_ == bool else type_(request.GET.get(param))
                        cache_key += ':'+urlsafe_base64_encode(str(value).encode()).decode()
                    data = cache.get(cache_key)
                    if data is not None:
                        response = Response(data)

                if response is None:
                    response = func(self, request, *args, **kwargs)
                    if cache_parameters is not None and response.status_code == 200:
                        cache.set(cache_key, response.data, 300)

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
    @api_etag(permissions=False, cache_parameters={})
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
            cache_key = 'mapdata:api:keys:%s:%s:%s' % (model.__name__, key,
                                                       AccessPermission.cache_key_for_request(request))
            qs = model.qs_for_request(request)
        else:
            cache_key = 'mapdata:api:keys:%s:%s:%s' % (model.__name__, key,
                                                       MapUpdate.current_cache_key())
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
    """
    Add ?on_top_of=<null or id> to filter by on_top_of, add ?group=<id> to filter by group.
    A Level is a Location – so if it is visible, you can use its ID in the Location API as well.
    """
    queryset = Level.objects.all()

    @list_route(methods=['get'])
    @api_etag(permissions=False, cache_parameters={})
    def geometrytypes(self, request):
        return self.list_types(get_submodels(LevelGeometryMixin))


class BuildingViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Building.objects.all()


class SpaceViewSet(MapdataViewSet):
    """
    Add ?geometry=1 to get geometries, add ?level=<id> to filter by level, add ?group=<id> to filter by group.
    A Space is a Location – so if it is visible, you can use its ID in the Location API as well.
    """
    queryset = Space.objects.all()

    @list_route(methods=['get'])
    @api_etag(permissions=False, cache_parameters={})
    def geometrytypes(self, request):
        return self.list_types(get_submodels(SpaceGeometryMixin))


class DoorViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Door.objects.all()


class HoleViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Hole.objects.all()


class AreaViewSet(MapdataViewSet):
    """
    Add ?geometry=1 to get geometries, add ?space=<id> to filter by space, add ?group=<id> to filter by group.
    An Area is a Location – so if it is visible, you can use its ID in the Location API as well.
    """
    queryset = Area.objects.all()


class StairViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Stair.objects.all()


class RampViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Ramp.objects.all()


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
    """
    Add ?geometry=1 to get geometries, add ?space=<id> to filter by space, add ?group=<id> to filter by group.
    A POI is a Location – so if it is visible, you can use its ID in the Location API as well.
    """
    queryset = POI.objects.all()


class LocationGroupCategoryViewSet(MapdataViewSet):
    queryset = LocationGroupCategory.objects.all()


class LocationGroupViewSet(MapdataViewSet):
    """
    Add ?category=<id or name> to filter by category.
    A Location Group is a Location – so if it is visible, you can use its ID in the Location API as well.
    """
    queryset = LocationGroup.objects.all()


class LocationViewSetBase(RetrieveModelMixin, GenericViewSet):
    queryset = LocationSlug.objects.all()

    def get_object(self) -> LocationSlug:
        raise NotImplementedError

    @api_etag(cache_parameters={'show_redirects': bool, 'detailed': bool, 'geometry': bool})
    def retrieve(self, request, key=None, *args, **kwargs):
        show_redirects = 'show_redirects' in request.GET
        detailed = 'detailed' in request.GET
        geometry = 'geometry' in request.GET

        location = self.get_object()

        if location is None:
            raise NotFound

        if isinstance(location, LocationRedirect):
            if not show_redirects:
                return redirect('../' + str(location.target.slug))  # todo: why does redirect/reverse not work here?

        return Response(location.serialize(include_type=True, detailed=detailed,
                                           geometry=geometry, simple_geometry=True))

    @detail_route(methods=['get'])
    @api_etag()
    def display(self, request, key=None):
        location = self.get_object()

        if location is None:
            raise NotFound

        if isinstance(location, LocationRedirect):
            return redirect('../' + str(location.target.pk) + '/display/')

        return Response(location.details_display())


class LocationViewSet(LocationViewSetBase):
    """
    Locations are Levels, Spaces, Areas, POIs and Location Groups (see /locations/types/). They have a shared ID pool.
    This API endpoint only accesses locations that have can_search or can_describe set to true.
    If you want to access all of them, use the API endpoints for the Location Types.
    Additionally, you can access Custom Locations (Coordinates) by using c:<level.short_label>:x:y as an id or slug.

    add ?searchable to only show locations with can_search set to true ordered by relevance
    add ?detailed to show all attributes
    add ?geometry to show geometries
    /{id}/ add ?show_redirect=1 to suppress redirects and show them as JSON.
    """
    queryset = LocationSlug.objects.all()
    lookup_value_regex = r'[^/]+'

    def get_object(self):
        return get_location_by_id_for_request(self.kwargs['pk'], self.request)

    @api_etag(cache_parameters={'searchable': bool, 'detailed': bool, 'geometry': bool})
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

    @list_route(methods=['get'])
    @api_etag(permissions=False)
    def types(self, request):
        return MapdataViewSet.list_types(get_submodels(Location), geomtype=False)


class LocationBySlugViewSet(LocationViewSetBase):
    queryset = LocationSlug.objects.all()
    lookup_field = 'slug'
    lookup_value_regex = r'[^/]+'

    def get_object(self):
        return get_location_by_slug_for_request(self.kwargs['slug'], self.request)


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
