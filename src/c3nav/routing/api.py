from rest_framework.decorators import list_route
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.routing.forms import RouteForm
from c3nav.routing.router import Router


class RoutingViewSet(ViewSet):
    """
    Routing API
    /geometries/ returns a list of geojson features, you have to specify ?level=<id> or ?space=<id>
    /geometrystyles/ returns styling information for all geometry types
    /bounds/ returns the maximum bounds of the map
    """

    def list(self, request):
        return []

    @list_route(methods=['get'])
    def route(self, request, *args, **kwargs):
        params = request.POST if request.method == 'POST' else request.GET
        form = RouteForm(params, request=request)

        if not form.is_valid():
            return Response({
                'errors': form.errors,
            })

        route = Router.load().get_route(form.cleaned_data['origin'], form.cleaned_data['destination'])

        return Response(route.serialize())
