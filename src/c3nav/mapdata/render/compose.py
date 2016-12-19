import mimetypes

from django.conf import settings
from django.core.files import File
from django.http import HttpResponse

from c3nav.mapdata.utils.misc import get_render_path


class LevelComposer:
    def get_level_image(self, request, level):
        if settings.DIRECT_EDITING:
            img = get_render_path('png', level.name, 'full', True)
        else:
            img = get_render_path('png', level.name, 'full', False)

        response = HttpResponse(content_type=mimetypes.guess_type(img)[0])
        for chunk in File(open(img, 'rb')).chunks():
            response.write(chunk)
        return response


composer = LevelComposer()
