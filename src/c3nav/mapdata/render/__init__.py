from c3nav.mapdata.models import Level
from c3nav.mapdata.render.renderer import LevelRenderer, get_render_path  # noqa


def render_all_levels(show_accessibles=False):

    renderers = []
    for level in Level.objects.all():
        renderers.append(LevelRenderer(level, only_public=False))
        renderers.append(LevelRenderer(level, only_public=True))

    for renderer in renderers:
        renderer.render_base(show_accessibles=show_accessibles)

    for renderer in renderers:
        if not renderer.level.intermediate:
            renderer.render_simple()

    for renderer in renderers:
        if not renderer.level.intermediate:
            renderer.render_full()
