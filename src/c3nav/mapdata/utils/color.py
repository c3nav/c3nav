from functools import lru_cache


@lru_cache()
def color_to_rgb(color, alpha=None):
    if color.startswith('#'):
        return (*(int(color[i:i + 2], 16) / 255 for i in range(1, 6, 2)), 1 if alpha is None else alpha)
    if color.startswith('rgba('):
        color = tuple(float(i.strip()) for i in color.strip()[5:-1].split(','))
        return (*(i/255 for i in color[:3]), color[3] if alpha is None else alpha)
    raise ValueError('invalid color string!')


@lru_cache()
def rgb_to_color(rgb):
    # noinspection PyStringFormat
    return 'rgba(%d, %d, %d, %.1f)' % (*(i*255 for i in rgb[:3]), rgb[3])
