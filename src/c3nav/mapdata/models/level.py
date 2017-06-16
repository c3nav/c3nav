from itertools import chain

from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import EditorFormMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.svg import SVGImage


class Level(SpecificLocation, EditorFormMixin, models.Model):
    """
    A map level
    """
    altitude = models.DecimalField(_('level altitude'), null=False, unique=True, max_digits=6, decimal_places=2)
    on_top_of = models.ForeignKey('mapdata.Level', null=True, on_delete=models.CASCADE,
                                  related_name='levels_on_top', verbose_name=_('on top of'))

    class Meta:
        verbose_name = _('Level')
        verbose_name_plural = _('Levels')
        default_related_name = 'levels'
        ordering = ['altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def lower(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(altitude__lt=self.altitude, on_top_of__isnull=True).order_by('-altitude')

    def higher(self, level_model=None):
        if self.on_top_of_id is not None:
            raise TypeError
        if level_model is None:
            level_model = Level
        return level_model.objects.filter(altitude__gt=self.altitude, on_top_of__isnull=True).order_by('altitude')

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
        result['altitude'] = float(str(self.altitude))
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

    def render_svg(self, effects=True, draw_spaces=None):
        from c3nav.mapdata.models import Source
        bounds = Source.max_bounds()
        svg = SVGImage(bounds=bounds, scale=settings.RENDER_SCALE)

        building_geometries = cascaded_union(tuple(b.geometry for b in self.buildings.all()))

        spaces = self.spaces.all().prefetch_related('groups', 'columns', 'holes', 'areas', 'areas__groups',
                                                    'stairs', 'obstacles', 'lineobstacles')
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
        doors = self.doors.all()
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
            svg.add_geometry(geometries, fill_color=color)

        for space in spaces:
            self._render_space_ground(svg, space)

        # calculate walls
        wall_geometry = building_geometries.difference(space_geometries).difference(door_geometries)

        # draw wall shadow
        if effects:
            wall_dilated_geometry = wall_geometry.buffer(0.7, join_style=JOIN_STYLE.mitre)
            svg.add_geometry(wall_dilated_geometry, fill_color='#000000', opacity=0.1, filter='wallblur',
                             clip_path=level_clip)

        for space in spaces:
            self._render_space_inventory(svg, space)

        # draw walls
        svg.add_geometry(wall_geometry, fill_color='#929292', stroke_color='#333333', stroke_width=0.07)

        # draw doors
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        door_geometries = door_geometries.difference(space_geometries)
        svg.add_geometry(door_geometries, fill_color='#ffffff', stroke_color='#929292', stroke_width=0.07)

        return svg.get_xml()
