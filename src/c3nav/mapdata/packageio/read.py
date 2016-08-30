import json
import os

from django.conf import settings
from django.core.management.base import CommandError

from ..models import Level, Package, Source
from .utils import ObjectCollection, json_encode


def read_packages():
    print('Detecting Map Packages…')

    objects = ObjectCollection()
    for directory in os.listdir(settings.MAP_ROOT):
        print('\n'+directory)
        if not os.path.isdir(os.path.join(settings.MAP_ROOT, directory)):
            continue
        read_package(directory, objects)

    objects.apply_to_db()


def read_package(directory, objects=None):
    if objects is None:
        objects = ObjectCollection()

    path = os.path.join(settings.MAP_ROOT, directory)

    # Main JSON
    try:
        package = json.load(open(os.path.join(path, 'pkg.json')))
    except FileNotFoundError:
        raise CommandError('no pkg.json found')

    package = Package.fromfile(package, directory)
    objects.add_package(package)
    objects.add_levels(_read_folder(package['name'], Level, os.path.join(path, 'levels')))
    objects.add_sources(_read_folder(package['name'], Source, os.path.join(path, 'sources'), check_sister_file=True))
    return objects


def _read_folder(package, cls, path, check_sister_file=False):
    objects = []
    if not os.path.isdir(path):
        return []
    for filename in os.listdir(path):
        if not filename.endswith('.json'):
            continue

        full_filename = os.path.join(path, filename)
        if not os.path.isfile(full_filename):
            continue

        name = filename[:-5]
        if check_sister_file and os.path.isfile(name):
            raise CommandError('%s: %s is missing.' % (filename, name))

        objects.append(cls.fromfile(json.load(open(full_filename)), package, name))
    return objects


def _fromfile_validate(cls, data, name):
    obj = cls.fromfile(json.loads(data), name=name)
    formatted_data = json_encode(obj.tofile())
    if data != formatted_data:
        raise CommandError('%s.json is not correctly formatted, its contents are:\n---\n' +
                           data+'\n---\nbut they should be\n---\n'+formatted_data+'\n---')
