import os
import subprocess
import xml.etree.ElementTree as ET

from django.conf import settings
from django.db.models import Max, Min
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, box

from c3nav.mapdata.models import Package


def get_render_path(filename):
    return os.path.join(settings.RENDER_ROOT, filename)


def get_dimensions():
    aggregate = Package.objects.all().aggregate(Max('right'), Min('left'), Max('top'), Min('bottom'))
    return (
        float(aggregate['right__max'] - aggregate['left__min']),
        float(aggregate['top__max'] - aggregate['bottom__min']),
    )


class LevelRenderer():
    def __init__(self, level):
        self.level = level

    @staticmethod
    def get_dimensions():
        width, height = get_dimensions()
        return (width * settings.RENDER_SCALE, height * settings.RENDER_SCALE)

    @staticmethod
    def polygon_svg(geometry, fill_color=None, fill_opacity=None,
                    stroke_width=0.0, stroke_color=None, stroke_opacity=None):
        scaled = scale(geometry, xfact=settings.RENDER_SCALE, yfact=settings.RENDER_SCALE, origin=(0, 0))
        element = ET.fromstring(scaled.svg(0, fill_color or '#FFFFFF'))
        if element.tag != 'g':
            new_element = ET.Element('g')
            new_element.append(element)
            element = new_element

        paths = element.findall('polyline')
        if len(paths) == 0:
            paths = element.findall('path')

        for path in paths:
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

            if stroke_opacity is not None:
                path.set('stroke-opacity', str(stroke_opacity))

        return element

    def create_svg(self):
        width, height = self.get_dimensions()
        svg = ET.Element('svg', {
            'width': str(width),
            'height': str(height),
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
            'xmlns:xlink': 'http://www.w3.org/1999/xlink',
        })
        return svg

    def add_svg_content(self, svg):
        width, height = self.get_dimensions()
        contents = ET.Element('g', {
            'transform': 'scale(1 -1) translate(0 -%d)' % (height),
        })
        svg.append(contents)
        return contents

    def add_svg_image(self, svg, image):
        width, height = self.get_dimensions()
        contents = ET.Element('image', {
            'x': '0',
            'y': '0',
            'width': str(width),
            'height': str(height),
            'xlink:href': image
        })
        svg.append(contents)

    def render_base(self, png=True, show_accessibles=False):
        svg = self.create_svg()
        contents = self.add_svg_content(svg)

        if not self.level.intermediate:
            width, height = get_dimensions()
            holes = self.level.geometries.holes.buffer(0.1, join_style=JOIN_STYLE.mitre)
            contents.append(self.polygon_svg(box(0, 0, width, height).difference(holes),
                                             fill_color='#000000'))

        contents.append(self.polygon_svg(self.level.geometries.buildings_with_holes,
                                         fill_color=('#EBEBEB' if self.level.intermediate else '#D5D5D5')))

        contents.append(self.polygon_svg(self.level.geometries.outsides_with_holes,
                                         fill_color='#DCE6DC'))

        contents.append(self.polygon_svg(self.level.geometries.stair_shadows,
                                         stroke_color='#000000',
                                         stroke_width=0.1,
                                         stroke_opacity=0.1))

        contents.append(self.polygon_svg(self.level.geometries.stairs,
                                         stroke_color='#000000',
                                         stroke_width=0.06,
                                         stroke_opacity=0.2))

        contents.append(self.polygon_svg(self.level.geometries.walls_shadow,
                                         fill_color='#000000',
                                         fill_opacity=0.06))

        if show_accessibles:
            main_geometry = self.level.geometries.accessible.buffer(-0.6, join_style=JOIN_STYLE.mitre)
            clear_geometry = self.level.geometries.accessible.buffer(-0.3, join_style=JOIN_STYLE.mitre)
            missing_geometry = clear_geometry.difference(main_geometry.buffer(0.31, join_style=JOIN_STYLE.mitre))

            contents.append(self.polygon_svg(clear_geometry,
                                             fill_color='#FFFF00',
                                             fill_opacity=0.5))

            contents.append(self.polygon_svg(main_geometry,
                                             fill_color='#009900',
                                             fill_opacity=0.5))

            contents.append(self.polygon_svg(missing_geometry,
                                             fill_color='#FF9900',
                                             fill_opacity=0.5))

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

        filename = get_render_path('level-%s.base.svg' % self.level.name)
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = get_render_path('level-%s.base.png' % self.level.name)
            subprocess.call(['rsvg-convert', filename, '-o', png_filename])

    def render_simple(self, png=True):
        svg = self.create_svg()

        dark_lower = []
        lower = []
        for level in self.level.lower():
            lower.append(level)
            if not level.intermediate:
                dark_lower.extend(lower)
                lower = []
        lower.append(self.level)

        width, height = get_dimensions()
        contents = self.add_svg_content(svg)
        contents.append(self.polygon_svg(box(0, 0, width, height),
                                         fill_color='#000000'))

        for level in dark_lower:
            self.add_svg_image(svg, 'file://'+get_render_path('level-%s.base.png' % level.name))

        contents = self.add_svg_content(svg)
        contents.append(self.polygon_svg(box(0, 0, width, height),
                                         fill_color='#000000',
                                         fill_opacity=0.1))

        for level in lower:
            self.add_svg_image(svg, 'file://'+get_render_path('level-%s.base.png' % level.name))

        filename = get_render_path('level-%s.simple.svg' % self.level.name)
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = get_render_path('level-%s.simple.png' % self.level.name)
            subprocess.call(['rsvg-convert', filename, '-o', png_filename])

    def render_full(self, png=True):
        svg = self.create_svg()

        self.add_svg_image(svg, 'file://' + get_render_path('level-%s.simple.png' % self.level.name))

        higher = []
        for level in self.level.higher():
            if not level.intermediate:
                break
            higher.append(level)

        contents = self.add_svg_content(svg)
        for level in higher:
            contents.append(self.polygon_svg(level.geometries.intermediate_shadows,
                                             fill_color='#000000',
                                             fill_opacity=0.05))

        for level in higher:
            self.add_svg_image(svg, 'file://'+get_render_path('level-%s.base.png' % level.name))

        filename = get_render_path('level-%s.full.svg' % self.level.name)
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = get_render_path('level-%s.full.png' % self.level.name)
            subprocess.call(['rsvg-convert', filename, '-o', png_filename])
