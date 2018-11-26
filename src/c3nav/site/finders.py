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

favicon_package_files = {
        'android-chrome-192x192.png',
        'android-chrome-512x512.png',
        'apple-touch-icon.png',
        'browserconfig.xml',
        'mstile-150x150.png',
        'mstile-310x310.png',
        'safari-pinned-tab.svg',
        'site.webmanifest',
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
