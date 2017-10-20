import io
import math
import re
import subprocess
from itertools import chain

import numpy as np
from django.conf import settings
from django.core import checks
from PIL import Image
from shapely.affinity import translate
from shapely.geometry import LineString, Polygon
from shapely.ops import unary_union

# import gobject-inspect, cairo and rsvg if the native rsvg SVG_RENDERER should be used
if settings.SVG_RENDERER == 'rsvg':
    import pgi
    import cairocffi
    pgi.require_version('Rsvg', '2.0')
    from pgi.repository import Rsvg


@checks.register()
def check_svg_renderer(app_configs, **kwargs):
    errors = []
    if settings.SVG_RENDERER not in ('rsvg', 'rsvg-convert', 'inkscape'):
        errors.append(
            checks.Error(
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

        # create base elements and counter for clip path ids
        self.g = ''
        self.defs = ''
        self.clip_path_i = 0

        # keep track which area of the image has which altitude currently
        self.altitudes = {}
        self.last_altitude = None

        # for fast numpy operations
        self.np_scale = np.array((self.scale, -self.scale))
        self.np_offset = np.array((-self.left*self.scale, self.top*self.scale))

        # keep track of created blur filters to avoid duplicates
        self.blurs = set()

    def get_dimensions_px(self, buffer):
        # get dimensions of the image in pixels, with or without buffer
        width_px = self.width * self.scale + (self.buffer_px * 2 if buffer else 0)
        height_px = self.height * self.scale + (self.buffer_px * 2 if buffer else 0)
        return height_px, width_px

    def get_xml(self, buffer=False):
        # get the root <svg> element as an ElementTree element, with or without buffer
        height_px, width_px = (self._trim_decimals(str(i)) for i in self.get_dimensions_px(buffer))
        offset_px = self._trim_decimals(str(-self.buffer_px)) if buffer else '0'

        attribs = ' viewBox="'+' '.join((offset_px, offset_px, width_px, height_px))+'"' if buffer else ''

        result = ('<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
                  'width="'+width_px+'" height="'+height_px+'"'+attribs+'>')
        if self.defs:
            result += '<defs>'+self.defs+'</defs>'
        if self.g:
            result += '<g>'+self.g+'</g>'
        result += '</svg>'
        return result

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

    def _trim_decimals(self, data):
        # remove trailing zeros from a decimal – yes this is slow, but it greatly speeds up cairo rendering
        return re.sub(r'([0-9]+)((\.[1-9])[0-9]+|\.[0-9]+)?', r'\1\3', data)

    def _geometry_to_svg(self, geom):
        # scale and move geometry and create svg code for it
        if isinstance(geom, Polygon):
            return ('<path d="' +
                    ' '.join((('M %.1f %.1f L'+(' %.1f %.1f'*(len(ring.coords)-1))+' z') %
                              tuple((np.array(ring)*self.np_scale+self.np_offset).flatten()))
                             for ring in chain((geom.exterior,), geom.interiors))
                    + '"/>').replace('.0 ', ' ')
        if isinstance(geom, LineString):
            return (('<path d="M %.1f %.1f L'+(' %.1f %.1f'*(len(geom.coords)-1))+'"/>') %
                    tuple((np.array(geom)*self.np_scale+self.np_offset).flatten())).replace('.0 ', ' ')
        try:
            geoms = geom.geoms
        except AttributeError:
            return ''
        return ''.join(self._geometry_to_svg(g) for g in geoms)

    def _create_geometry(self, geometry, attribs='', tag='g'):
        # convert a shapely geometry into an svg xml element
        return '<'+tag+attribs+'>'+self._geometry_to_svg(geometry)+'</'+tag+'>'

    def register_clip_path(self, geometry):
        defid = 'clip'+str(self.clip_path_i)
        self.defs += self._create_geometry(geometry, ' id="'+defid+'"', tag='clipPath')
        self.clip_path_i += 1
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
            self.defs += ('<filter id="'+blur_id+'" width="200%" height="200%" x="-50%" y="-50%">'
                          '<feGaussianBlur stdDeviation="'+str(blur_radius * self.scale)+'"/>'
                          '</filter>')
            self.blurs.add(elevation)

        attribs = ' filter="url(#'+blur_id+')" fill="#000" fill-opacity="0.2"'
        if clip_path:
            attribs += ' clip-path="url(#'+self.register_clip_path(clip_path)+')"'
        shadow = self._create_geometry(shadow_geom, attribs)
        self.g += shadow

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

        # if fill_color is set, filter out geometries that cannot be filled
        if fill_color is not None:
            try:
                geometry.geoms
            except AttributeError:
                pass
            else:
                geometry = type(geometry)(tuple(geom for geom in geometry.geoms if hasattr(geom, 'exterior')))
        if geometry.is_empty:
            pass

        attribs = ' fill="'+(fill_color or 'none')+'"'
        if fill_opacity:
            attribs += ' fill-opacity="'+str(fill_opacity)[:4]+'"'
        if stroke_px:
            attribs += ' stroke-width="'+self._trim_decimals(str(stroke_px))+'"'
        elif stroke_width:
            attribs += ' stroke-width="'+self._trim_decimals(str(stroke_width * self.scale))+'"'
        if stroke_color:
            attribs += ' stroke="'+stroke_color+'"'
        if stroke_opacity:
            attribs += ' stroke-opacity="'+str(stroke_opacity)[:4]+'"'
        if stroke_linejoin:
            attribs += ' stroke-linejoin="'+stroke_linejoin+'"'
        if opacity:
            attribs += ' opacity="'+str(opacity)[:4]+'"'
        if filter:
            attribs += ' filter="url(#'+filter+')"'
        if clip_path:
            attribs += ' clip-path="url(#'+clip_path+')"'

        if geometry is not None:
            if not geometry:
                return

            if altitude is not None or elevation is not None:
                if elevation is not None:
                    if elevation:
                        self.add_shadow(geometry, elevation)
                else:
                    for other_altitude, other_geom in self.altitudes.items():
                        self.add_shadow(geometry, altitude-other_altitude, clip_path=other_geom)

                self.clip_altitudes(geometry, altitude)

            element = self._create_geometry(geometry, attribs)

        else:
            element = '<rect width="100%" height="100%"'+attribs+'>'

        self.g += element
        return element
