from c3nav import settings
from c3nav.mapdata.utils.cache.cache_decorator import mapdata_cache


def css_vars_as_str(vars):
    css_str = ''
    for name, value in vars.items():
        if name is not None and name != '':
            css_str += f'--color-{name}: {value};'
    return css_str


remove = ['grid']

modify = {
    'grid-text': ('grid', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.6)'),
    'grid-lines': ('grid', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.2)'),
    'modal-backdrop': ('modal-backdrop', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.2)'),
    'shadow': ('shadow', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.2)'),
    'control-shadow': ('shadow', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.6)'),
    'overlay-background': ('overlay-background', lambda rgb: f'rgba({rgb[0]},{rgb[1]},{rgb[2]},0.6)'),
}


def modify_vars(css_vars):
    from c3nav.mapdata.utils.color import color_to_rgb
    for key, (source, fn) in modify.items():
        try:
            rgb = [x * 255 for x in color_to_rgb(css_vars[source])]
        except ValueError:  # ignore invalid colors
            continue
        css_vars[key] = fn(rgb)
    for key in remove:
        del css_vars[key]
    falsy_vars = []
    for key, val in css_vars.items():
        if not val:
            falsy_vars.append(key)
    for key in falsy_vars:
        del css_vars[key]


def make_themes(theme_models):
    from c3nav import settings
    from django.utils.translation import gettext_lazy as _

    themes = {}
    base_css_vars = settings.BASE_THEME['css_vars'].copy()
    modify_vars(base_css_vars)
    primary_color = base_css_vars['primary']
    if settings.BASE_THEME['randomize_primary_color']:
        del base_css_vars['primary']
    base_theme_vars_str = css_vars_as_str(base_css_vars)
    base_theme = {
        'css_vars': ':root{%s}' % base_theme_vars_str,
        'theme_color': base_css_vars['header-background'],
        'randomize_primary_color': settings.BASE_THEME['randomize_primary_color'],
        'primary_color': primary_color,
    }
    if settings.BASE_THEME['is_dark']:
        default_dark = base_theme
        default_light = None
    else:
        default_light = base_theme
        default_dark = None

    for theme in theme_models:
        css_vars = theme.css_vars()
        modify_vars(css_vars)
        primary_color = css_vars['primary'] if 'primary' in css_vars else base_theme['primary_color']
        if theme.randomize_primary_color:
            del css_vars['primary']
        css_vars_str = css_vars_as_str(css_vars)
        css_code = (':root{%s}' % css_vars_str)
        themes[theme.pk] = {
            'name': theme.title,
            'css_vars': css_code,
            'css_extra': theme.extra_css,
            'funky': theme.funky,
            'theme_color_dark': theme.color_css_header_background,
            'theme_color_light': theme.color_css_header_background,
            'randomize_primary_color': theme.randomize_primary_color,
            'primary_color': primary_color,
        }
        if theme.default:
            default_theme = {
                    'css_vars': css_code,
                    'css_extra': theme.extra_css,
                    'theme_color': css_vars['header-background'],
                    'randomize_primary_color': theme.randomize_primary_color,
                    'primary_color': primary_color,
                }
            if theme.dark:
                default_dark = default_theme
            else:
                default_light = default_theme

    if default_dark is not None and default_light is not None:
        name = _('Automatic')
        css_code = ('@media(prefers-color-scheme:light){%s@media(prefers-color-scheme:dark){%s}'
                    % (default_light['css_vars'], default_dark['css_vars']))
        randomize_primary_color = default_dark['randomize_primary_color'] or default_light['randomize_primary_color']
    else:
        name = _('Default')
        default_theme = default_light or default_dark
        css_code = default_theme['css_vars']
        randomize_primary_color = default_theme['randomize_primary_color']

    themes[0] = {
        'name': name,
        'css_vars': css_code,
        'css_extra': '',
        'funky': False,
        'theme_color_dark': default_dark['theme_color'] if default_dark is not None else default_light['theme_color'],
        'theme_color_light': default_light['theme_color'] if default_light is not None else default_dark['theme_color'],
        'randomize_primary_color': randomize_primary_color,
        'primary_color': default_light['primary_color'] if default_light is not None else default_dark['primary_color'],
    }

    return themes


# @mapdata_cache
def css_themes_all():
    from c3nav.mapdata.models.theme import Theme
    return make_themes(Theme.objects.all())


# @mapdata_cache
def css_themes_public():
    from c3nav.mapdata.models.theme import Theme
    return make_themes(Theme.objects.filter(public=True))


def random_color():
    import random
    return settings.RANDOM_PRIMARY_COLOR_LIST[random.randrange(0, 360)]


def get_random_primary_color(request):
    if settings.PRIMARY_COLOR_RANDOMISATION['mode'] == 'off':
        return settings.BASE_THEME['css_vars']['primary']
    elif settings.PRIMARY_COLOR_RANDOMISATION['mode'] == 'request':
        return random_color()
    elif settings.PRIMARY_COLOR_RANDOMISATION['mode'] == 'session':
        if 'randomized_primary_color' not in request.session:
            request.session['randomized_primary_color'] = random_color()
        return request.session['randomized_primary_color']
    elif settings.PRIMARY_COLOR_RANDOMISATION['mode'] == 'time':
        from django.core.cache import cache
        color = cache.get('randomized_primary_color', None)
        if color is None:
            color = random_color()
            cache.set('randomized_primary_color', color, settings.PRIMARY_COLOR_RANDOMISATION['duration'].total_seconds())
        return color