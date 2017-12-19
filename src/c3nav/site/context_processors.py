import os

from c3nav.site.finders import logo_paths

logos_result = {
    prefix: os.path.join(prefix, os.path.basename(path)) if path else None
    for prefix, path in logo_paths.items()
}


def logos(request):
    return logos_result
