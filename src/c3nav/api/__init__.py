from functools import wraps

from rest_framework.renderers import JSONRenderer

from c3nav.mapdata.utils import json_encoder_reindent

orig_render = JSONRenderer.render


@wraps(JSONRenderer.render)
def nicer_renderer(self, data, accepted_media_type=None, renderer_context=None):
    if self.get_indent(accepted_media_type, renderer_context) is None:
        return orig_render(self, data, accepted_media_type, renderer_context)
    return json_encoder_reindent(lambda d: orig_render(self, d, accepted_media_type, renderer_context), data)


# Monkey patch for nicer indentation in the django rest framework
# JSONRenderer.render = nicer_renderer
