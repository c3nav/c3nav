import os

from django.conf import settings
from django.contrib.staticfiles.finders import BaseFinder
from django.core.files.storage import FileSystemStorage

logo_paths = {
    'header_logo': settings.HEADER_LOGO,
    'header_logo_anim': settings.HEADER_LOGO_ANIM,
    'favicon': settings.FAVICON,
}

logofinder_results = {
    os.path.join(prefix, os.path.basename(path)): path
    for prefix, path in logo_paths.items()
    if path
}

favicon_package_files = {
    'apple-touch-icon.png',
    'favicon-96x96.png',
    'favicon.ico',
    'favicon.svg',
    'site.webmanifest',
    'web-app-manifest-192x192.png',
    'web-app-manifest-512x512.png',
}

if settings.FAVICON_PACKAGE and os.path.isdir(settings.FAVICON_PACKAGE):
    logofinder_results.update({
        os.path.join('favicon_package', file): os.path.join(settings.FAVICON_PACKAGE, file)
        for file in favicon_package_files
    })


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
        if settings.FAVICON_PACKAGE and os.path.isdir(settings.FAVICON_PACKAGE):
            storage = FileSystemStorage(location=settings.FAVICON_PACKAGE)
            storage.prefix = 'favicon_package'
            result += [(filename, storage) for filename in favicon_package_files]
        return result
