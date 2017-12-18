import os

from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.core.files.storage import FileSystemStorage


class HeaderLogoFinder(BaseFinder):
    def find(self, path, all=False):
        if path == settings.HEADER_LOGO_NAME:
            return [settings.HEADER_LOGO] if all else settings.HEADER_LOGO
        return []

    def list(self, ignore_patterns):
        if not settings.HEADER_LOGO:
            return []
        basedir, filename = os.path.split(settings.HEADER_LOGO)
        storage = FileSystemStorage(location=basedir)
        storage.prefix = 'logo'
        return [(filename, storage)]
