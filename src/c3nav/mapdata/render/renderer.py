import os
import xml.etree.ElementTree as ET

from django.conf import settings
from django.db.models import Max, Min
from shapely.affinity import scale
from shapely.geometry import box

from c3nav.mapdata.models import Package


class LevelRenderer():
    def __init__(self, level):
        self.level = level

    @staticmethod
    def get_dimensions():
        aggregate = Package.objects.all().aggregate(Max('right'), Min('left'), Max('top'), Min('bottom'))
        return (
            (aggregate['right__max'] - aggregate['left__min']) * 32,
            (aggregate['top__max'] - aggregate['bottom__min']) * 32
        )

    @staticmethod
    def polygon_svg(geometry, fill_color=None, stroke_width=0.0, stroke_color=None, filter=None):
        element = ET.fromstring(scale(geometry, xfact=32, yfact=32, origin=(0, 0)).svg(0, fill_color or '#FFFFFF'))
        if element.tag != 'g':
            new_element = ET.Element('g')
            new_element.append(element)
            element = new_element

        for path in element.findall('path'):
            path.attrib.pop('opacity')
            path.set('stroke-width', str(stroke_width))

            if fill_color is None and 'fill' in path.attrib:
                path.attrib.pop('fill')
                path.set('fill-opacity', '0')

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

        contents.append(self.polygon_svg(box(0, 0, width, height), fill_color='#000000'))

        contents.append(self.polygon_svg(self.level.geometries.buildings,
                                         fill_color='#D5D5D5'))

        contents.append(self.polygon_svg(self.level.geometries.walls_shadow,
                                         fill_color='#CCCCCC'))

        contents.append(self.polygon_svg(self.level.geometries.doors,
                                         fill_color='#FFFFFF',
                                         stroke_color='#CCCCCC',
                                         stroke_width=2))

        contents.append(self.polygon_svg(self.level.geometries.obstacles,
                                         fill_color='#BDBDBD',
                                         stroke_color='#9E9E9E',
                                         stroke_width=3))

        contents.append(self.polygon_svg(self.level.geometries.walls_without_doors,
                                         fill_color='#949494',
                                         stroke_color='#757575',
                                         stroke_width=3))

        return ET.tostring(svg).decode()

    def write_svg(self):
        filename = os.path.join(settings.RENDER_ROOT, 'level-%s.svg' % self.level.name)
        with open(filename, 'w') as f:
            f.write(self.get_svg())
