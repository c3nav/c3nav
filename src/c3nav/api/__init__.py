from functools import wraps

from rest_framework.generics import GenericAPIView
from rest_framework.renderers import JSONRenderer

from c3nav.mapdata.utils.json import json_encoder_reindent

default_app_config = 'c3nav.api.apps.APIConfig'


orig_render = JSONRenderer.render


@wraps(JSONRenderer.render)
def nicer_renderer(self, data, accepted_media_type=None, renderer_context=None):
    if self.get_indent(accepted_media_type, renderer_context) is None:
        return orig_render(self, data, accepted_media_type, renderer_context)
    shorten_limit = 50
    if isinstance(data, (list, tuple)):
        shorten_limit = 5 if any(('geometry' in item) for item in data[:50]) else 50
    shorten = isinstance(data, (list, tuple)) and len(data) > shorten_limit
    if shorten:
        remaining_len = len(data)-shorten_limit
        data = data[:shorten_limit]
    result = json_encoder_reindent(lambda d: orig_render(self, d, accepted_media_type, renderer_context), data)
    if shorten:
        result = (result[:-2] +
                  ('\n    ...%d more elements (truncated for HTML preview)...' % remaining_len).encode() +
                  result[-2:])
    return result


# Monkey patch for nicer indentation in the django rest framework
JSONRenderer.render = nicer_renderer

# Fuck serializers!
del GenericAPIView.get_serializer
