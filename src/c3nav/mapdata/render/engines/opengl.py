import io
import threading
from collections import namedtuple
from itertools import chain
from queue import Queue
from typing import Optional

import ModernGL
import numpy as np
from PIL import Image
from shapely.geometry import CAP_STYLE, JOIN_STYLE, Polygon
from shapely.ops import unary_union

from c3nav.mapdata.render.data import HybridGeometry
from c3nav.mapdata.render.engines.base import FillAttribs, StrokeAttribs
from c3nav.mapdata.render.engines.base3d import Base3DEngine
from c3nav.mapdata.utils.mesh import triangulate_polygon


class RenderContext(namedtuple('RenderContext', ('width', 'height', 'ctx', 'prog', 'fbo'))):
    """
    A OpenGL Render Context with program and framebuffer. Can only be used by thread that created it.
    """
    @classmethod
    def create(cls, width, height):
        ctx = ModernGL.create_standalone_context()

        color_rbo = ctx.renderbuffer((width, height), samples=ctx.max_samples)
        fbo = ctx.framebuffer([color_rbo])
        fbo.use()

        prog = ctx.program([
            ctx.vertex_shader('''
                #version 330
                in vec3 in_vert;
                in vec4 in_color;
                out vec4 v_color;

                uniform vec3 scale;
                uniform vec3 offset;

                void main() {
                    gl_Position = vec4(in_vert*scale+offset, 1.0);
                    v_color = in_color;
                }
            '''),
            ctx.fragment_shader('''
                #version 330
                in vec4 v_color;
                out vec4 f_color;
                void main() {
                    f_color = v_color;
                }
            '''),
        ])

        return cls(width, height, ctx, prog, fbo)


class RenderTask:
    """
    Async Render Task
    """
    __slots__ = ('width', 'height', 'scale', 'offset', 'background_rgb', 'vertices', 'event', 'result')

    def __init__(self, width, height, scale, offset, background_rgb, vertices):
        self.width = width
        self.height = height
        self.scale = scale
        self.offset = offset
        self.background_rgb = background_rgb
        self.vertices = vertices

        self.event = threading.Event()
        self.result = None

    def get_result(self) -> bytes:
        """
        Wait the task to complete and return the result.
        """
        self.event.wait()
        return self.result

    def set_result(self, result: bytes):
        """
        Set the task result and mark it as completed.
        """
        self.result = result
        self.event.set()


class OpenGLWorker(threading.Thread):
    """
    OpenGL Worker Thread
    This is needed to reuse OpenGL resources, because they have to be always accessed from the same thread.
    """
    def __init__(self):
        threading.Thread.__init__(self, daemon=True)
        self._queue = Queue()
        self.ctx = None

    def _get_ctx(self, width, height):
        ctx = self.ctx
        if ctx is None or ctx.width != width or ctx.height != height:
            ctx = RenderContext.create(width, height)
            self.ctx = ctx
        return ctx

    def run(self):
        while True:
            task = self._queue.get()

            ctx = self._get_ctx(task.width, task.height)
            ctx.ctx.clear(*task.background_rgb)

            ctx.prog.uniforms['scale'].value = task.scale
            ctx.prog.uniforms['offset'].value = task.offset

            if task.vertices:
                vbo = ctx.ctx.buffer(task.vertices)
                vao = ctx.ctx.simple_vertex_array(ctx.prog, vbo, ['in_vert', 'in_color'])
                vao.render()

            color_rbo2 = ctx.ctx.renderbuffer((task.width, task.height))
            fbo2 = ctx.ctx.framebuffer(color_rbo2)
            ctx.ctx.copy_framebuffer(fbo2, ctx.fbo)

            img = Image.frombytes('RGB', (task.width, task.height), fbo2.read(components=3))

            f = io.BytesIO()
            img.save(f, 'PNG')
            f.seek(0)
            task.set_result(f.read())

    def render(self, width: int, height: int, scale: tuple, offset: tuple, background_rgb: tuple, vertices: bytes):
        """
        Render image and return it as PNG bytes
        """
        task = RenderTask(width, height, scale, offset, background_rgb, vertices)
        self._queue.put(task)
        return task.get_result()


class OpenGLEngine(Base3DEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        scale_x = self.scale / self.width * 2
        scale_y = self.scale / self.height * 2
        scale_z = (scale_x+scale_y) / 2

        self.gl_scale = (scale_x, -scale_y, scale_z)
        self.gl_offset = (-self.minx * scale_x - 1, self.maxy * scale_y - 1, 0)

    def _add_geometry(self, geometry, fill: Optional[FillAttribs], stroke: Optional[StrokeAttribs], **kwargs):
        if fill is not None:
            self.vertices.append(self._place_geometry(geometry, self.color_to_rgb(fill.color), offset=False))

        if stroke is not None:
            width = max(stroke.width, (stroke.min_px or 0) / self.scale) / 2

            # if width would be <1px, emulate it through opacity on a 1px width
            one_pixel = 1 / self.scale / 2
            if width < one_pixel:
                alpha = width/one_pixel
                width = one_pixel
            else:
                alpha = 1

            self.vertices.append(self._create_border(geometry, width, self.color_to_rgb(stroke.color, alpha=alpha)))

    def _create_border(self, geometry: HybridGeometry, width, append=None):
        altitude = np.vstack(geometry.faces)[:, :, 2].max()+0.001
        geometry = self.buffered_bbox.intersection(geometry.geom)

        lines = tuple(chain(*(
            ((geom.exterior, *geom.interiors) if isinstance(geom, Polygon) else (geom,))
            for geom in getattr(geometry, 'geoms', (geometry,))
        )))

        if not lines:
            return np.empty((0, 3, 3+len(append)))

        lines = unary_union(lines).buffer(width, cap_style=CAP_STYLE.flat, join_style=JOIN_STYLE.mitre)

        vertices, faces = triangulate_polygon(lines)
        triangles = np.dstack((vertices[faces], np.full((faces.size, 1), fill_value=altitude).reshape((-1, 3, 1))))

        return self._append_to_vertices(triangles.astype(np.float32), append)

    worker = OpenGLWorker()

    def render(self) -> bytes:
        return self.worker.render(self.width, self.height, self.gl_scale, self.gl_offset, self.background_rgb,
                                  np.vstack(self.vertices).astype(np.float32).tobytes() if self.vertices else b'')


OpenGLEngine.worker.start()
