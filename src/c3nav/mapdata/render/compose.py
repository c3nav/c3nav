import os

from django.http import HttpResponse
from PIL import Image

from c3nav.mapdata.utils.misc import get_render_path


class LevelComposer:
    images = {}
    images_mtimes = {}

    @classmethod
    def _get_image(cls, filename, cached=True):
        mtime = None
        if cached:
            mtime = os.path.getmtime(filename)
            if filename in cls.images:
                if cls.images_mtimes[filename] == mtime:
                    return cls.images[filename]

        img = Image.open(filename)

        if cached:
            cls.images[filename] = img
            cls.images_mtimes[filename] = mtime

        return img

    def _get_public_level_image(self, level):
        return self._get_image(get_render_path('png', level.name, 'full', True))

    def get_level_image(self, request, level):
        img = self._get_public_level_image(level)
        response = HttpResponse(content_type="image/png")
        img.save(response, 'PNG')
        return response


composer = LevelComposer()
