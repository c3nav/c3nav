from c3nav.mapdata.models import Level
from c3nav.mapdata.render.renderer import LevelRenderer  # noqa


def render_all_levels():
    for level in Level.objects.all():
        renderer = LevelRenderer(level)
        renderer.render_png()
