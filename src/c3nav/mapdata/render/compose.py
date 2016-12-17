from django.http import HttpResponse
from PIL import Image

from c3nav.mapdata.render.utils import get_render_path


def get_level_image(request, level):
    im = Image.open(get_render_path('png', level.name, 'full', True))
    response = HttpResponse(content_type="image/png")
    im.save(response, 'PNG')
    return response
