import os

from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.core.files.storage import FileSystemStorage

logo_paths = {
    'header_logo': settings.HEADER_LOGO,
    'favicon': settings.FAVICON,
}

logofinder_results = {
    os.path.join(prefix, os.path.basename(path)): path
    for prefix, path in logo_paths.items()
    if path
}


class LogoFinder(BaseFinder):
    def find(self, path, all=False):
        result = logofinder_results.get(path)
        if not result:
            return []
        if all:
            return [result]
        return result

    def list(self, ignore_patterns):
        result = []
        for prefix, path in logo_paths.items():
            if not path:
                continue
            basedir, filename = os.path.split(path)
            storage = FileSystemStorage(location=basedir)
            storage.prefix = prefix
            result.append((filename, storage))
        return result
