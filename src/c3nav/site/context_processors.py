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


def colors(request):
    return {'colors': {
        'primary_color': settings.PRIMARY_COLOR,
        'header_background_color': settings.HEADER_BACKGROUND_COLOR,
        'header_text_color': settings.HEADER_TEXT_COLOR,
        'header_text_hover_color': settings.HEADER_TEXT_HOVER_COLOR,
        'safari_mask_icon_color': settings.SAFARI_MASK_ICON_COLOR,
        'msapplication_tile_color': settings.MSAPPLICATION_TILE_COLOR,
    }}
