import os
from decimal import Decimal
from itertools import chain
from operator import attrgetter

from django.conf import settings
from django.db import models
from django.db.models import Prefetch
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE, box
from shapely.ops import cascaded_union

from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.geometry import assert_multipolygon
from c3nav.mapdata.utils.scad import polygon_scad
from c3nav.mapdata.utils.svg import SVGImage


class Level(SpecificLocation, models.Model):
    """
    A map level
    """
    base_altitude = models.DecimalField(_('base altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    on_top_of = models.ForeignKey('mapdata.Level', null=True, on_delete=models.CASCADE,
                                  related_name='levels_on_top', verbose_name=_('on top of'))

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'
        ordering = ['base_altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def lower(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(base_altitude__lt=self.base_altitude,
                                          on_top_of__isnull=True).order_by('-base_altitude')

    def higher(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(base_altitude__gt=self.base_altitude,
                                          on_top_of__isnull=True).order_by('base_altitude')

    @property
    def sublevels(self):
        if self.on_top_of is not None:
            raise TypeError
        return chain((self, ), self.levels_on_top.all())

    @property
    def sublevel_title(self):
        return '-' if self.on_top_of_id is None else self.title

    @property
    def primary_level(self):
        return self if self.on_top_of_id is None else self.on_top_of

    @property
    def primary_level_pk(self):
        return self.pk if self.on_top_of_id is None else self.on_top_of_id

    def _serialize(self, level=True, **kwargs):
        result = super()._serialize(**kwargs)
        result['base_altitude'] = float(str(self.base_altitude))
        return result

    def _render_space_ground(self, svg, space):
        areas_by_color = {}
        for area in space.areas.all():
            areas_by_color.setdefault(area.get_color(), []).append(area)
        areas_by_color.pop(None, None)
        areas_by_color.pop('', None)
        for i, (color, color_areas) in enumerate(areas_by_color.items()):
            geometries = cascaded_union(tuple(area.geometry for area in color_areas)).intersection(space.geometry)
            svg.add_geometry(geometries, fill_color=color)

        stair_geometries = tuple(stair.geometry for stair in space.stairs.all())
        svg.add_geometry(cascaded_union(stair_geometries).intersection(space.geometry),
                         stroke_width=0.06, stroke_color='#000000', opacity=0.15)
        for i in range(2):
            svg.add_geometry(cascaded_union(tuple(g.parallel_offset(0.06+0.04*i, 'right', join_style=JOIN_STYLE.mitre)
                                                  for g in stair_geometries)).intersection(space.geometry),
                             stroke_width=0.04, stroke_color='#000000', opacity=0.07-0.05*i)

    def _render_space_inventory(self, svg, space):
        obstacle_geometries = cascaded_union(
            tuple(obstacle.geometry for obstacle in space.obstacles.all()) +
            tuple(obstacle.buffered_geometry for obstacle in space.lineobstacles.all())
        ).intersection(space.geometry)
        svg.add_geometry(obstacle_geometries, fill_color='#999999')

    def render_svg(self, request, effects=True, draw_spaces=None):
        from c3nav.mapdata.models import Source, Area, Door, Space

        bounds = Source.max_bounds()
        svg = SVGImage(bounds=bounds, scale=settings.RENDER_SCALE)

        building_geometries = cascaded_union(tuple(b.geometry for b in self.buildings.all()))

        spaces = self.spaces.filter(Space.q_for_request(request)).prefetch_related(
            Prefetch('areas', Area.qs_for_request(request)),
            'groups', 'columns', 'holes', 'areas__groups',
            'stairs', 'obstacles', 'lineobstacles'
        )
        for space in spaces:
            if space.outside:
                space.geometry = space.geometry.difference(building_geometries)
            columns_geom = cascaded_union(tuple(column.geometry for column in space.columns.all()))
            holes_geom = cascaded_union(tuple(hole.geometry for hole in space.holes.all()))
            space.geometry = space.geometry.difference(columns_geom)
            space.hole_geometries = holes_geom.intersection(space.geometry)

        space_geometries = cascaded_union(tuple(space.geometry for space in spaces))
        hole_geometries = cascaded_union(tuple(space.hole_geometries for space in spaces))

        # draw space background
        doors = self.doors.filter(Door.q_for_request(request))
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        level_geometry = cascaded_union((space_geometries, building_geometries, door_geometries))
        level_geometry = level_geometry.difference(hole_geometries)
        level_clip = svg.register_geometry(level_geometry, defid='level', as_clip_path=True)
        svg.add_geometry(fill_color='#d1d1d1', clip_path=level_clip)

        # color in spaces
        spaces_by_color = {}
        for space in spaces:
            spaces_by_color.setdefault(space.get_color(), []).append(space)
        spaces_by_color.pop(None, None)
        spaces_by_color.pop('', None)
        for i, (color, color_spaces) in enumerate(spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            svg.add_geometry(geometries.intersection(level_geometry), fill_color=color)

        for space in spaces:
            self._render_space_ground(svg, space)

        # calculate walls
        wall_geometry = building_geometries.difference(space_geometries).difference(door_geometries)

        # draw wall shadow
        if effects:
            wall_dilated_geometry = wall_geometry.buffer(0.5, join_style=JOIN_STYLE.mitre)
            svg.add_geometry(wall_dilated_geometry, fill_color='#000000', opacity=0.1, filter='wallblur',
                             clip_path=level_clip)

        for space in spaces:
            self._render_space_inventory(svg, space)

        # draw walls
        svg.add_geometry(wall_geometry, fill_color='#929292', stroke_color='#333333', stroke_width=0.05)

        # draw doors
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        door_geometries = door_geometries.difference(space_geometries)
        svg.add_geometry(door_geometries, fill_color='#ffffff', stroke_color='#929292', stroke_width=0.05)

        return svg.get_xml()

    @staticmethod
    def _give_height_to_areas_with_one_neighbor(accessible_area, areas_by_altitude):
        # give height to all obstacles that touch only one altitude
        remaining_polygons = []
        for polygon in assert_multipolygon(accessible_area):
            buffered = polygon.buffer(0.001)
            found_altitude = None
            for altitude, area in areas_by_altitude.items():
                if buffered.intersects(area[0]):
                    if found_altitude is not None:
                        found_altitude = None
                        break
                    found_altitude = altitude
            if found_altitude is None:
                remaining_polygons.append(polygon)
            else:
                areas_by_altitude[found_altitude].append(polygon)
        return cascaded_union(remaining_polygons)

    @cached_property
    def min_altitude(self):
        return min(self.altitudeareas.all(), key=attrgetter('altitude'), default=self.base_altitude).altitude

    @cached_property
    def bounds(self):
        return cascaded_union(tuple(item.geometry.buffer(0)
                                    for item in chain(self.altitudeareas.all(), self.buildings.all()))).bounds

    def _render_scad(self, f, low_clip=(), spaces=None, request=None):
        if spaces is None:
            from c3nav.mapdata.models import Area, Space
            spaces = self.spaces.filter(Space.q_for_request(request, allow_none=True)).prefetch_related(
                Prefetch('areas', Area.qs_for_request(request, allow_none=True)),
                'groups', 'columns', 'holes', 'areas__groups',
                'stairs', 'obstacles', 'lineobstacles'
            )

        for area in self.altitudeareas.all():
            geometry = area.geometry
            for low_altitude, low_area in low_clip:
                intersection = geometry.intersection(low_area)
                if not intersection.is_empty:
                    geometry = geometry.difference(intersection)
                    width = max(area.altitude - low_altitude, 0)
                    if width:
                        f.write('    ')
                        f.write('translate([0, 0, %.2f]) ' % (area.altitude - width))
                        f.write('linear_extrude(height=%.2f, center=false, convexity=20) ' % width)
                        f.write(polygon_scad(area.geometry) + ';\n')
            if not geometry.is_empty:
                f.write('    ')
                f.write('translate([0, 0, %.2f]) ' % (area.altitude - Decimal('0.5')))
                f.write('linear_extrude(height=0.5, center=false, convexity=20) ')
                f.write(polygon_scad(area.geometry) + ';\n')

    @classmethod
    def render_scad_all(cls, levels=None, request=None):
        from c3nav.mapdata.models import Level, Area, Space
        spaces = Space.objects.filter(Space.q_for_request(request, allow_none=True)).prefetch_related(
            Prefetch('areas', Area.qs_for_request(request, allow_none=True)),
            'groups', 'columns', 'holes', 'areas__groups',
            'stairs', 'obstacles', 'lineobstacles'
        )
        level_spaces = {}
        for space in spaces:
            level_spaces.setdefault(space.level_id, []).append(space)
        filename = os.path.join(settings.RENDER_ROOT, 'all.scad')

        if levels is None:
            levels = Level.objects
        levels = levels.prefetch_related('buildings', 'doors', 'altitudeareas').order_by('base_altitude')

        bounds = cascaded_union(tuple(box(*level.bounds) for level in levels)).bounds
        center = tuple(box(*bounds).centroid.coords[0])
        min_altitude = min((level.min_altitude for level in levels), default=0)

        with open(filename, 'w') as f:
            f.write('translate([%.2f, %.2f, %.2f]) {\n' % (0-center[0], 0-center[1], 0-min_altitude+Decimal('0.5')))
            first = True
            for level in levels:
                low_clip = []
                if first:
                    low_clip = [(level.min_altitude-Decimal('0.5'), box(*bounds))]
                    first = False
                level._render_scad(f, spaces=level_spaces.get(level.pk, []), low_clip=low_clip)
            f.write('}\n')
