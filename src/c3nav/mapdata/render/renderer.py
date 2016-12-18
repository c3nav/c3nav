import subprocess
import xml.etree.ElementTree as ET

from django.conf import settings
from shapely.affinity import scale
from shapely.geometry import JOIN_STYLE, box

from c3nav.mapdata.utils.misc import get_dimensions, get_render_dimensions, get_render_path


class LevelRenderer():
    def __init__(self, level, only_public):
        self.level = level
        self.only_public = only_public

        self.geometries = self.get_geometries(level)

    def get_geometries(self, level):
        return level.public_geometries if self.only_public else level.geometries

    def get_filename(self, mode, filetype, level=None):
        return get_render_path(filetype, self.level.name if level is None else level, mode, self.only_public)

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
        width, height = get_render_dimensions()
        svg = ET.Element('svg', {
            'width': str(width),
            'height': str(height),
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
            'xmlns:xlink': 'http://www.w3.org/1999/xlink',
        })
        return svg

    def add_svg_content(self, svg):
        width, height = get_render_dimensions()
        contents = ET.Element('g', {
            'transform': 'scale(1 -1) translate(0 -%d)' % (height),
        })
        svg.append(contents)
        return contents

    def add_svg_image(self, svg, image):
        width, height = get_render_dimensions()
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

        MITRE = JOIN_STYLE.mitre
        if not self.level.intermediate:
            width, height = get_dimensions()
            holes = self.geometries.holes.buffer(0.1, join_style=MITRE)
            contents.append(self.polygon_svg(box(0, 0, width, height).difference(holes),
                                             fill_color='#000000'))

        contents.append(self.polygon_svg(self.geometries.buildings_with_holes,
                                         fill_color='#D5D5D5'))

        contents.append(self.polygon_svg(self.geometries.outsides_with_holes,
                                         fill_color='#DCE6DC'))

        contents.append(self.polygon_svg(self.geometries.stair_areas,
                                         fill_color='#000000',
                                         fill_opacity=0.03))

        contents.append(self.polygon_svg(self.geometries.stairs,
                                         stroke_color='#000000',
                                         stroke_width=0.06,
                                         stroke_opacity=0.2))

        contents.append(self.polygon_svg(self.geometries.escalators,
                                         fill_color='#B3B3B3'))

        contents.append(self.polygon_svg(self.geometries.walls_shadow,
                                         fill_color='#000000',
                                         fill_opacity=0.06))

        if show_accessibles:
            narrowed_geometry = self.geometries.accessible.buffer(-0.6, join_style=MITRE)
            clear_geometry = self.geometries.accessible.buffer(-0.3, join_style=JOIN_STYLE.mitre)
            wide_geometry = narrowed_geometry.buffer(0.31, join_style=MITRE).intersection(clear_geometry)
            missing_geometry = clear_geometry.difference(wide_geometry.buffer(0.01, join_style=MITRE))

            contents.append(self.polygon_svg(clear_geometry,
                                             fill_color='#FFFF00',
                                             fill_opacity=0.5))

            contents.append(self.polygon_svg(narrowed_geometry,
                                             fill_color='#009900',
                                             fill_opacity=0.5))

            contents.append(self.polygon_svg(missing_geometry,
                                             fill_color='#FF9900',
                                             fill_opacity=0.5))

        contents.append(self.polygon_svg(self.geometries.elevatorlevels,
                                         fill_color='#9EF8FB'))

        contents.append(self.polygon_svg(self.geometries.doors,
                                         fill_color='#FFFFFF',
                                         stroke_color='#3c3c3c',
                                         stroke_width=0.05))

        contents.append(self.polygon_svg(self.geometries.uncropped_obstacles,
                                         fill_color='#A6A6A6',
                                         stroke_color='#919191',
                                         stroke_width=0.05))

        contents.append(self.polygon_svg(self.geometries.cropped_obstacles.buffer(-0.06, join_style=MITRE),
                                         fill_color='#A6A6A6',
                                         stroke_color='#919191',
                                         stroke_width=0.05))

        wider_escalators = self.geometries.escalators.buffer(0.3, join_style=MITRE)
        contents.append(self.polygon_svg(wider_escalators.intersection(self.geometries.uncropped_obstacles),
                                         fill_color='#666666',
                                         stroke_color='#666666',
                                         stroke_width=0.05))

        contents.append(self.polygon_svg(self.geometries.walls,
                                         fill_color='#949494',
                                         stroke_color='#3c3c3c',
                                         stroke_width=0.05))

        filename = self.get_filename('base', 'svg')
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = self.get_filename('base', 'png')
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
            self.add_svg_image(svg, 'file://'+self.get_filename('base', 'png', level=level))

        contents = self.add_svg_content(svg)
        contents.append(self.polygon_svg(box(0, 0, width, height),
                                         fill_color='#000000',
                                         fill_opacity=0.1))

        for level in lower:
            self.add_svg_image(svg, 'file://'+self.get_filename('base', 'png', level=level))

        filename = self.get_filename('simple', 'svg')
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = self.get_filename('simple', 'png')
            subprocess.call(['rsvg-convert', filename, '-o', png_filename])

    def render_full(self, png=True):
        svg = self.create_svg()

        self.add_svg_image(svg, 'file://' + self.get_filename('simple', 'png'))

        higher = []
        for level in self.level.higher():
            if not level.intermediate:
                break
            higher.append(level)

        contents = self.add_svg_content(svg)
        for level in higher:
            contents.append(self.polygon_svg(self.get_geometries(level).intermediate_shadows,
                                             fill_color='#000000',
                                             fill_opacity=0.07))

        for level in higher:
            self.add_svg_image(svg, 'file://'+self.get_filename('base', 'png', level=level))

        filename = self.get_filename('full', 'svg')
        with open(filename, 'w') as f:
            f.write(ET.tostring(svg).decode())

        if png:
            png_filename = self.get_filename('full', 'png')
            subprocess.call(['rsvg-convert', filename, '-o', png_filename])
