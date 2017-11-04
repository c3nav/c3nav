import os
from decimal import Decimal
from itertools import chain
from operator import attrgetter, itemgetter

from django.conf import settings
from django.db import models
from django.db.models import Prefetch
from django.urls import reverse
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE, box
from shapely.ops import cascaded_union

from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.geometry import assert_multipolygon
from c3nav.mapdata.utils.scad import add_indent, polygon_scad


class LevelManager(models.Manager):
    def get_queryset(self, *args, **kwargs):
        return super().get_queryset(*args, **kwargs).defer('render_data')


class Level(SpecificLocation, models.Model):
    """
    A map level
    """
    base_altitude = models.DecimalField(_('base altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    default_height = models.DecimalField(_('default space height'), max_digits=6, decimal_places=2, default=3.0)
    on_top_of = models.ForeignKey('mapdata.Level', null=True, on_delete=models.CASCADE,
                                  related_name='levels_on_top', verbose_name=_('on top of'))
    short_label = models.SlugField(max_length=20, verbose_name=_('short label'), unique=True)

    render_data = models.BinaryField(null=True)

    objects = LevelManager()

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'
        ordering = ['base_altitude']
        base_manager_name = 'objects'

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
        result['short_label'] = self.short_label
        result['on_top_of'] = self.on_top_of_id
        result['base_altitude'] = float(str(self.base_altitude))
        result['default_height'] = float(str(self.default_height))
        return result

    def details_display(self):
        result = super().details_display()
        result['display'].insert(3, (str(_('short label')), self.short_label))
        result['display'].extend([
            (str(_('outside only')), self.base_altitude),
            (str(_('default height')), self.default_height),
        ])
        result['editor_url'] = reverse('editor.levels.detail', kwargs={'pk': self.pk})
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
        from c3nav.mapdata.render.image.engines.svg import SVGImage
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
            space.geometry = space.geometry.difference(holes_geom)

        space_geometries = cascaded_union(tuple(space.geometry for space in spaces))
        hole_geometries = cascaded_union(tuple(space.hole_geometries for space in spaces)).difference(space_geometries)

        # draw space background
        doors = self.doors.filter(Door.q_for_request(request))
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        level_geometry = cascaded_union((space_geometries, building_geometries, door_geometries))
        level_geometry = level_geometry.difference(hole_geometries)
        level_clip = svg.register_clip_path(level_geometry, defid='level', as_clip_path=True)
        svg.add_geometry(fill_color='#ececec', clip_path=level_clip)

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
        wall_geometry = wall_geometry.difference(hole_geometries)

        # draw wall shadow
        if effects:
            wall_dilated_geometry = wall_geometry.buffer(0.5, join_style=JOIN_STYLE.mitre)
            svg.add_geometry(wall_dilated_geometry, fill_color='#000000', opacity=0.1, filter='wallblur',
                             clip_path=level_clip)

        for space in spaces:
            self._render_space_inventory(svg, space)

        # draw walls
        svg.add_geometry(wall_geometry, fill_color='#aaaaaa')

        # draw doors
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        door_geometries = door_geometries.difference(space_geometries)
        svg.add_geometry(door_geometries, fill_color='#ffffff')

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

    def _render_scad_polygon(self, f, geometry, altitude, height=Decimal('0.0'), low_clip=()):
        for low_altitude, low_area in low_clip:
            intersection = geometry.intersection(low_area)
            if not intersection.is_empty:
                geometry = geometry.difference(intersection)

                low_height = max(altitude - low_altitude, 0)
                total_height = low_height+height
                if total_height:
                    f.write('    ')
                    f.write('translate([0, 0, %.2f]) ' % (altitude - low_height))
                    f.write(add_indent(polygon_scad(intersection, total_height))[4:])
        if not geometry.is_empty:
            f.write('    ')
            f.write('translate([0, 0, %.2f]) ' % (altitude - Decimal('0.5')))
            f.write(add_indent(polygon_scad(geometry, height+Decimal('0.5')))[4:])

    def _render_scad(self, f, low_clip=(), spaces=None, request=None):
        f.write('    // '+self.title+'\n')

        if spaces is None:
            from c3nav.mapdata.models import Area, Space
            spaces = self.spaces.filter(Space.q_for_request(request, allow_none=True)).prefetch_related(
                Prefetch('areas', Area.qs_for_request(request, allow_none=True)),
                'groups', 'columns', 'holes', 'areas__groups',
                'stairs', 'obstacles', 'lineobstacles'
            )

        f.write('')

        for area in self.altitudeareas.all():
            area.geometry = area.geometry.buffer(0)
            self._render_scad_polygon(f, area.geometry, area.altitude, low_clip=low_clip)

        draw_obstacles = {}
        height_spaces = {}
        for space in spaces:
            columns = cascaded_union(tuple(columns.geometry for columns in space.columns.all()))
            space.geometry = space.geometry.difference(columns)
            if self.on_top_of_id is None and not space.outside:
                height = space.height or self.default_height
                height_spaces.setdefault(height, []).append(space.geometry)
            holes = cascaded_union(tuple(hole.geometry for hole in space.holes.all()))
            for lineobstacle in space.lineobstacles.all():
                lineobstacle.geometry = lineobstacle.buffered_geometry
            for obstacle in chain(space.obstacles.all(), space.lineobstacles.all()):
                geometry = obstacle.geometry.intersection(space.geometry).difference(holes)
                for altitudearea in self.altitudeareas.all():
                    intersection = geometry.intersection(altitudearea.geometry)
                    if not intersection.is_empty:
                        geometry = geometry.difference(intersection.buffer(0.001, join_style=JOIN_STYLE.mitre))
                        draw_obstacles.setdefault((altitudearea.altitude, obstacle.height), []).append(intersection)
                if not geometry.is_empty:
                    for polygon in assert_multipolygon(geometry):
                        center = polygon.centroid
                        altitude = min(self.altitudeareas.all(), key=lambda a: a.geometry.distance(center)).altitude
                        draw_obstacles.setdefault((altitude, obstacle.height), []).append(polygon)

        for (altitude, height), polygons in draw_obstacles.items():
            self._render_scad_polygon(f, cascaded_union(polygons), altitude, height, low_clip=low_clip)

        spaces_geom = cascaded_union(tuple(space.geometry for space in self.spaces.all() if not space.outside))
        buildings_geom = cascaded_union(tuple(building.geometry for building in self.buildings.all()))
        doors_geom = cascaded_union(tuple(door.geometry for door in self.doors.all()))
        walls_geom = buildings_geom.difference(doors_geom).difference(spaces_geom)

        drawn_walls = {}
        for height, polygons in sorted(height_spaces.items(), key=itemgetter(0)):
            polygons = cascaded_union(polygons)
            for area in self.altitudeareas.all():
                intersection = area.geometry.intersection(polygons)
                if not intersection.is_empty:
                    walls = intersection.buffer(0.5, join_style=JOIN_STYLE.mitre).intersection(walls_geom)
                    walls = walls.buffer(0.001, join_style=JOIN_STYLE.mitre)
                    self._render_scad_polygon(f, walls, area.altitude+height, low_clip=low_clip)
                    drawn_walls.setdefault(area.altitude+height, []).append(walls)

        remaining_walls_geom = walls_geom.difference(cascaded_union(tuple(chain(*drawn_walls.values()))))

        drawn_walls = {altitude: cascaded_union(walls) for altitude, walls in drawn_walls.items()}
        drawn_walls_sorted = sorted(drawn_walls.items(), key=itemgetter(0))
        for wall in assert_multipolygon(remaining_walls_geom):
            buffered = wall.buffer(0.001, join_style=JOIN_STYLE.mitre)
            try:
                altitude = next(iter(altitude for altitude, geom in drawn_walls_sorted if geom.intersects(buffered)))
            except StopIteration:
                altitude = min(drawn_walls_sorted, key=lambda a: buffered.distance(a[1]))[0]
            self._render_scad_polygon(f, buffered, altitude, low_clip=low_clip)

    @classmethod
    def _render_scad_levels(cls, levels, filename, level_spaces):
        bounds = cascaded_union(tuple(box(*level.bounds) for level in levels)).bounds
        center = tuple(box(*bounds).centroid.coords[0])
        min_altitude = min((level.min_altitude for level in levels), default=0)

        filename = os.path.join(settings.RENDER_ROOT, filename)
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

        if levels is None:
            levels = Level.objects
        levels = levels.prefetch_related('buildings', 'doors', 'altitudeareas').order_by('base_altitude')

        cls._render_scad_levels(levels, 'all.levels.scad', level_spaces)

        for level in levels:
            if level.on_top_of_id is not None:
                continue
            sublevels = tuple(sublevel for sublevel in levels if sublevel.on_top_of_id == level.pk)
            cls._render_scad_levels((level, )+sublevels, level.get_slug()+'.scad', level_spaces)
