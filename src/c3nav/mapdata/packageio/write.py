import difflib
import json
import os
import sys
from datetime import datetime

from django.conf import settings
from django.utils import timezone

from ..models import Package
from .utils import json_encode


def write_packages(prettify=False, check_only=False):
    if not check_only:
        sys.out.write('Writing Map Packages…')

    count = 0
    for package in Package.objects.all():
        if not check_only:
            sys.out.write('\n'+package.name)
        count += write_package(package, prettify, check_only)
    return count


def write_package(package, prettify=False, check_only=False):
    count = 0
    count += _write_object(package, package.directory, 'pkg.json', prettify, check_only)
    count += _write_folder(package.levels.all(), os.path.join(package.directory, 'levels'), prettify, check_only)
    count += _write_folder(package.sources.all(), os.path.join(package.directory, 'sources'), prettify, check_only,
                           check_sister_file=True)
    return count


def _write_folder(objects, path, prettify=False, check_only=False, check_sister_file=False):
    count = 0
    filenames = set()
    full_path = os.path.join(settings.MAP_ROOT, path)
    if objects:
        if not os.path.isdir(full_path):
            os.mkdir(full_path)
        for obj in objects:
            filename = '%s.json' % obj.name
            filenames.add(filename)
            count += _write_object(obj, path, filename, prettify, check_only)

    if os.path.isdir(full_path):
        for filename in os.listdir(full_path):
            full_filename = os.path.join(full_path, filename)
            if filename in filenames or not filename.endswith('.json') or not os.path.isfile(full_filename):
                continue

            count += 1
            if check_only:
                sys.stdout.writelines(difflib.unified_diff(
                    list(open(full_filename)),
                    [],
                    fromfiledate=timezone.make_aware(
                        datetime.fromtimestamp(os.path.getmtime(full_filename))
                    ).isoformat(),
                    tofiledate=timezone.make_aware(datetime.fromtimestamp(0)).isoformat(),
                    fromfile=os.path.join(path, filename),
                    tofile=os.path.join(path, filename)
                ))
            else:
                os.remove(full_filename)
                if check_sister_file and os.path.isfile(full_filename[:-5]):
                    os.remove(full_filename[:-5])
    return count


def _write_object(obj, path, filename, prettify=False, check_only=False):
    full_path = os.path.join(settings.MAP_ROOT, path)
    full_filename = os.path.join(full_path, filename)
    new_data = obj.tofile()
    new_data_encoded = json_encode(new_data)
    old_data = None
    old_data_encoded = None
    if os.path.isfile(full_filename):
        with open(full_filename) as f:
            old_data_encoded = f.read()
        old_data = json.loads(old_data_encoded, parse_int=float)
        if old_data != json.loads(new_data_encoded, parse_int=float):
            if not check_only:
                sys.stdout.write('- Updated: '+os.path.join(path, filename))
        elif old_data_encoded != new_data_encoded:
            if not prettify:
                return 0
            if not check_only:
                sys.stdout.write('- Beautified: '+os.path.join(path, filename))
        else:
            return 0
    else:
        if not check_only:
            sys.stdout.write('- Created: '+os.path.join(path, filename))

    if check_only:
        sys.stdout.writelines(difflib.unified_diff(
            [] if old_data is None else [(line+'\n') for line in old_data_encoded.split('\n')],
            [(line+'\n') for line in new_data_encoded.split('\n')],
            fromfiledate=timezone.make_aware(
                datetime.fromtimestamp(0 if old_data is None else os.path.getmtime(full_filename))
            ).isoformat(),
            tofiledate=timezone.now().isoformat(),
            fromfile=os.path.join(path, filename),
            tofile=os.path.join(path, filename)
        ))
    else:
        with open(full_filename, 'w') as f:
            f.write(new_data_encoded)
    return 1
