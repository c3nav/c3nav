from itertools import chain

from rest_framework.decorators import list_route
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from shapely.ops import cascaded_union

from c3nav.mapdata.models import Area, Section, Space


class EditorViewSet(ViewSet):
    """
    Editor API
    /geometries/ returns a list of geojson features, you have to specify ?section=<id> or ?space=<id>
    /geometrystyles/ returns styling information for all geometry types
    """
    @list_route(methods=['get'])
    def geometries(self, request, *args, **kwargs):
        section = request.GET.get('section')
        space = request.GET.get('space')
        if section is not None:
            if space is not None:
                raise ValidationError('Only section or space can be specified.')
            section = get_object_or_404(Section, pk=section)
            holes = section.holes.all()
            holes_geom = cascaded_union([hole.geometry for hole in holes])
            buildings = section.buildings.all()
            spaces = section.spaces.all()
            spaces_geom = cascaded_union([space.geometry for space in spaces if space.level == 'normal'])
            holes_geom = holes_geom.intersection(spaces_geom)
            doors = section.doors.all()
            for obj in chain(buildings, (s for s in spaces if s.level == 'normal')):
                obj.geometry = obj.geometry.difference(holes_geom)

            results = []

            def add_spaces(level):
                results.extend(space for space in spaces if space.level == level)
                results.extend((area for area in Area.objects.filter(space__section=section, space__level=level)
                                if area.get_color()))

            add_spaces('lower')

            results.extend(buildings)
            for door in section.doors.all():
                results.append(door)

            add_spaces('normal')
            add_spaces('upper')
            return Response([obj.to_geojson() for obj in results])
        elif space is not None:
            space = get_object_or_404(Space, pk=space)
            section = space.section

            doors = [door for door in section.doors.all() if door.geometry.intersects(space.geometry)]
            doors_geom = cascaded_union([door.geometry for door in doors])

            spaces = [s for s in section.spaces.filter(level='normal')
                      if s.geometry.intersects(doors_geom) and s.pk != space.pk]

            space.bounds = True

            results = chain(
                section.buildings.all(),
                doors,
                spaces,
                [space],
                space.areas.all(),
                space.stairs.all(),
                space.obstacles.all(),
                space.lineobstacles.all(),
                space.points.all(),
            )
            return Response(sum([self._get_geojsons(obj) for obj in results], ()))
        else:
            raise ValidationError('No section or space specified.')

    def _get_geojsons(self, obj):
        return ((obj.to_shadow_geojson(),) if hasattr(obj, 'to_shadow_geojson') else ()) + (obj.to_geojson(),)

    @list_route(methods=['get'])
    def geometrystyles(self, request, *args, **kwargs):
        return Response({
            'building': '#929292',
            'space': '#d1d1d1',
            'hole': 'rgba(255, 0, 0, 0.3)',
            'door': '#ffffff',
            'area': 'rgba(85, 170, 255, 0.5)',
            'stair': 'rgba(160, 0, 160, 0.5)',
            'obstacle': '#999999',
            'lineobstacle': '#999999',
            'point': '#4488cc',
            'shadow': '#000000',
        })
