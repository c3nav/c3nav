import os
import xml.etree.ElementTree as ET

import subprocess
from django.conf import settings
from django.db.models import Max, Min
from shapely.affinity import scale

from c3nav.mapdata.models import Package


class LevelRenderer():
    def __init__(self, level):
        self.level = level

    @staticmethod
    def get_dimensions():
        aggregate = Package.objects.all().aggregate(Max('right'), Min('left'), Max('top'), Min('bottom'))
        return (
            float(aggregate['right__max'] - aggregate['left__min']) * settings.RENDER_SCALE,
            float(aggregate['top__max'] - aggregate['bottom__min']) * settings.RENDER_SCALE
        )

    @staticmethod
    def polygon_svg(geometry, fill_color=None, fill_opacity=None, stroke_width=0.0, stroke_color=None, filter=None):
        scaled = scale(geometry, xfact=settings.render_scale, yfact=settings.render_scale, origin=(0, 0))
        element = ET.fromstring(scaled.svg(0, fill_color or '#FFFFFF'))
        if element.tag != 'g':
            new_element = ET.Element('g')
            new_element.append(element)
            element = new_element

        for path in element.findall('path'):
            path.attrib.pop('opacity')
            path.set('stroke-width', str(stroke_width * settings.RENDER_SCALE))

            if fill_color is None and 'fill' in path.attrib:
                path.attrib.pop('fill')
                path.set('fill-opacity', '0')

            if fill_opacity is not None:
                path.set('fill-opacity', str(fill_opacity))

            if stroke_color is not None:
                path.set('stroke', stroke_color)
            elif 'stroke' in path.attrib:
                path.attrib.pop('stroke')

            if filter is not None:
                path.set('filter', filter)

        return element

    def get_svg(self):
        width, height = self.get_dimensions()

        svg = ET.Element('svg', {
            'width': str(width),
            'height': str(height),
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
        })

        contents = ET.Element('g', {
            'transform': 'scale(1 -1) translate(0 -%d)' % (height),
        })
        svg.append(contents)

        contents.append(self.polygon_svg(self.level.geometries.buildings_with_holes,
                                         fill_color='#D5D5D5'))

        contents.append(self.polygon_svg(self.level.geometries.outsides,
                                         fill_color='#DCE6DC'))

        contents.append(self.polygon_svg(self.level.geometries.walls_shadow,
                                         fill_color='#000000',
                                         fill_opacity=0.06))

        contents.append(self.polygon_svg(self.level.geometries.elevatorlevels,
                                         fill_color='#9EF8FB'))

        contents.append(self.polygon_svg(self.level.geometries.doors,
                                         fill_color='#FFFFFF',
                                         stroke_color='#3c3c3c',
                                         stroke_width=0.05))

        contents.append(self.polygon_svg(self.level.geometries.obstacles,
                                         fill_color='#BDBDBD',
                                         stroke_color='#9E9E9E',
                                         stroke_width=0.05))

        contents.append(self.polygon_svg(self.level.geometries.walls,
                                         fill_color='#949494',
                                         stroke_color='#3c3c3c',
                                         stroke_width=0.05))

        return ET.tostring(svg).decode()

    def _get_render_path(self, filename):
        return os.path.join(settings.RENDER_ROOT, filename)

    def write_svg(self):
        filename = self._get_render_path('level-%s.svg' % self.level.name)
        with open(filename, 'w') as f:
            f.write(self.get_svg())
        return filename

    def render_png(self):
        svg_filename = self.write_svg()
        filename = self._get_render_path('level-%s.png' % self.level.name)
        subprocess.call(['rsvg-convert', svg_filename, '-o', filename])







