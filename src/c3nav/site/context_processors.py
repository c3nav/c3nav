import json
import os

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder

from c3nav.site.finders import favicon_package_files, logo_paths

logos_result = {
    prefix: os.path.join(prefix, os.path.basename(path)) if path else None
    for prefix, path in logo_paths.items()
}

if settings.FAVICON_PACKAGE:
    logos_result['favicon_package'] = {
        '.'.join(file.split('.')[:-1]): os.path.join('favicon_package', file)
        for file in favicon_package_files
    }
else:
    logos_result['favicon_package'] = None


def logos(request):
    return logos_result


def user_data_json(request):
    return {
        'user_data_json': lambda: json.dumps(dict(request.user_data), separators=(',', ':'), cls=DjangoJSONEncoder),
    }


def header_logo_mask(request):
    return {
        'header_logo_mask_mode': settings.HEADER_LOGO_MASK_MODE,
    }


def theme(request):
    from c3nav.site.themes import css_themes_all, css_themes_public
    if request.user_permissions.nonpublic_themes:
        themes = css_themes_all()
    else:
        themes = css_themes_public()
    active_theme_id = request.session.get('theme', 0)
    if active_theme_id in themes:
        active_theme = themes[active_theme_id]
    else:
        active_theme_id = 0
        active_theme = themes[0]
        request.session['theme'] = active_theme_id

    if active_theme['randomize_primary_color']:
        from c3nav.site.themes import get_random_primary_color
        primary_color = get_random_primary_color(request)
    else:
        primary_color = active_theme['primary_color']

    return {
        'active_theme_id': active_theme_id,
        'active_theme': active_theme,
        'themes': themes,
        'randomize_primary_color': active_theme['randomize_primary_color'],
        'primary_color': primary_color,
    }
