from django.conf import settings
from django.db import models
from django.utils.translation import ugettext_lazy as _
from shapely.geometry import JOIN_STYLE
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import EditorFormMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.utils.svg import SVGImage


class Section(SpecificLocation, EditorFormMixin, models.Model):
    """
    A map section like a level
    """
    altitude = models.DecimalField(_('section altitude'), null=False, unique=True, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Section')
        verbose_name_plural = _('Sections')
        default_related_name = 'sections'
        ordering = ['altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def lower(self):
        return Section.objects.filter(altitude__lt=self.altitude).order_by('altitude')

    def higher(self):
        return Section.objects.filter(altitude__gt=self.altitude).order_by('altitude')

    def _serialize(self, section=True, **kwargs):
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

        spaces = self.spaces.all().prefetch_related('groups', 'holes', 'areas', 'areas__groups',
                                                    'stairs', 'obstacles', 'lineobstacles')
        space_levels = {
            'upper': [],
            'lower': [],
            'normal': [],
        }
        for space in spaces:
            space_levels[space.level].append(space)
        for space in space_levels['normal']:
            if space.outside:
                space.geometry = space.geometry.difference(building_geometries)
            else:
                space.geometry = space.geometry.intersection(building_geometries)
        space_geometries = {level: cascaded_union(tuple(s.geometry for s in level_spaces))
                            for level, level_spaces in space_levels.items()}

        for space in spaces:
            space_holes = cascaded_union(tuple(hole.geometry for hole in space.holes.all()))
            space.hole_geometries = space_holes.intersection(space.geometry)

        hole_geometries = cascaded_union(tuple(space.hole_geometries for space in space_levels['normal']))

        lower_spaces_by_color = {}
        for space in space_levels['lower']:
            lower_spaces_by_color.setdefault(space.get_color(), []).append(space)
        for i, (color, color_spaces) in enumerate(lower_spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            svg.add_geometry(geometries, fill_color=color or '#d1d1d1')

        for space in space_levels['lower']:
            self._render_space_ground(svg, space)
            self._render_space_inventory(svg, space)

        # draw space background
        doors = self.doors.all()
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        section_geometry = cascaded_union((space_geometries['normal'], building_geometries, door_geometries))
        section_geometry = section_geometry.difference(hole_geometries)
        section_clip = svg.register_geometry(section_geometry, defid='section', as_clip_path=True)
        svg.add_geometry(fill_color='#d1d1d1', clip_path=section_clip)

        # color in spaces
        spaces_by_color = {}
        for space in space_levels['normal']:
            spaces_by_color.setdefault(space.get_color(), []).append(space)
        spaces_by_color.pop(None, None)
        spaces_by_color.pop('', None)
        for i, (color, color_spaces) in enumerate(spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            svg.add_geometry(geometries, fill_color=color)

        for space in space_levels['normal']:
            self._render_space_ground(svg, space)

        # calculate walls
        wall_geometry = building_geometries.difference(space_geometries['normal']).difference(door_geometries)

        # draw wall shadow
        if effects:
            wall_dilated_geometry = wall_geometry.buffer(0.7, join_style=JOIN_STYLE.mitre)
            svg.add_geometry(wall_dilated_geometry, fill_color='#000000', opacity=0.1, filter='wallblur',
                             clip_path=section_clip)

        for space in space_levels['normal']:
            self._render_space_inventory(svg, space)

        # draw walls
        svg.add_geometry(wall_geometry, fill_color='#929292', stroke_color='#333333', stroke_width=0.07)

        # draw doors
        door_geometries = cascaded_union(tuple(d.geometry for d in doors))
        door_geometries = door_geometries.difference(space_geometries['normal'])
        svg.add_geometry(door_geometries, fill_color='#ffffff', stroke_color='#929292', stroke_width=0.07)

        # draw upper spaces
        upper_spaces_by_color = {}
        for space in space_levels['upper']:
            upper_spaces_by_color.setdefault(space.get_color(), []).append(space)
        for i, (color, color_spaces) in enumerate(upper_spaces_by_color.items()):
            geometries = cascaded_union(tuple(space.geometry for space in color_spaces))
            svg.add_geometry(geometries, fill_color=color or '#d1d1d1')

        for space in space_levels['upper']:
            self._render_space_ground(svg, space)
            self._render_space_inventory(svg, space)

        return svg.get_xml()
