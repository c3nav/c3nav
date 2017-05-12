import xml.etree.ElementTree as ET
from abc import ABC

from shapely.affinity import scale

from c3nav.mapdata.utils.misc import get_render_dimensions


class SVGGroup:
    def __init__(self, width: int, height: int, scale: float=1):
        self.width = width
        self.height = height
        self.scale = scale
        self.g = ET.Element('g', {
            'transform': 'scale(1 -1) translate(0 -%d)' % (self.height),
        })

    def get_xml(self):
        return self.g

    def add_group(self):
        group = SVGGroup(self.width, self.height, self.scale)
        self.g.append(group)
        return group


class SVGImage(SVGGroup):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def get_xml(self):
        root = ET.Element('svg', {
            'width': str(self.width),
            'height': str(self.height),
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
            'xmlns:xlink': 'http://www.w3.org/1999/xlink',
        })
        root.append(self.g)
        return root

    def add_geometry(self, geometry, fill_color=None, fill_opacity=None,
                    stroke_width=0.0, stroke_color=None, stroke_opacity=None):
        scaled = scale(geometry, xfact=self.scale, yfact=self.scale, origin=(0, 0))
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
            path.set('stroke-width', str(stroke_width * self.scale))

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

        self.g.append(element)
        return element


class MapRenderer(ABC):
    def __init__(self):
        pass

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
