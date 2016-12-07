from functools import wraps

from rest_framework.renderers import JSONRenderer

from c3nav.mapdata.utils.json import json_encoder_reindent

orig_render = JSONRenderer.render


@wraps(JSONRenderer.render)
def nicer_renderer(self, data, accepted_media_type=None, renderer_context=None):
    if self.get_indent(accepted_media_type, renderer_context) is None:
        return orig_render(self, data, accepted_media_type, renderer_context)
    shorten = isinstance(data, (list, tuple)) and len(data) > 5
    orig_len = None
    if shorten:
        orig_len = len(data)-5
        data = data[:5]
    result = json_encoder_reindent(lambda d: orig_render(self, d, accepted_media_type, renderer_context), data)
    if shorten:
        result = (result[:-2] +
                  ('\n    ...%d more elements (truncated for HTML preview)...' % orig_len).encode() +
                  result[-2:])
    return result


# Monkey patch for nicer indentation in the django rest framework
JSONRenderer.render = nicer_renderer
