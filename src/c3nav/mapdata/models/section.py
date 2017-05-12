from django.conf import settings
from django.db import models
from django.utils.functional import cached_property
from django.utils.translation import ugettext_lazy as _
from shapely.ops import cascaded_union

from c3nav.mapdata.models.base import EditorFormMixin
from c3nav.mapdata.models.locations import SpecificLocation
from c3nav.mapdata.render.svg import SVGImage
from c3nav.mapdata.utils.misc import get_dimensions


class Section(SpecificLocation, EditorFormMixin, models.Model):
    """
    A map section like a level
    """
    name = models.SlugField(_('section name'), unique=True, max_length=50)
    altitude = models.DecimalField(_('section altitude'), null=False, unique=True, max_digits=6, decimal_places=2)

    class Meta:
        verbose_name = _('Section')
        verbose_name_plural = _('Sections')
        default_related_name = 'sections'
        ordering = ['altitude']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @cached_property
    def public_geometries(self):
        return SectionGeometries.by_section(self, only_public=True)

    @cached_property
    def geometries(self):
        return SectionGeometries.by_section(self, only_public=False)

    def lower(self):
        return Section.objects.filter(altitude__lt=self.altitude).order_by('altitude')

    def higher(self):
        return Section.objects.filter(altitude__gt=self.altitude).order_by('altitude')

    def _serialize(self, section=True, **kwargs):
        result = super()._serialize(**kwargs)
        result['name'] = self.name
        result['altitude'] = float(str(self.altitude))
        return result

    def render_svg(self):
        width, height = get_dimensions()
        svg = SVGImage(width=width, height=height, scale=settings.RENDER_SCALE)

        building_geometries = cascaded_union(tuple(b.geometry for b in self.buildings.all()))

        spaces = self.spaces.all()
        space_levels = {
            'upper': [],
            'lower': [],
            '': [],
        }
        for space in spaces:
            space_levels[space.level].append(space)
        space_geometries = {
            level: cascaded_union(tuple((s.geometry.difference(building_geometries) if s.outside else s.geometry)
                                         for s in level_spaces))
            for level, level_spaces in space_levels.items()}

        hole_geometries = cascaded_union(tuple(h.geometry for h in self.holes.all()))
        hole_geometries = hole_geometries.intersection(space_geometries[''])
        hole_svg = svg.add_geometry(hole_geometries, 'holes')
        hole_mask = svg.add_mask(hole_svg, inverted=True, defid='holes-mask')

        space_lower_svg = svg.add_geometry(space_geometries['lower'], defid='spaces-lower')
        svg.use_geometry(space_lower_svg, fill_color='#d1d1d1')

        space_svg = svg.add_geometry(space_geometries[''], defid='spaces')
        space_hole_mask = svg.add_mask(space_svg, hole_svg, inverted=True, defid='spaces_mask')
        svg.use_geometry(space_svg, fill_color='#d1d1d1', mask=hole_mask)

        building_svg = svg.add_geometry(building_geometries, 'buildings')
        svg.use_geometry(building_svg, fill_color='#929292', mask=space_hole_mask)

        svg.use_geometry(space_svg, stroke_color='#333333', stroke_width=0.08)
        svg.use_geometry(building_svg, stroke_color='#333333', stroke_width=0.10)

        door_geometries = cascaded_union(tuple(d.geometry for d in self.doors.all()))
        door_geometries = door_geometries.difference(space_geometries[''])
        door_svg = svg.add_geometry(door_geometries, defid='doors')
        svg.use_geometry(door_svg, fill_color='#ffffff')

        space_upper_svg = svg.add_geometry(space_geometries['upper'], defid='spaces-upper')
        svg.use_geometry(space_upper_svg, fill_color='#d1d1d1')
        return svg.get_xml()
