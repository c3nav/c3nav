import io
import re
import subprocess
import zlib
from itertools import chain
from typing import Optional

import numpy as np
from django.conf import settings
from django.core import checks
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon
# import gobject-inspect, cairo and rsvg if the native rsvg SVG_RENDERER should be used
from shapely.ops import unary_union

from c3nav.mapdata.render.engines.base import FillAttribs, RenderEngine, StrokeAttribs
from c3nav.mapdata.utils.geometry.inspect import unwrap_geom

if settings.SVG_RENDERER == 'rsvg':
    try:
        import pgi
        pgi.require_version('Rsvg', '2.0')
        from pgi.repository import Rsvg
        import cairocffi as cairo
    except ImportError:
        import gi
        gi.require_version('Rsvg', '2.0')
        import cairo
        from gi.repository import Rsvg
elif settings.SVG_RENDERER == 'rsvg-convert':
    from PIL import Image


def unwrap_hybrid_geom(geom):
    from c3nav.mapdata.render.geometry import HybridGeometry
    if isinstance(geom, HybridGeometry):
        geom = geom.geom
    return unwrap_geom(geom)


@checks.register()
def check_svg_renderer(app_configs, **kwargs):
    errors = []
    if settings.SVG_RENDERER not in ('rsvg', 'rsvg-convert', 'inkscape'):
        errors.append(
            checks.Error(
                'Invalid SVG renderer: '+settings.SVG_RENDERER,
                obj='settings.SVG_RENDERER',
                id='c3nav.mapdata.E002',
            )
        )
    return errors


