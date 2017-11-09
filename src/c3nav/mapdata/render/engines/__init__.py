from django.conf import settings
from django.core import checks

from c3nav.mapdata.render.engines.svg import SVGEngine  # noqa
from c3nav.mapdata.render.engines.stl import STLEngine  # noqa


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
