from django.conf import settings
from django.core import checks

from c3nav.mapdata.render.engines.base import get_engine, get_engine_filetypes, register_engine  # noqa
from c3nav.mapdata.render.engines.blender import BlenderEngine  # noqa
from c3nav.mapdata.render.engines.openscad import OpenSCADEngine  # noqa
from c3nav.mapdata.render.engines.openscadold import OldOpenSCADEngine  # noqa
from c3nav.mapdata.render.engines.stl import STLEngine  # noqa
from c3nav.mapdata.render.engines.svg import SVGEngine  # noqa
from c3nav.mapdata.render.engines.wavefront import WavefrontEngine  # noqa


@checks.register()
def check_image_renderer(app_configs, **kwargs):
    errors = []
    if settings.IMAGE_RENDERER not in ('svg', 'opengl'):
        errors.append(
            checks.Error(
                'Invalid image renderer: '+settings.IMAGE_RENDERER,
                obj='settings.IMAGE_RENDERER',
                id='c3nav.mapdata.E001',
            )
        )
    return errors


if settings.IMAGE_RENDERER == 'opengl':
    from c3nav.mapdata.render.engines.opengl import OpenGLEngine as ImageRenderEngine  # noqa
else:
    from c3nav.mapdata.render.engines.svg import SVGEngine as ImageRenderEngine  # noqa

register_engine(ImageRenderEngine)
