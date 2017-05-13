import re
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
            'transform': 'scale(1 -1) translate(0 -%d)' % (self.height*scale),
        })

    def get_element(self):
        return self.g

    def get_xml(self):
        return ET.tostring(self.get_element()).decode()

    def add_group(self):
        group = SVGGroup(self.width, self.height, self.scale)
        self.g.append(group)
        return group


class SVGImage(SVGGroup):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.defs = ET.Element('defs')
        self.def_i = 0

        # blur_filter = ET.Element('filter', {'id': 'wallblur'})
        # blur_filter.append(ET.Element('feGaussianBlur', {'in': 'SourceGraphic', 'stdDeviation': str(5*self.scale)}))
        # self.defs.append(blur_filter)

    def get_element(self):
        root = ET.Element('svg', {
            'width': str(self.width*self.scale),
            'height': str(self.height*self.scale),
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
            'xmlns:xlink': 'http://www.w3.org/1999/xlink',
        })
        root.append(self.defs)
        root.append(self.g)
        return root

    def new_defid(self):
        defid = 's'+str(self.def_i)
        self.def_i += 1
        return defid

    def add_geometry(self, geometry, defid=None, comment=None):
        if defid is None:
            defid = self.new_defid()

        scaled = scale(geometry, xfact=self.scale, yfact=self.scale, origin=(0, 0))
        re_string = re.sub(r'([0-9]+)\.0', r'\1', re.sub(r'([0-9]+\.[0-9])[0-9]+', r'\1', scaled.svg(0, '#FFFFFF')))
        element = ET.fromstring(re_string)
        if element.tag != 'g':
            new_element = ET.Element('g')
            new_element.append(element)
            element = new_element

        paths = element.findall('polyline')
        if len(paths) == 0:
            paths = element.findall('path')

        for path in paths:
            path.attrib.pop('opacity', None)
            path.attrib.pop('fill', None)
            path.attrib.pop('fill-rule', None)
            path.attrib.pop('stroke', None)
            path.attrib.pop('stroke-width', None)

        element.set('id', defid)
        self.defs.append(element)
        return defid

    def add_mask(self, *geometries, inverted=False, defid=None):
        if defid is None:
            defid = self.new_defid()

        mask = ET.Element('mask', {'id': defid})
        mask.append(ET.Element('rect', {'width': '100%', 'height': '100%', 'fill': 'white' if inverted else 'black'}))
        for geometry in geometries:
            mask.append(ET.Element('use', {'xlink:href': '#'+geometry, 'fill': 'black' if inverted else 'white'}))
        self.defs.append(mask)
        return defid

    def add_union(self, *geometries, wall_shadow=False, defid=None):
        if defid is None:
            defid = self.new_defid()

        element = ET.Element('g', {'id': defid})
        for geometry in geometries:
            newelem = ET.Element('use', {'xlink:href': '#'+geometry})
            if wall_shadow:
                newelem.set('filter', 'url(#wallshadow)')
            element.append(newelem)
        self.defs.append(element)
        return defid

    def add_intersection(self, geometry1, geometry2, defid=None):
        if defid is None:
            defid = self.new_defid()

        mask = ET.Element('mask', {'id': defid+'-mask'})
        mask.append(ET.Element('rect', {'width': '100%', 'height': '100%', 'fill': 'black'}))
        mask.append(ET.Element('use', {'xlink:href': '#'+geometry2, 'fill': 'white'}))
        self.defs.append(mask)

        element = ET.Element('g', {'id': defid, 'mask': 'url(#'+defid+'-mask)'})
        element.append(ET.Element('use', {'xlink:href': '#'+geometry1}))
        self.defs.append(element)
        return defid

    def add_difference(self, geometry1, geometry2, defid=None):
        if defid is None:
            defid = self.new_defid()

        mask = ET.Element('mask', {'id': defid+'-mask'})
        mask.append(ET.Element('rect', {'width': '100%', 'height': '100%', 'fill': 'white'}))
        mask.append(ET.Element('use', {'xlink:href': '#'+geometry2, 'fill': 'black'}))
        self.defs.append(mask)

        element = ET.Element('g', {'id': defid, 'mask': 'url(#'+defid+'-mask)'})
        element.append(ET.Element('use', {'xlink:href': '#' + geometry1}))
        self.defs.append(element)
        return defid

    def use_geometry(self, geometry, fill_color=None, fill_opacity=None, opacity=None, mask=None, filter=None,
                     stroke_width=0.0, stroke_color=None, stroke_opacity=None, stroke_linejoin=None):
        element = ET.Element('use', {'xlink:href': '#'+geometry})
        element.set('fill', fill_color or 'none')
        if fill_opacity:
            element.set('fill-opacity', str(fill_opacity))
        if stroke_width:
            element.set('stroke-width', str(stroke_width * self.scale))
        if stroke_color:
            element.set('stroke', stroke_color)
        if stroke_opacity:
            element.set('stroke-opacity', str(stroke_opacity))
        if stroke_linejoin:
            element.set('stroke-linejoin', str(stroke_linejoin))
        if opacity:
            element.set('opacity', str(opacity))
        if mask:
            element.set('mask', 'url(#'+mask+')')
        if filter:
            element.set('filter', 'url(#'+filter+')')

        self.g.append(element)
        return element
