import io
import math
import re
import subprocess
import xml.etree.ElementTree as ET
from itertools import chain

from django.conf import settings
from django.core.checks import Error, register
from PIL import Image
from shapely.affinity import affine_transform, translate
from shapely.ops import unary_union

# import gobject-inspect, cairo and rsvg if the native rsvg SVG_RENDERER should be used
if settings.SVG_RENDERER == 'rsvg':
    import pgi
    import cairocffi
    pgi.require_version('Rsvg', '2.0')
    from pgi.repository import Rsvg


@register()
def check_svg_renderer(app_configs, **kwargs):
    errors = []
    if settings.SVG_RENDERER not in ('rsvg', 'rsvg-convert', 'inkscape'):
        errors.append(
            Error(
                'Invalid SVG renderer: '+settings.SVG_RENDERER,
                obj='settings.SVG_RENDERER',
                id='c3nav.mapdata.E001',
            )
        )
    return errors


class SVGImage:
    # draw an svg image. supports pseudo-3D shadow-rendering
    def __init__(self, bounds, scale: float=1, buffer=0):
        # get image dimensions.
        # note that these values describe the „viewport“ of the image, not its dimensions in pixels.
        (self.bottom, self.left), (self.top, self.right) = bounds
        self.width = self.right-self.left
        self.height = self.top-self.bottom
        self.scale = scale

        # how many pixels around the image should be added and later cropped (otherwise rsvg does not blur correctly)
        self.buffer_px = int(math.ceil(buffer*self.scale))

        # create base elements and counter for dynamic definition ids
        self.g = ET.Element('g', {})
        self.defs = ET.Element('defs')
        self.def_i = 0

        # keep track which area of the image has which altitude currently
        self.altitudes = {}
        self.last_altitude = None

        # keep track of created blur filters to avoid duplicates
        self.blurs = set()

    def get_dimensions_px(self, buffer):
        # get dimensions of the image in pixels, with or without buffer
        width_px = self.width * self.scale + (self.buffer_px * 2 if buffer else 0)
        height_px = self.height * self.scale + (self.buffer_px * 2 if buffer else 0)
        return height_px, width_px

    def get_element(self, buffer=False):
        # get the root <svg> element as an ElementTree element, with or without buffer
        height_px, width_px = (self._trim_decimals(str(i)) for i in self.get_dimensions_px(buffer))
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
        if len(self.defs):
            root.append(self.defs)
        if len(self.g):
            root.append(self.g)
        return root

    def get_xml(self, buffer=False):
        # get xml of the svg as a string
        return ET.tostring(self.get_element(buffer=buffer)).decode()

    def get_png(self, f=None):
        # render the image to png. returns bytes if f is None, otherwise it calls f.write()
        if settings.SVG_RENDERER == 'rsvg':
            # create buffered surfaces
            buffered_surface = cairocffi.SVGSurface(None, *(int(i) for i in self.get_dimensions_px(buffer=True)))
            buffered_context = cairocffi.Context(buffered_surface)

            # draw svg with rsvg
            handle = Rsvg.Handle()
            svg = handle.new_from_data(self.get_xml(buffer=True).encode())
            svg.render_cairo(buffered_context)

            # crop resulting immage
            surface = buffered_surface.create_similar(buffered_surface.get_content(),
                                                      *(int(i) for i in self.get_dimensions_px(buffer=False)))
            context = cairocffi.Context(surface)
            context.set_source_surface(buffered_surface, -self.buffer_px, -self.buffer_px)
            context.paint()
            if f is None:
                return surface.write_to_png()
            f.write(surface.write_to_png())

        elif settings.SVG_RENDERER == 'rsvg-convert':
            p = subprocess.run(('rsvg-convert', '--format', 'png'),
                               input=self.get_xml(buffer=True).encode(), stdout=subprocess.PIPE, check=True)
            png = io.BytesIO(p.stdout)
            img = Image.open(png)
            img = img.crop((self.buffer_px, self.buffer_px,
                            self.buffer_px + int(self.width * self.scale),
                            self.buffer_px + int(self.height * self.scale)))
            if f is None:
                f = io.BytesIO()
                img.save(f, 'PNG')
                f.seek(0)
                return f.read()
            img.save(f, 'PNG')

        elif settings.SVG_RENDERER == 'inkscape':
            p = subprocess.run(('inkscape', '-z', '-e', '/dev/stderr', '/dev/stdin'), input=self.get_xml().encode(),
                               stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True)
            png = p.stderr[p.stderr.index(b'\x89PNG'):]
            if f is None:
                return png
            f.write(png)

    def new_defid(self):
        defid = 's'+str(self.def_i)
        self.def_i += 1
        return defid

    def _trim_decimals(self, data):
        # remove trailing zeros from a decimal
        return re.sub(r'([0-9]+)((\.[1-9])[0-9]+|\.[0-9]+)?', r'\1\3', data)

    def _create_geometry(self, geometry):
        # convert a shapely geometry into an svg xml element

        # scale and move the object into position, this is equivalent to:
        # geometry = translate(geometry, xoff=0-self.left, yoff=0-self.bottom)
        # geometry = scale(geometry, xfact=1, yfact=-1, origin=(self.width / 2, self.height / 2))
        # geometry = scale(geometry, xfact=self.scale, yfact=self.scale, origin=(0, 0))
        geometry = affine_transform(geometry, (self.scale, 0.0,
                                               0.0, -self.scale,
                                               -(self.left)*self.scale, (self.top)*self.scale))
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

    def add_shadow(self, geometry, elevation, clip_path=None):
        # add a shadow for the given geometry with the given elevation and, optionally, a clip path
        elevation = min(elevation, 2)
        blur_radius = elevation / 3 * 0.25

        shadow_geom = translate(geometry.buffer(blur_radius),
                                xoff=(elevation / 3 * 0.12), yoff=-(elevation / 3 * 0.12))

        if clip_path is not None:
            if shadow_geom.distance(clip_path) >= blur_radius:
                return

        blur_id = 'blur'+str(int(elevation*100))
        if elevation not in self.blurs:
            blur_filter = ET.Element('filter', {'id': blur_id,
                                                'width': '200%',
                                                'height': '200%',
                                                'x': '-50%',
                                                'y': '-50%'})
            blur_filter.append(ET.Element('feGaussianBlur',
                                          {'stdDeviation': str(blur_radius * self.scale)}))

            self.defs.append(blur_filter)
            self.blurs.add(elevation)

        shadow = self._create_geometry(shadow_geom)
        shadow.set('filter', 'url(#'+blur_id+')')
        shadow.set('fill', '#000')
        shadow.set('fill-opacity', '0.2')
        if clip_path:
            shadow_clip = self.register_geometry(clip_path, as_clip_path=True)
            shadow.set('clip-path', 'url(#'+shadow_clip+')')
        self.g.append(shadow)

    def clip_altitudes(self, new_geometry, new_altitude=None):
        # registrer new geometry with specific (or no) altitude
        # a geometry with no altitude will reset the altitude information of its area as if nothing was ever there
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
        # draw a shapely geometry with a given style
        # if altitude is set, the geometry will get a calculated shadow relative to the other geometries
        # if elevation is set, the geometry will get a shadow with exactly this elevation
        if geometry is not None:
            if not geometry:
                return

            if altitude is not None or elevation is not None:
                if elevation is not None:
                    elevation = float(1 if elevation is None else elevation)
                    if elevation:
                        self.add_shadow(geometry, elevation)
                else:
                    for other_altitude, other_geom in self.altitudes.items():
                        self.add_shadow(geometry, altitude-other_altitude, clip_path=other_geom)

                self.clip_altitudes(geometry, altitude)

            element = self._create_geometry(geometry)

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
