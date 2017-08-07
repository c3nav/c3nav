import os
from decimal import Decimal
from itertools import chain
from operator import itemgetter

from django.conf import settings
from django.db import models
from django.db.models import Prefetch
from django.utils.translation import ugettext_lazy as _
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, LineString
from shapely.ops import cascaded_union

from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.geometry import assert_multilinestring, assert_multipolygon
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

    def render_scad(self, f, low_clip=[], spaces=None, request=None):
        if spaces is None:
            from c3nav.mapdata.models import Area, Space
            spaces = self.spaces.filter(Space.q_for_request(request, allow_none=True)).prefetch_related(
                Prefetch('areas', Area.qs_for_request(request, allow_none=True)),
                'groups', 'columns', 'holes', 'areas__groups',
                'stairs', 'obstacles', 'lineobstacles'
            )

        buildings_geom = cascaded_union(tuple(b.geometry for b in self.buildings.all()))
        doors_geom = cascaded_union(tuple(d.geometry for d in self.doors.all()))
        space_geom = cascaded_union(tuple((s.geometry if not s.outside else s.geometry.difference(buildings_geom))
                                          for s in self.spaces.all()))
        accessible_area = cascaded_union((doors_geom, space_geom))
        for space in spaces:
            accessible_area = accessible_area.difference(space.geometry.intersection(
                cascaded_union(tuple(h.geometry for h in space.holes.all()))
            ))

        areas_by_altitude = {}
        for area in self.altitudeareas.all():
            areas_by_altitude.setdefault(area.altitude, []).append(area.geometry.buffer(0.01))
        areas_by_altitude = {altitude: [cascaded_union(areas)] for altitude, areas in areas_by_altitude.items()}

        accessible_area = accessible_area.difference(cascaded_union(tuple(chain(*areas_by_altitude.values()))))

        stairs = []
        for space in spaces:
            geom = space.geometry
            if space.outside:
                geom = space_geom.difference(buildings_geom)
            remaining_space = geom.intersection(accessible_area)
            if remaining_space.is_empty:
                continue

            max_len = ((geom.bounds[0]-geom.bounds[2])**2 + (geom.bounds[1]-geom.bounds[3])**2)**0.5
            stairs = []
            for stair in space.stairs.all():
                for substair in assert_multilinestring(stair.geometry):
                    for coord1, coord2 in zip(tuple(substair.coords)[:-1], tuple(substair.coords)[1:]):
                        line = LineString([coord1, coord2])
                        fact = (max_len*3) / line.length
                        scaled = scale(line, xfact=fact, yfact=fact)
                        stairs.append(scaled.buffer(0.0001, JOIN_STYLE.mitre).intersection(geom.buffer(0.0001)))
            if stairs:
                stairs = cascaded_union(stairs)
                remaining_space = remaining_space.difference(stairs)

            for polygon in assert_multipolygon(remaining_space.buffer(0)):
                center = polygon.centroid
                buffered = polygon.buffer(0.001, JOIN_STYLE.mitre)
                touches = tuple((altitude, buffered.intersection(areas[0]).area)
                                for altitude, areas in areas_by_altitude.items()
                                if buffered.intersects(areas[0]))
                if touches:
                    max_intersection = max(touches, key=itemgetter(1))[1]
                    altitude = max(altitude for altitude, area in touches if area > max_intersection/2)
                else:
                    altitude = min(areas_by_altitude.items(), key=lambda a: a[1][0].distance(center))[0]
                areas_by_altitude[altitude].append(polygon.buffer(0.001, JOIN_STYLE.mitre))

            # plot_geometry(remaining_space, title=space.title)

        areas_by_altitude = {altitude: [cascaded_union(areas)] for altitude, areas in areas_by_altitude.items()}

        for altitude, areas in areas_by_altitude.items():
            for area in areas:
                f.write('translate([0, 0, %.2f]) ' % (altitude-Decimal('0.5')))
                f.write('linear_extrude(height=0.5, center=false, convexity=20) ')
                f.write(polygon_scad(area) + ';\n')

    @classmethod
    def render_scad_all(cls, request=None):
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
        with open(filename, 'w') as f:
            for level in Level.objects.prefetch_related('buildings', 'doors', 'altitudeareas'):
                level.render_scad(f, spaces=level_spaces.get(level.pk, []))