class SVGEngine(RenderEngine):
    filetype = 'png'

    # draw an svg image. supports pseudo-3D shadow-rendering
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # create base elements and counter for clip path ids
        self.g = ''
        self.defs = ''
        self.clip_path_i = 0

        # for fast numpy operations
        self.np_scale = np.array((self.scale, -self.scale))
        self.np_offset = np.array((-self.minx * self.scale, self.maxy * self.scale))

        # keep track of created blur filters to avoid duplicates
        self.blurs = set()

        # keep track which area of the image has which altitude currently
        self.altitudes = {}
        self.last_altitude = None

        self._create_geometry_cache = {}

    def get_xml(self, buffer=False):
        # get the root <svg> element as an ElementTree element, with or without buffer
        if buffer:
            width_px = self._trim_decimals(str(self.buffered_width))
            height_px = self._trim_decimals(str(self.buffered_height))
            offset_px = self._trim_decimals(str(-self.buffer))
            attribs = ' viewBox="' + ' '.join((offset_px, offset_px, width_px, height_px)) + '"' if buffer else ''
        else:
            width_px = self._trim_decimals(str(self.width))
            height_px = self._trim_decimals(str(self.height))
            attribs = ''

        result = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                  'width="'+width_px+'" height="'+height_px+'"'+attribs+'>')
        if self.defs:
            result += '<defs>'+self.defs+'</defs>'
        if self.g:
            result += '<g>'+self.g+'</g>'
        result += '</svg>'
        return result

    def render(self, filename=None):
        # render the image to png. returns bytes if f is None, otherwise it calls f.write()

        if self.width == 256 and self.height == 256 and not self.g:
            # create empty tile png with minimal size, indexed color palette with only one entry
            plte = b'PLTE' + bytearray(tuple(int(i*255) for i in self.background_rgb))
            return (b'\x89PNG\r\n\x1a\n' +
                    b'\x00\x00\x00\rIHDR\x00\x00\x01\x00\x00\x00\x01\x00\x01\x03\x00\x00\x00f\xbc:%\x00\x00\x00\x03' +
                    plte + zlib.crc32(plte).to_bytes(4, byteorder='big') +
                    b'\x00\x00\x00\x1fIDATh\xde\xed\xc1\x01\r\x00\x00\x00\xc2\xa0\xf7Om\x0e7\xa0\x00\x00\x00\x00\x00' +
                    b'\x00\x00\x00\xbe\r!\x00\x00\x01\x7f\x19\x9c\xa7\x00\x00\x00\x00IEND\xaeB`\x82')

        if settings.SVG_RENDERER == 'rsvg':
            # create buffered surfaces
            buffered_surface = cairo.SVGSurface(None, self.buffered_width, self.buffered_height)
            buffered_context = cairo.Context(buffered_surface)

            # draw svg with rsvg
            handle = Rsvg.Handle()
            svg = handle.new_from_data(self.get_xml(buffer=True).encode())
            svg.render_cairo(buffered_context)

            # create cropped image
            surface = buffered_surface.create_similar(cairo.CONTENT_COLOR_ALPHA, self.width, self.height)
            context = cairo.Context(surface)

            # set background color
            context.set_source(cairo.SolidPattern(*self.background_rgb))
            context.paint()

            # paste buffered immage with offset
            context.set_source_surface(buffered_surface, -self.buffer, -self.buffer)
            context.paint()

            f = io.BytesIO()
            surface.write_to_png(f)
            f.seek(0)
            return f.read()

        elif settings.SVG_RENDERER == 'rsvg-convert':
            p = subprocess.run(('rsvg-convert', '-b', self.background, '--format', 'png'),
                               input=self.get_xml(buffer=True).encode(), stdout=subprocess.PIPE, check=True)
            png = io.BytesIO(p.stdout)
            img = Image.open(png)
            img = img.crop((self.buffer, self.buffer,
                            self.buffer + self.width,
                            self.buffer + self.height))

            f = io.BytesIO()
            img.save(f, 'PNG')
            f.seek(0)
            return f.read()

        elif settings.SVG_RENDERER == 'inkscape':
            p = subprocess.run(('inkscape', '-z', '-b', self.background, '-e', '/dev/stderr', '/dev/stdin'),
                               input=self.get_xml().encode(), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                               check=True)
            png = p.stderr[p.stderr.index(b'\x89PNG'):]
            return png

    def _trim_decimals(self, data):
        # remove trailing zeros from a decimal – yes this is slow, but it greatly speeds up cairo rendering
        return re.sub(r'([0-9]+)((\.[1-9])[0-9]+|\.[0-9]+)?', r'\1\2', data)

    def _geometry_to_svg(self, geom):
        # scale and move geometry and create svg code for it
        if isinstance(geom, Polygon):
            return ('<path d="' +
                    ' '.join((('M %.1f %.1f L'+(' %.1f %.1f'*(len(ring.coords)-1))+' z') %
                              tuple((np.array(ring.coords)*self.np_scale+self.np_offset).flatten()))
                             for ring in chain((geom.exterior,), geom.interiors))
                    + '"/>').replace('.0 ', ' ')
        if isinstance(geom, LineString):
            return (('<path d="M %.1f %.1f L'+(' %.1f %.1f'*(len(geom.coords)-1))+'"/>') %
                    tuple((np.array(geom.coords)*self.np_scale+self.np_offset).flatten())).replace('.0 ', ' ')
        try:
            geoms = geom.geoms
        except AttributeError:
            return ''
        return ''.join(self._geometry_to_svg(g) for g in geoms)

    def _create_geometry(self, geometry, attribs='', tag='g', cache_key=None):
        # convert a shapely geometry into an svg xml element
        result = None
        if cache_key is not None:
            result = self._create_geometry_cache.get(cache_key, None)
        if result is None:
            result = self._geometry_to_svg(geometry)
            if cache_key is not None:
                self._create_geometry_cache[cache_key] = result
        return '<'+tag+attribs+'>'+result+'</'+tag+'>'

    def register_clip_path(self, geometry):
        defid = 'clip'+str(self.clip_path_i)
        self.defs += self._create_geometry(geometry, ' id="'+defid+'"', tag='clipPath')
        self.clip_path_i += 1
        return defid

    def add_shadow(self, geometry, elevation, color, clip_path=None):
        # add a shadow for the given geometry with the given elevation and, optionally, a clip path
        elevation = float(min(elevation, 2))
        blur_radius = elevation / 3 * 0.25

        shadow_geom = translate(geometry.buffer(blur_radius),
                                xoff=(elevation / 3 * 0.12), yoff=-(elevation / 3 * 0.12))

        if clip_path is not None:
            if shadow_geom.distance(clip_path) >= blur_radius:
                return

        blur_id = 'blur'+str(int(elevation*100))
        if elevation not in self.blurs:
            self.defs += ('<filter id="'+blur_id+'" width="200%" height="200%" x="-50%" y="-50%">'
                          '<feGaussianBlur stdDeviation="'+str(blur_radius * self.scale)+'"/>'
                          '</filter>')
            self.blurs.add(elevation)

        attribs = ' filter="url(#'+blur_id+')" fill="'+(color or '#000')+'" fill-opacity="0.2"'
        if clip_path:
            attribs += ' clip-path="url(#'+self.register_clip_path(clip_path)+')"'
        shadow = self._create_geometry(shadow_geom, attribs)
        self.g += shadow

    def clip_altitudes(self, new_geometry, new_altitude=None):
        # register new geometry with an altitude
        # a geometry with no altitude will reset the altitude information of its area as if nothing was ever there
        if self.last_altitude is not None and self.last_altitude > new_altitude:
            raise ValueError('Altitudes have to be ascending.')

        if new_altitude in self.altitudes:
            self.altitudes[new_altitude] = unary_union([self.altitudes[new_altitude], new_geometry])
        else:
            self.altitudes[new_altitude] = new_geometry

    def darken(self, area, much=False):
        if area:
            self.add_geometry(geometry=area, fill=FillAttribs('#000000', 0.4 if much else 0.1), category='darken')

    def _add_geometry(self, geometry, fill: Optional[FillAttribs], stroke: Optional[StrokeAttribs],
                      altitude=None, height=None, shadow_color=None, shape_cache_key=None, **kwargs):
        geometry = self.buffered_bbox.intersection(unwrap_hybrid_geom(geometry))

        if geometry.is_empty:
            return

        if fill:
            attribs = ' fill="'+(fill.color)+'"'
            if fill.opacity:
                attribs += ' fill-opacity="'+str(fill.opacity)[:4]+'"'
        else:
            attribs = ' fill="none"'

        if altitude is not None and stroke is None:
            stroke = StrokeAttribs('rgba(0, 0, 0, 0.15)', 0.05, min_px=0.2)

        if stroke:
            width = stroke.width*self.scale
            if stroke.min_px:
                width = max(width, stroke.min_px)
            attribs += ' stroke-width="' + self._trim_decimals(str(width)) + '" stroke="' + stroke.color + '"'
            if stroke.opacity:
                attribs += ' stroke-opacity="'+str(stroke.opacity)[:4]+'"'

        if geometry is not None:

            if False:
                # old shadow rendering. currently needs too much resources
                if altitude is not None or height is not None:
                    if height is not None:
                        if height:
                            self.add_shadow(geometry, height, '#000')
                    else:
                        for other_altitude, other_geom in self.altitudes.items():
                            self.add_shadow(geometry, altitude-other_altitude, clip_path=other_geom)

                    self.clip_altitudes(geometry, altitude, '#000')
            else:
                if height is not None:
                    self.add_shadow(geometry, height, shadow_color)

            element = self._create_geometry(geometry, attribs, cache_key=shape_cache_key)

        else:
            element = '<rect width="100%" height="100%"'+attribs+'>'

        self.g += element
