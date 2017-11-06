import io

import ModernGL
import numpy as np
from PIL import Image

from c3nav.mapdata.render.engines.base import RenderEngine


class OpenGLEngine(RenderEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vertices = []
        self.ctx = ModernGL.create_standalone_context()

        self.color_rbo = self.ctx.renderbuffer((self.width, self.height))
        self.depth_rbo = self.ctx.depth_renderbuffer((self.width, self.height))
        self.fbo = self.ctx.framebuffer([self.color_rbo], self.depth_rbo)
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

    def _add_geometry(self, geometry, fill=None, stroke=None, altitude=None, height=None, shape_cache_key=None):
        pass

    def get_png(self) -> bytes:
        if self.vertices:
            vbo = self.ctx.buffer(np.hstack(self.vertices).tobytes())

            # We control the 'in_vert' and `in_color' variables
            vao = self.ctx.simple_vertex_array(self.prog, vbo, ['in_vert', 'in_color'])
            vao.render()

        img = Image.frombytes('RGB', (self.width, self.height), self.fbo.read(components=3))

        f = io.BytesIO()
        img.save(f, 'PNG')
        f.seek(0)
        return f.read()
