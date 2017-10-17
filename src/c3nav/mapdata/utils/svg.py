import io
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from itertools import chain

from django.conf import settings
from django.core.checks import Error, register
from PIL import Image
from shapely.affinity import scale, translate
from shapely.ops import unary_union


@register()
def check_svg_renderer(app_configs, **kwargs):
    errors = []
    if settings.SVG_RENDERER not in ('rsvg', 'inkscape'):
        errors.append(
            Error(
                'Invalid SVG renderer: '+settings.SVG_RENDERER,
                obj='settings.SVG_RENDERER',
                id='c3nav.mapdata.E001',
            )
        )
    return errors


class SVGImage:
    def __init__(self, bounds, scale: float=1, buffer=0):
        (self.bottom, self.left), (self.top, self.right) = bounds
        self.width = self.right-self.left
        self.height = self.top-self.bottom
        self.scale = scale
        self.buffer_px = int(math.ceil(buffer*self.scale))
        self.g = ET.Element('g', {})
        self.defs = ET.Element('defs')
        self.def_i = 0
        self.altitudes = {}
        self.last_altitude = None
        self.blurs = set()

    def get_element(self, buffer=False):
        width_px = self._trim_decimals(str(self.width*self.scale + (self.buffer_px*2 if buffer else 0)))
        height_px = self._trim_decimals(str(self.height*self.scale + (self.buffer_px*2 if buffer else 0)))
        offset_px = self._trim_decimals(str(-self.buffer_px)) if buffer else '0'
        root = ET.Element('svg', {
            'width': width_px,
            'height': height_px,
            'xmlns:svg': 'http://www.w3.org/2000/svg',
            'xmlns': 'http://www.w3.org/2000/svg',
            'xmlns:xlink': 'http://www.w3.org/1999/xlink',
        })
        if buffer:
            root.attrib['viewBox'] = ' '.join((offset_px, offset_px, width_px, height_px))
        root.append(self.defs)
        root.append(self.g)
        return root

    def get_xml(self, buffer=False):
        return ET.tostring(self.get_element(buffer=buffer)).decode()

    def get_png(self):
        crop = False
        if settings.SVG_RENDERER == 'rsvg':
            crop = True
            p = subprocess.run(('rsvg-convert', '--format', 'png'),
                               input=self.get_xml(buffer=True).encode(), stdout=subprocess.PIPE, check=True)
            png = p.stdout
        elif settings.SVG_RENDERER == 'inkscape':
            p = subprocess.run(('inkscape', '-z', '-e', '/dev/stderr', '/dev/stdin'), input=self.get_xml().encode(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            png = p.stderr
            png = png[png.index(b'\x89PNG'):]
            print(png)
        else:
            raise ValueError

        if crop:
            f = io.BytesIO(png)
            img = Image.open(f)
            img = img.crop((self.buffer_px, self.buffer_px,
                            self.buffer_px+int(self.width*self.scale),
                            self.buffer_px+int(self.height*self.scale)))
            f = io.BytesIO()
            img.save(f, 'PNG')
            f.seek(0)
            png = f.read()

        return png

    def new_defid(self):
        defid = 's'+str(self.def_i)
        self.def_i += 1
        return defid

    def _trim_decimals(self, data):
        return re.sub(r'([0-9]+)\.0', r'\1', re.sub(r'([0-9]+\.[0-9])[0-9]+', r'\1', data))

    def _create_geometry(self, geometry):
        geometry = translate(geometry, xoff=0-self.left, yoff=0-self.bottom)
        geometry = scale(geometry, xfact=1, yfact=-1, origin=(self.width / 2, self.height / 2))
        geometry = scale(geometry, xfact=self.scale, yfact=self.scale, origin=(0, 0))
        element = ET.fromstring(self._trim_decimals(geometry.svg(0, '#FFFFFF')))
        if element.tag != 'g':
            new_element = ET.Element('g')
            new_element.append(element)
            element = new_element

        for elem in chain(element.findall('polyline'), element.findall('path')):
            elem.attrib.pop('opacity', None)
            elem.attrib.pop('fill', None)
            elem.attrib.pop('fill-rule', None)
            elem.attrib.pop('stroke', None)
            elem.attrib.pop('stroke-width', None)
        return element

    def register_geometry(self, geometry, defid=None, as_clip_path=False, comment=None):
        if defid is None:
            defid = self.new_defid()

        element = self._create_geometry(geometry)

        if as_clip_path:
            element.tag = 'clipPath'
        element.set('id', defid)
        self.defs.append(element)
        return defid

    def get_blur(self, elevation):
        blur_id = 'blur'+str(elevation*100)
        if elevation not in self.blurs:
            blur_filter = ET.Element('filter', {'id': blur_id,
                                                'width': '200%',
                                                'height': '200%',
                                                'x': '-50%',
                                                'y': '-50%'})
            blur_filter.append(ET.Element('feGaussianBlur',
                                          {'in': 'SourceGraphic',
                                           'stdDeviation': str(elevation*self.scale)}))
            self.defs.append(blur_filter)
            self.blurs.add(elevation)
        return blur_id

    def add_clip_path(self, *geometries, inverted=False, subtract=False, defid=None):
        if defid is None:
            defid = self.new_defid()

        clippath = ET.Element('clipPath', {'id': defid})
        clippath.append(ET.Element('use', {'xlink:href': '#' + geometries[0]}))
        self.defs.append(clippath)
        return defid

    def clip_altitudes(self, new_geometry, new_altitude=None):
        for altitude, geometry in tuple(self.altitudes.items()):
            if altitude != new_altitude:
                self.altitudes[altitude] = geometry.difference(new_geometry)
                if self.altitudes[altitude].is_empty:
                    self.altitudes.pop(altitude)
        if new_altitude is not None:
            if self.last_altitude is not None and self.last_altitude > new_altitude:
                raise ValueError('Altitudes have to be ascending.')
            self.last_altitude = new_altitude
            if new_altitude in self.altitudes:
                self.altitudes[new_altitude] = unary_union([self.altitudes[new_altitude], new_geometry])
            else:
                self.altitudes[new_altitude] = new_geometry

    def add_geometry(self, geometry=None, fill_color=None, fill_opacity=None, opacity=None, filter=None,
                     stroke_px=0.0, stroke_width=0.0, stroke_color=None, stroke_opacity=None, stroke_linejoin=None,
                     clip_path=None, altitude=None, elevation=None):
        if geometry is not None:
            if not geometry:
                return
            if isinstance(geometry, str):
                element = ET.Element('use', {'xlink:href': '#'+geometry})
            else:
                element = self._create_geometry(geometry)

            if altitude is not None or elevation is not None:
                blur_radius = float(1 if elevation is None else elevation)

                buffered_geometry = translate(geometry.buffer(blur_radius/20),
                                              xoff=blur_radius/40, yoff=-blur_radius/40)
                shadow_element = self._create_geometry(buffered_geometry)
                shadow_element.set('fill', '#000000')
                shadow_element.set('fill-opacity', '0.14')
                shadow_element.set('filter', 'url(#'+self.get_blur(blur_radius/15)+')')
                self.g.append(shadow_element)

                self.clip_altitudes(geometry, altitude)

        else:
            element = ET.Element('rect', {'width': '100%', 'height': '100%'})
        element.set('fill', fill_color or 'none')
        if fill_opacity:
            element.set('fill-opacity', str(fill_opacity)[:4])
        if stroke_px:
            element.set('stroke-width', self._trim_decimals(str(stroke_px)))
        elif stroke_width:
            element.set('stroke-width', self._trim_decimals(str(stroke_width * self.scale)))
        if stroke_color:
            element.set('stroke', stroke_color)
        if stroke_opacity:
            element.set('stroke-opacity', str(stroke_opacity)[:4])
        if stroke_linejoin:
            element.set('stroke-linejoin', stroke_linejoin)
        if opacity:
            element.set('opacity', str(opacity)[:4])
        if filter:
            element.set('filter', 'url(#'+filter+')')
        if clip_path:
            element.set('clip-path', 'url(#'+clip_path+')')

        self.g.append(element)
        return element
