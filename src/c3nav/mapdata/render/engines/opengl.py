import io
from collections import deque
from typing import Union

import ModernGL
import numpy as np
from PIL import Image
from shapely.geometry import MultiPolygon, Polygon
from trimesh.creation import triangulate_polygon

from c3nav.mapdata.render.engines.base import RenderEngine
from c3nav.mapdata.utils.geometry import assert_multipolygon


class OpenGLEngine(RenderEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vertices = []
        self.ctx = ModernGL.create_standalone_context()

        self.color_rbo = self.ctx.renderbuffer((self.width, self.height))
        self.fbo = self.ctx.framebuffer([self.color_rbo])
        self.fbo.use()

        self.ctx.clear(*(i/255 for i in self.background_rgb))

        self.prog = self.ctx.program([
            self.ctx.vertex_shader('''
                #version 330
                in vec2 in_vert;
                in vec3 in_color;
                out vec3 v_color;
                void main() {
                    gl_Position = vec4(in_vert, 0.0, 1.0);
                    v_color = in_color;
                }
            '''),
            self.ctx.fragment_shader('''
                #version 330
                in vec3 v_color;
                out vec4 f_color;
                void main() {
                    f_color = vec4(v_color, 1.0);
                }
            '''),
        ])

        scale_x = self.scale / self.width * 2
        scale_y = self.scale / self.height * 2

        self.np_scale = np.array((scale_x, -scale_y))
        self.np_offset = np.array((-self.minx * scale_x - 1, self.maxy * scale_y - 1))

    def _create_geometry(self, geometry: Union[Polygon, MultiPolygon], append=None):
        triangles = deque()

        for i, polygon in enumerate(assert_multipolygon(geometry)):
            vertices, faces = triangulate_polygon(polygon)
            triangles.append(vertices[faces.flatten()])

        vertices = np.vstack(triangles).astype(np.float32)
        vertices = vertices * self.np_scale + self.np_offset
        if append is not None:
            append = np.array(append, dtype=np.float32).flatten()
            vertices = np.hstack((
                vertices,
                append.reshape(1, append.size).repeat(vertices.shape[0], 0)
            ))
        return vertices.flatten()

    def _add_geometry(self, geometry, fill=None, stroke=None, altitude=None, height=None, shape_cache_key=None):
        if fill is not None:
            self.vertices.append(self._create_geometry(geometry, self.hex_to_rgb(fill.color)))

    def get_png(self) -> bytes:
        if self.vertices:
            vbo = self.ctx.buffer(np.hstack(self.vertices).astype(np.float32).tobytes())

            # We control the 'in_vert' and `in_color' variables
            vao = self.ctx.simple_vertex_array(self.prog, vbo, ['in_vert', 'in_color'])
            vao.render()

        img = Image.frombytes('RGB', (self.width, self.height), self.fbo.read(components=3))

        f = io.BytesIO()
        img.save(f, 'PNG')
        f.seek(0)
        return f.read()
