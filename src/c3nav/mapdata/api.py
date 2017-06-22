import mimetypes
import operator
from functools import reduce

from django.db.models import Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import redirect
from django.utils.translation import ugettext_lazy as _
from rest_framework.decorators import detail_route, list_route
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.mixins import RetrieveModelMixin
from rest_framework.response import Response
from rest_framework.viewsets import GenericViewSet, ReadOnlyModelViewSet

from c3nav.mapdata.models import Building, Door, Hole, LocationGroup, Source, Space
from c3nav.mapdata.models.geometry.level import LevelGeometryMixin
from c3nav.mapdata.models.geometry.space import Area, Column, LineObstacle, Obstacle, Point, SpaceGeometryMixin, Stair
from c3nav.mapdata.models.level import Level
from c3nav.mapdata.models.locations import Location, LocationRedirect, LocationSlug, SpecificLocation
from c3nav.mapdata.utils.models import get_submodels


def optimize_query(qs):
    if issubclass(qs.model, SpecificLocation):
        qs = qs.prefetch_related(Prefetch('groups', queryset=LocationGroup.objects.only('id')))
    return qs


class MapdataViewSet(ReadOnlyModelViewSet):
    def list(self, request, *args, **kwargs):
        qs = optimize_query(self.get_queryset())
        geometry = ('geometry' in request.GET)
        if issubclass(qs.model, LevelGeometryMixin) and 'level' in request.GET:
            if not request.GET['level'].isdigit():
                raise ValidationError(detail={'detail': _('%s is not an integer.') % 'level'})
            try:
                level = Level.objects.get(pk=request.GET['level'])
            except Level.DoesNotExist:
                raise NotFound(detail=_('level not found.'))
            qs = qs.filter(level=level)
        if issubclass(qs.model, SpaceGeometryMixin) and 'space' in request.GET:
            if not request.GET['space'].isdigit():
                raise ValidationError(detail={'detail': _('%s is not an integer.') % 'space'})
            try:
                space = Space.objects.get(pk=request.GET['space'])
            except Space.DoesNotExist:
                raise NotFound(detail=_('space not found.'))
            qs = qs.filter(space=space)
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

    def retrieve(self, request, *args, **kwargs):
        return Response(self.get_object().serialize())

    @staticmethod
    def list_types(models_list, **kwargs):
        return Response([
            model.serialize_type(**kwargs) for model in models_list
        ])


class LevelViewSet(MapdataViewSet):
    """ Add ?on_top_of=null or ?on_top_of=<id> to filter by on_top_of. """
    queryset = Level.objects.all()

    @list_route(methods=['get'])
    def geometrytypes(self, request):
        return self.list_types(get_submodels(LevelGeometryMixin))

    @detail_route(methods=['get'])
    def svg(self, requests, pk=None):
        level = self.get_object()
        response = HttpResponse(level.render_svg(), 'image/svg+xml')
        return response


class BuildingViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Building.objects.all()


class SpaceViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Space.objects.all()

    @list_route(methods=['get'])
    def geometrytypes(self, request):
        return self.list_types(get_submodels(SpaceGeometryMixin))


class DoorViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?level=<id> to filter by level. """
    queryset = Door.objects.all()


class HoleViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Hole.objects.all()


class AreaViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
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


class PointViewSet(MapdataViewSet):
    """ Add ?geometry=1 to get geometries, add ?space=<id> to filter by space. """
    queryset = Point.objects.all()


class LocationGroupViewSet(MapdataViewSet):
    queryset = LocationGroup.objects.all()


class LocationViewSet(RetrieveModelMixin, GenericViewSet):
    """
    only accesses locations that have can_search or can_describe set to true.
    add ?detailed=1 to show all attributes.
    /{id}/ add ?show_redirect=1 to suppress redirects and show them as JSON.
    /search/ only accesses locations that have can_search set to true. Add GET Parameter “s” to search.
    """
    queryset = LocationSlug.objects.all()
    lookup_field = 'slug'

    def list(self, request, *args, **kwargs):
        detailed = 'detailed' in request.GET

        queryset = self.get_queryset().order_by('id')
        conditions = []
        for model in get_submodels(Location):
            conditions.append(Q(**{model._meta.default_related_name+'__isnull': False}) &
                              (Q(**{model._meta.default_related_name + '__can_search': True}) |
                               Q(**{model._meta.default_related_name + '__can_describe': True})))
        queryset = queryset.filter(reduce(operator.or_, conditions))

        if detailed:
            for model in get_submodels(SpecificLocation):
                queryset = queryset.prefetch_related(Prefetch(model._meta.default_related_name+'__groups',
                                                              queryset=LocationGroup.objects.only('id', 'titles')))

        return Response([obj.get_child().serialize(include_type=True, detailed=detailed) for obj in queryset])

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
    def types(self, request):
        return MapdataViewSet.list_types(get_submodels(Location), geomtype=False)

    @list_route(methods=['get'])
    def redirects(self, request):
        return Response([obj.serialize(include_type=False) for obj in LocationRedirect.objects.all().order_by('id')])

    @list_route(methods=['get'])
    def search(self, request):
        detailed = 'detailed' in request.GET
        search = request.GET.get('s')

        queryset = self.get_queryset().order_by('id')
        conditions = []
        for model in get_submodels(Location):
            conditions.append(Q(**{model._meta.default_related_name + '__isnull': False}) &
                              Q(**{model._meta.default_related_name + '__can_search': True}))
        queryset = queryset.filter(reduce(operator.or_, conditions))

        if detailed:
            for model in get_submodels(SpecificLocation):
                queryset = queryset.prefetch_related(Prefetch(model._meta.default_related_name+'__groups',
                                                              queryset=LocationGroup.objects.only('id', 'titles')))

        if not search:
            return Response([obj.serialize(include_type=True, detailed=detailed) for obj in queryset])

        words = search.lower().split(' ')[:10]
        results = queryset
        for word in words:
            results = [r for r in results if (word in r.title.lower() or (r.slug and word in r.slug.lower()))]
        # todo: rank results
        return Response([obj.serialize(include_type=True, detailed='detailed' in request.GET) for obj in results])


class SourceViewSet(MapdataViewSet):
    queryset = Source.objects.all()

    @detail_route(methods=['get'])
    def image(self, request, pk=None):
        return self._image(request, pk=pk)

    def _image(self, request, pk=None):
        source = self.get_object()
        response = HttpResponse(content_type=mimetypes.guess_type(source.name)[0])
        response.write(source.image)
        return response
