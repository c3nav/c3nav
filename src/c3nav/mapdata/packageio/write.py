import json
import os

from django.conf import settings

from ..models import Package
from .utils import json_encode


def write_packages(prettify=False):
    print('Writing Map Packages…')
    for package in Package.objects.all():
        print('\n'+package.name)
        write_package(package, prettify)


def write_package(package, prettify=False):
    pkg_path = os.path.join(settings.MAP_ROOT, package.directory)

    with open(os.path.join(pkg_path, 'pkg.json'), 'w') as f:
        f.write(json_encode(package.tofile()))

    _write_folder(package, package.levels.all(), 'levels', prettify)
    _write_folder(package, package.sources.all(), 'sources', prettify, check_sister_file=True)


def _write_folder(package, objects, path, prettify=False, check_sister_file=False):
    filenames = set()
    full_path = os.path.join(settings.MAP_ROOT, package.directory, path)
    if objects:
        if not os.path.isdir(full_path):
            os.mkdir(full_path)
        for obj in objects:
            filename = '%s.json' % obj.name
            filenames.add(filename)

            full_filename = os.path.join(full_path, filename)
            new_data = obj.tofile()
            new_data_encoded = json_encode(new_data)
            if os.path.isfile(full_filename):
                with open(full_filename) as f:
                    old_data_encoded = f.read()
                old_data = json.loads(old_data_encoded, parse_int=float)
                if old_data != json.loads(new_data_encoded, parse_int=float):
                    print('- Updated: '+os.path.join(path, filename))
                elif old_data_encoded != new_data_encoded:
                    if not prettify:
                        continue
                    print('- Beautified: '+os.path.join(path, filename))
                else:
                    continue
            else:
                print('- Created: '+os.path.join(path, filename))
            with open(full_filename, 'w') as f:
                f.write(new_data_encoded)

    if os.path.isdir(path):
        for filename in os.listdir(path):
            full_filename = os.path.join(path, filename)
            if filename not in filenames and filename.endswith('.json') and os.path.isfile(full_filename):
                os.remove(full_filename)
                if check_sister_file and os.path.isfile(full_filename[:-5]):
                    os.remove(full_filename[:-5])
