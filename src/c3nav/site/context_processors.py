import json
import os

from django.core.serializers.json import DjangoJSONEncoder

from c3nav.site.finders import logo_paths

logos_result = {
    prefix: os.path.join(prefix, os.path.basename(path)) if path else None
    for prefix, path in logo_paths.items()
}


def logos(request):
    return logos_result


def mobileclient(request):
    return {
        'mobileclient': 'c3navclient' in request.META['HTTP_USER_AGENT'],
    }


def user_data_json(request):
    return {
        'user_data_json': lambda: json.dumps(dict(request.user_data), cls=DjangoJSONEncoder),
    }
