from itertools import chain

from rest_framework.decorators import list_route
from rest_framework.exceptions import ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet
from shapely.ops import cascaded_union

from c3nav.mapdata.models import Section, Space


class EditorViewSet(ViewSet):
    """
    Editor API
    /geometries/ returns a list of geojson features, you have to specify ?section=<id> or ?space=<id>
    /geometrystyles/ returns styling information for all geometry types
    """
    def _get_section_geometries(self, section: Section):
        buildings = section.buildings.all()
        buildings_geom = cascaded_union([building.geometry for building in buildings])
        spaces = {space.id: space for space in section.spaces.all()}
        holes_geom = []
        for space in spaces.values():
            if space.outside:
                space.geometry = space.geometry.difference(buildings_geom)
            columns_geom = cascaded_union([column.geometry for column in space.columns.all()])
            space.geometry = space.geometry.difference(columns_geom)
            space_holes_geom = cascaded_union([hole.geometry for hole in space.holes.all()])
            holes_geom.append(space_holes_geom.intersection(space.geometry))
            space.geometry = space.geometry.difference(space_holes_geom)
        holes_geom = cascaded_union(holes_geom)

        for building in buildings:
            building.original_geometry = building.geometry
        for obj in chain(buildings, spaces.values()):
            obj.geometry = obj.geometry.difference(holes_geom)

        results = []
        results.extend(buildings)
        for door in section.doors.all():
            results.append(door)

        results.extend(spaces.values())
        return results

    def _get_sections_pk(self, section):
        sections_under = ()
        sections_on_top = ()
        lower_section = section.lower().first()
        primary_sections = (section,) + ((lower_section,) if lower_section else ())
        secondary_sections = Section.objects.filter(on_top_of__in=primary_sections).values_list('pk', 'on_top_of')
        if lower_section:
            sections_under = tuple(pk for pk, on_top_of in secondary_sections if on_top_of == lower_section.pk)
        if True:
            sections_on_top = tuple(pk for pk, on_top_of in secondary_sections if on_top_of == section.pk)
        sections = chain([section.pk], sections_under, sections_on_top)
        return sections, sections_on_top, sections_under

    @list_route(methods=['get'])
    def geometries(self, request, *args, **kwargs):
        section = request.GET.get('section')
        space = request.GET.get('space')
        if section is not None:
            if space is not None:
                raise ValidationError('Only section or space can be specified.')
            section = get_object_or_404(Section, pk=section)

            sections, sections_on_top, sections_under = self._get_sections_pk(section)
            sections = Section.objects.filter(pk__in=sections).prefetch_related('buildings', 'spaces', 'doors',
                                                                                'spaces__groups', 'spaces__holes',
                                                                                'spaces__columns')
            sections = {s.pk: s for s in sections}

            section = sections[section.pk]
            sections_under = [sections[pk] for pk in sections_under]
            sections_on_top = [sections[pk] for pk in sections_on_top]

            results = chain(
                *(self._get_section_geometries(s) for s in sections_under),
                self._get_section_geometries(section),
                *(self._get_section_geometries(s) for s in sections_on_top)
            )

            return Response([obj.to_geojson() for obj in results])
        elif space is not None:
            space = get_object_or_404(Space.objects.select_related('section'), pk=space)
            section = space.section

            doors = [door for door in section.doors.all() if door.geometry.intersects(space.geometry)]
            doors_space_geom = cascaded_union([door.geometry for door in doors]+[space.geometry])

            sections, sections_on_top, sections_under = self._get_sections_pk(section)
            other_spaces = Space.objects.filter(section__pk__in=sections).prefetch_related('groups')
            other_spaces = [s for s in other_spaces
                            if s.geometry.intersects(doors_space_geom) and s.pk != space.pk]

            space.bounds = True

            buildings = section.buildings.all()
            buildings_geom = cascaded_union([building.geometry for building in buildings])
            for other_space in other_spaces:
                if other_space.outside:
                    other_space.geometry = other_space.geometry.difference(buildings_geom)
                other_space.opacity = 0.4
                other_space.color = '#ffffff'
            for building in buildings:
                building.opacity = 0.5

            results = chain(
                buildings,
                doors,
                [space],
                space.areas.all().prefetch_related('groups'),
                space.holes.all(),
                space.stairs.all(),
                space.obstacles.all(),
                space.lineobstacles.all(),
                space.columns.all(),
                space.points.all().prefetch_related('groups'),
                other_spaces,
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
            'area': 'rgba(85, 170, 255, 0.2)',
            'stair': 'rgba(160, 0, 160, 0.5)',
            'obstacle': '#999999',
            'lineobstacle': '#999999',
            'column': '#888888',
            'point': '#4488cc',
            'shadow': '#000000',
        })
