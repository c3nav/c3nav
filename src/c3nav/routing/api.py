import hashlib
import json
import mimetypes
import os
from collections import OrderedDict

from django.conf import settings
from django.core.files import File
from django.http import Http404, HttpResponse, HttpResponseNotModified
from django.http import HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from rest_framework.decorators import detail_route, list_route, api_view
from rest_framework.response import Response
from rest_framework.viewsets import ReadOnlyModelViewSet, ViewSet

from c3nav.access.apply import filter_arealocations_by_access, filter_queryset_by_access, get_unlocked_packages_names
from c3nav.mapdata.lastupdate import get_last_mapdata_update
from c3nav.mapdata.models import GEOMETRY_MAPITEM_TYPES, AreaLocation, Level, LocationGroup, Package, Source
from c3nav.mapdata.models.geometry import DirectedLineGeometryMapItemWithLevel
from c3nav.mapdata.search import get_location
from c3nav.mapdata.serializers.main import LevelSerializer, PackageSerializer, SourceSerializer
from c3nav.mapdata.utils.cache import (CachedReadOnlyViewSetMixin, cache_mapdata_api_response, get_levels_cached,
                                       get_packages_cached, get_bssid_areas_cached)


class RoutingmetryTypeViewSet(ViewSet):
    """
    Lists all geometry types.
    """
    @cache_mapdata_api_response()
    def list(self, request):
        return Response([
            OrderedDict((
                ('name', name),
                ('title', str(mapitemtype._meta.verbose_name)),
                ('title_plural', str(mapitemtype._meta.verbose_name_plural)),
            )) for name, mapitemtype in GEOMETRY_MAPITEM_TYPES.items()
        ])


class GeometryViewSet(ViewSet):
    """
    List all geometries.
    You can filter by adding a level GET parameter or one or more package or type GET parameters.
    """
    def list(self, request):
        types = set(request.GET.getlist('type'))
        valid_types = list(GEOMETRY_MAPITEM_TYPES.keys())
        if not types:
            types = valid_types
        else:
            types = [t for t in valid_types if t in types]

        level = None
        if 'level' in request.GET:
            levels_cached = get_levels_cached()
            level_name = request.GET['level']
            if level_name in levels_cached:
                level = levels_cached[level_name]

        packages_cached = get_packages_cached()
        package_names = set(request.GET.getlist('package')) & set(get_unlocked_packages_names(request))
        packages = [packages_cached[name] for name in package_names if name in packages_cached]
        if len(packages) == len(packages_cached):
            packages = []
        package_ids = sorted([package.id for package in packages])

        cache_key = '__'.join((
            ','.join([str(i) for i in types]),
            str(level.id) if level is not None else '',
            ','.join([str(i) for i in package_ids]),
        ))

        return self._list(request, types=types, level=level, packages=packages, add_cache_key=cache_key)

    @staticmethod
    def compare_by_location_type(x: AreaLocation, y: AreaLocation):
        return AreaLocation.LOCATION_TYPES.index(x.location_type) - AreaLocation.LOCATION_TYPES.index(y.location_type)

    @cache_mapdata_api_response()
    def _list(self, request, types, level, packages):
        results = []
        for t in types:
            mapitemtype = GEOMETRY_MAPITEM_TYPES[t]
            queryset = mapitemtype.objects.all()
            if packages:
                queryset = queryset.filter(package__in=packages)
            if level:
                if hasattr(mapitemtype, 'level'):
                    queryset = queryset.filter(level=level)
                elif hasattr(mapitemtype, 'levels'):
                    queryset = queryset.filter(levels=level)
                else:
                    queryset = queryset.none()
            queryset = filter_queryset_by_access(request, queryset)
            queryset = queryset.order_by('name')

            for field_name in ('package', 'level', 'crop_to_level', 'elevator'):
                if hasattr(mapitemtype, field_name):
                    queryset = queryset.select_related(field_name)

            for field_name in ('levels', ):
                if hasattr(mapitemtype, field_name):
                    queryset.prefetch_related(field_name)

            if issubclass(mapitemtype, AreaLocation):
                queryset = sorted(queryset, key=AreaLocation.get_sort_key)

            if issubclass(mapitemtype, DirectedLineGeometryMapItemWithLevel):
                results.extend(obj.to_shadow_geojson() for obj in queryset)

            results.extend(obj.to_geojson() for obj in queryset)

        return Response(results)


class PackageViewSet(CachedReadOnlyViewSetMixin, ReadOnlyModelViewSet):
    """
    Retrieve packages the map consists of.
    """
    queryset = Package.objects.all()
    serializer_class = PackageSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    ordering = ('name',)


class LevelViewSet(CachedReadOnlyViewSetMixin, ReadOnlyModelViewSet):
    """
    List and retrieve levels.
    """
    queryset = Level.objects.all()
    serializer_class = LevelSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    ordering = ('altitude',)


class SourceViewSet(CachedReadOnlyViewSetMixin, ReadOnlyModelViewSet):
    """
    List and retrieve source images (to use as a drafts).
    """
    queryset = Source.objects.all()
    serializer_class = SourceSerializer
    lookup_field = 'name'
    lookup_value_regex = '[^/]+'
    ordering = ('name',)
    include_package_access = True

    def get_queryset(self):
        return filter_queryset_by_access(self.request, super().get_queryset().all())

    @detail_route(methods=['get'])
    def image(self, request, name=None):
        return self._image(request, name=name, add_cache_key=self._get_add_cache_key(request))

    @cache_mapdata_api_response()
    def _image(self, request, name=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        image_path = os.path.join(settings.MAP_ROOT, source.package.directory, 'sources', source.name)
        for chunk in File(open(image_path, 'rb')).chunks():
            response.write(chunk)
        return response


class LocationViewSet(ViewSet):
    """
    List and retrieve locations
    """
    # We don't cache this, because it depends on access_list
    lookup_field = 'name'
    include_package_access = True

    @staticmethod
    def _filter(queryset):
        return queryset.filter(can_search=True).order_by('name')

    def list(self, request, **kwargs):
        etag = hashlib.sha256(json.dumps({
            'full_access': request.c3nav_full_access,
            'access_list': request.c3nav_access_list,
            'last_update': get_last_mapdata_update().isoformat()
        }).encode()).hexdigest()

        if_none_match = request.META.get('HTTP_IF_NONE_MATCH')
        if if_none_match:
            if if_none_match == etag:
                return HttpResponseNotModified()

        locations = []
        locations += list(filter_queryset_by_access(request, self._filter(LocationGroup.objects.all())))
        locations += sorted(filter_arealocations_by_access(request, self._filter(AreaLocation.objects.all())),
                            key=AreaLocation.get_sort_key, reverse=True)

        response = Response([location.to_location_json() for location in locations])
        response['ETag'] = etag
        response['Cache-Control'] = 'no-cache'
        return response

    def retrieve(self, request, name=None, **kwargs):
        location = get_location(request, name)
        if location is None:
            raise Http404
        return Response(location.to_json())

    @list_route(methods=['POST'])
    def wifilocate(self, request):
        stations = json.loads(request.POST['stations'])[:200]
        if not stations:
            return Response({})

        bssids = get_bssid_areas_cached()
        stations = sorted(stations, key=lambda l: l['level'])
        for station in stations:
            area_name = bssids.get(station['bssid'])
            if area_name is not None:
                location = get_location(request, area_name)
                if location is not None:
                    return Response({'location': location.to_location_json()});

        return Response({'location': None})
