from django.utils.translation import ugettext_lazy as _
from rest_framework.decorators import list_route
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.utils.locations import visible_locations_for_request
from c3nav.routing.exceptions import LocationUnreachable, NoRouteFound, NotYetRoutable
from c3nav.routing.forms import RouteForm
from c3nav.routing.router import Router


class RoutingViewSet(ViewSet):
    @list_route(methods=['get', 'post'])
    def route(self, request, *args, **kwargs):
        params = request.POST if request.method == 'POST' else request.GET
        form = RouteForm(params, request=request)

        if not form.is_valid():
            return Response({
                'errors': form.errors,
            })

        try:
            route = Router.load().get_route(origin=form.cleaned_data['origin'],
                                            destination=form.cleaned_data['destination'],
                                            permissions=AccessPermission.get_for_request(request))
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

        return Response({
            'request': {
                'origin': form.cleaned_data['origin'].pk,
                'destination': form.cleaned_data['destination'].pk,
            },
            'result': route.serialize(locations=visible_locations_for_request(request)),
        })
