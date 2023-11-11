from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.mapdata.api import api_stats_clean_location_value
from c3nav.mapdata.forms import PositionAPIUpdateForm
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.models.geometry.space import RangingBeacon
from c3nav.mapdata.models.locations import Position
from c3nav.mapdata.utils.cache.stats import increment_cache_key
from c3nav.mapdata.utils.locations import CustomLocation, visible_locations_for_request
from c3nav.routing.exceptions import LocationUnreachable, NoRouteFound, NotYetRoutable
from c3nav.routing.forms import RouteForm
from c3nav.routing.locator import Locator
from c3nav.routing.models import RouteOptions
from c3nav.routing.router import Router


class RoutingViewSet(ViewSet):
    """
    /route/ Get routes.
    /options/ Get or set route options.
    /locate/ Wifi locate.

    How to use the /locate/ endpoint:
    POST visible wifi stations as JSON data like this:
    {
        "stations": [
            {
                "bssid": "11:22:33:44:55:66",
                "ssid": "36C3",
                "level": -55,
                "frequency": 5500
            },
            ...
        ]
    }
    """
    @action(detail=False, methods=['get', 'post'])
    def route(self, request, *args, **kwargs):
        params = request.POST if request.method == 'POST' else request.GET
        form = RouteForm(params, request=request)

        if not form.is_valid():
            return Response({
                'errors': form.errors,
            }, status=400)

        options = RouteOptions.get_for_request(request)
        try:
            options.update(params, ignore_unknown=True)
        except ValidationError as e:
            return Response({
                'errors': (str(e), ),
            }, status=400)

        try:
            route = Router.load().get_route(origin=form.cleaned_data['origin'],
                                            destination=form.cleaned_data['destination'],
                                            permissions=AccessPermission.get_for_request(request),
                                            options=options)
        except NotYetRoutable:
            return Response({
                'error': _('Not yet routable, try again shortly.'),
            })
        except LocationUnreachable:
            return Response({
                'error': _('Unreachable location.'),
            })
        except NoRouteFound:
            return Response({
                'error': _('No route found.'),
            })

        origin_values = api_stats_clean_location_value(form.cleaned_data['origin'].pk)
        destination_values = api_stats_clean_location_value(form.cleaned_data['destination'].pk)
        increment_cache_key('apistats__route')
        for origin_value in origin_values:
            for destination_value in destination_values:
                increment_cache_key('apistats__route_tuple_%s_%s' % (origin_value, destination_value))
        for value in origin_values:
            increment_cache_key('apistats__route_origin_%s' % value)
        for value in destination_values:
            increment_cache_key('apistats__route_destination_%s' % value)

        return Response({
            'request': {
                'origin': self.get_request_pk(form.cleaned_data['origin']),
                'destination': self.get_request_pk(form.cleaned_data['destination']),
            },
            'options': options.serialize(),
            'report_issue_url': reverse('site.report_create', kwargs={
                'origin': request.POST['origin'],
                'destination': request.POST['destination'],
                'options': options.serialize_string()
            }),
            'result': route.serialize(locations=visible_locations_for_request(request)),
        })

    def get_request_pk(self, location):
        return location.slug if isinstance(location, Position) else location.pk

    @action(detail=False, methods=['get', 'post'])
    def options(self, request, *args, **kwargs):
        options = RouteOptions.get_for_request(request)

        if request.method == 'POST':
            try:
                options.update(request.POST, ignore_unknown=True)
            except ValidationError as e:
                return Response({
                    'errors': (str(e),),
                }, status=400)
            options.save()

        return Response(options.serialize())

    @action(detail=False, methods=('POST', ))
    def locate(self, request, *args, **kwargs):
        if isinstance(request.data, list):
            stations_data = request.data
            data = {}
        else:
            data = request.data
            if 'stations' not in data:
                return Response({
                    'errors': (_('stations is missing.'),),
                }, status=400)
            stations_data = data['stations']

        try:
            location = Locator.load().locate(stations_data, permissions=AccessPermission.get_for_request(request))
            if location is not None:
                increment_cache_key('apistats__locate__%s' % location.pk)
        except ValidationError:
            return Response({
                'errors': (_('Invalid scan data.'),),
            }, status=400)

        if 'set_position' in data and location:
            set_position = data['set_position']
            if not set_position.startswith('p:'):
                return Response({
                    'errors': (_('Invalid set_position.'),),
                }, status=400)

            try:
                position = Position.objects.get(secret=set_position[2:])
            except Position.DoesNotExist:
                return Response({
                    'errors': (_('Invalid set_position.'),),
                }, status=400)

            form_data = {
                **data,
                'coordinates_id': None if location is None else location.pk,
            }

            form = PositionAPIUpdateForm(instance=position, data=form_data, request=request)

            if not form.is_valid():
                return Response({
                    'errors': form.errors,
                }, status=400)

            form.save()

        return Response({'location': None if location is None else location.serialize(simple_geometry=True)})

    @action(detail=False)
    def locate_test(self, request):
        position = RangingBeacon.objects.select_related('space__level').first()
        if not position:
            return Response(None)
        location = CustomLocation(
            level=position.space.level,
            x=position.geometry.x,
            y=position.geometry.y,
            permissions=(),
            icon='my_location'
        )
        return Response({'location': location.serialize(simple_geometry=True)})
