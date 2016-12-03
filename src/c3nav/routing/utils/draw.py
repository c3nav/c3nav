from django.conf import settings


def _ellipse_bbox(x, y, height):
    x *= settings.RENDER_SCALE
    y *= settings.RENDER_SCALE
    y = height-y
    return ((x - 2, y - 2), (x + 2, y + 2))


def _line_coords(from_point, to_point, height):
    return (from_point.x * settings.RENDER_SCALE, height - (from_point.y * settings.RENDER_SCALE),
            to_point.x * settings.RENDER_SCALE, height - (to_point.y * settings.RENDER_SCALE))
