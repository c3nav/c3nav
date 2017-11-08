import io
import threading
from collections import deque, namedtuple
from itertools import chain
from queue import Queue
from typing import Optional, Tuple, Union

import ModernGL
import numpy as np
from PIL import Image
from shapely.geometry import CAP_STYLE, JOIN_STYLE, MultiPolygon, Polygon
from shapely.ops import unary_union

from c3nav.mapdata.render.engines.base import FillAttribs, RenderEngine, StrokeAttribs
from c3nav.mapdata.utils.mesh import triangulate_polygon


class RenderContext(namedtuple('RenderContext', ('width', 'height', 'ctx', 'prog', 'fbo'))):
    """
    A OpenGL Render Context with program and framebuffer. Can only be used by thread that created it.
    """
    @classmethod
    def create(cls, width, height):
        ctx = ModernGL.create_standalone_context()

        color_rbo = ctx.renderbuffer((width, height))
        fbo = ctx.framebuffer([color_rbo])
        fbo.use()

        prog = ctx.program([
            ctx.vertex_shader('''
                #version 330
                in vec2 in_vert;
                in vec4 in_color;
                out vec4 v_color;
                void main() {
                    gl_Position = vec4(in_vert, 0.0, 1.0);
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
    __slots__ = ('width', 'height', 'samples', 'background_rgb', 'vertices', 'event', 'result')

    def __init__(self, width, height, samples, background_rgb, vertices):
        self.width = width
        self.height = height
        self.samples = samples
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

            ctx = self._get_ctx(task.width*task.samples, task.height*task.samples)
            ctx.ctx.clear(*(i / 255 for i in task.background_rgb))

            if task.vertices:
                vbo = ctx.ctx.buffer(task.vertices)
                vao = ctx.ctx.simple_vertex_array(ctx.prog, vbo, ['in_vert', 'in_color'])
                vao.render()

            img = Image.frombytes('RGB', (ctx.width, ctx.height), ctx.fbo.read(components=3))
            img = img.resize((task.width, task.height), Image.BICUBIC)

            f = io.BytesIO()
            img.save(f, 'PNG')
            f.seek(0)
            task.set_result(f.read())

    def render(self, width: int, height: int, samples: int,
               background_rgb: Tuple[int, int, int], vertices: bytes) -> bytes:
        """
        Render image and return it as PNG bytes
        """
        task = RenderTask(width, height, samples, background_rgb, vertices)
        self._queue.put(task)
        return task.get_result()


class OpenGLEngine(RenderEngine):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.vertices = []

        scale_x = self.scale / self.width * 2
        scale_y = self.scale / self.height * 2

        self.samples = 4

        self.np_scale = np.array((scale_x, -scale_y))
        self.np_offset = np.array((-self.minx * scale_x - 1, self.maxy * scale_y - 1))

    def _create_geometry(self, geometry: Union[Polygon, MultiPolygon], append=None):
        triangles = deque()

        vertices, faces = triangulate_polygon(geometry)
        triangles = vertices[faces.flatten()]

        vertices = np.vstack(triangles).astype(np.float32)
        vertices = vertices * self.np_scale + self.np_offset
        if append is not None:
            append = np.array(append, dtype=np.float32).flatten()
            vertices = np.hstack((
                vertices,
                append.reshape(1, append.size).repeat(vertices.shape[0], 0)
            ))
        return vertices.flatten()

    def _add_geometry(self, geometry, fill: Optional[FillAttribs] = None, stroke: Optional[StrokeAttribs] = None,
                      altitude=None, height=None, shape_cache_key=None):
        if fill is not None:
            if stroke is not None and fill.color == stroke.color:
                geometry = geometry.buffer(max(stroke.width, (stroke.min_px or 0) / self.scale),
                                           cap_style=CAP_STYLE.flat, join_style=JOIN_STYLE.mitre)
                stroke = None
            self.vertices.append(self._create_geometry(geometry, self.color_to_rgb(fill.color)))

        if stroke is not None:
            lines = tuple(chain(*(
                ((geom.exterior, *geom.interiors) if isinstance(geom, Polygon) else (geom, ))
                for geom in getattr(geometry, 'geoms', (geometry, ))
            )))
            one_pixel = 1 / self.scale / 2 / self.samples
            width = max(stroke.width, (stroke.min_px or 0) / self.scale) / 2
            if width < one_pixel:
                alpha = width/one_pixel
                width = one_pixel
            else:
                alpha = 1
            self.vertices.append(self._create_geometry(
                unary_union(lines).buffer(width, cap_style=CAP_STYLE.flat, join_style=JOIN_STYLE.mitre),
                self.color_to_rgb(stroke.color, alpha=alpha)
            ))

    worker = OpenGLWorker()

    def get_png(self) -> bytes:
        return self.worker.render(self.width, self.height, self.samples, self.background_rgb,
                                  np.hstack(self.vertices).astype(np.float32).tobytes())


OpenGLEngine.worker.start()
