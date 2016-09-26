import json
import os
import re
import subprocess

from django.conf import settings
from django.core.management import CommandError

from ..models import Level, Package
from .const import ordered_models


class MapdataReader:
    def __init__(self):
        self.content = {}
        self.package_names_by_dir = {}
        self.saved_items = {model: {} for model in ordered_models}

    def read_packages(self):
        print('Detecting Map Packages…')

        for directory in os.listdir(settings.MAP_ROOT):
            print('\n' + directory)
            if not os.path.isdir(os.path.join(settings.MAP_ROOT, directory)):
                continue
            self.read_package(directory)

    def read_package(self, package_dir):
        full_package_dir = os.path.join(settings.MAP_ROOT, package_dir)

        for path, sub_dirs, filenames in os.walk(full_package_dir):
            sub_dirs[:] = sorted([directory for directory in sub_dirs if not directory.startswith('.')])
            for filename in sorted(filenames):
                if not filename.endswith('.json'):
                    continue
                self.add_file(package_dir, path[len(full_package_dir) + 1:], filename)

    def _add_item(self, item):
        if item.package_dir not in self.content:
            self.content[item.package_dir] = {model: [] for model in ordered_models}
        self.content[item.package_dir][item.model].append(item)

    def add_file(self, package_dir, path, filename):
        file_path = os.path.join(package_dir, path, filename)
        relative_file_path = os.path.join(path, filename)
        print(file_path)
        for model in ordered_models:
            if re.search(model.path_regex, relative_file_path):
                self._add_item(ReaderItem(self, package_dir, path, filename, model))
                break
        else:
            raise CommandError('Unexpected JSON file: %s' % file_path)

    def apply_to_db(self):
        # Collect all Packages
        package_items_by_name = {}
        package_dirs_by_name = {}
        for package_dir, items_by_model in self.content.items():
            if not items_by_model[Package]:
                raise CommandError('Missing package file: %s' % package_dir)

            if len(items_by_model[Package]) > 1:
                raise CommandError('Multiple package files: %s' % package_dir)

            package_item = items_by_model[Package][0]
            package_items_by_name[package_item.data['name']] = package_item
            package_dirs_by_name[package_item.data['name']] = package_dir
            self.package_names_by_dir[package_dir] = package_item.data['name']

        # Resolve Package Dependencies
        unresolved_packages = set(package_items_by_name.keys())
        resolved_packages = set()
        package_order = []
        while unresolved_packages:
            resolvable = set([name for name in unresolved_packages if
                              not set(package_items_by_name[name].data['depends'])-resolved_packages])
            if not resolvable:
                raise CommandError('Could not resolve package dependencies: %s' % unresolved_packages)
            package_order.extend(resolvable)
            unresolved_packages -= resolvable
            resolved_packages |= resolvable

        # Create new and update existing entries
        for package_name in package_order:
            print('')
            package_dir = package_dirs_by_name[package_name]
            items_by_model = self.content[package_dir]
            for model in ordered_models:
                items = items_by_model[model]
                for item in items:
                    item.save()

        # Delete old entries
        for model in reversed(ordered_models):
            queryset = model.objects.exclude(name__in=self.saved_items[model].keys())
            for name in queryset.values_list('name', flat=True):
                print('- Deleted %s: %s' % (model.__name__, name))
            queryset.delete()


class ReaderItem:
    def __init__(self, reader, package_dir, path, filename, model):
        self.reader = reader
        self.package_dir = package_dir
        self.path = path
        self.filename = filename
        self.model = model
        self.obj = None
        self.path_in_package = os.path.join(self.path, self.filename)

        try:
            with open(os.path.join(settings.MAP_ROOT, package_dir, path, filename)) as f:
                self.content = f.read()
        except Exception as e:
            raise CommandError('Could not read File: %s' % e)

        try:
            self.json_data = json.loads(self.content)
        except json.JSONDecodeError as e:
            raise CommandError('Could not decode JSON: %s' % e)

        self.data = {'name': filename[:-5]}

        if self.model == Package:
            self.data['directory'] = package_dir
            self.data['commit_id'] = None
            try:
                full_package_dir = os.path.join(settings.MAP_ROOT, package_dir)
                result = subprocess.Popen(['git', '-C', full_package_dir, 'rev-parse', '--verify', 'HEAD'],
                                          stdout=subprocess.PIPE)
                returncode = result.wait()
            except FileNotFoundError:
                pass
            else:
                if returncode == 0:
                    self.data['commit_id'] = result.stdout.read().strip()

        try:
            add_data = self.model.fromfile(self.json_data, self.path_in_package)
        except Exception as e:
            raise CommandError('Could not load data: %s' % e)
        self.data.update(add_data)

    relations = {
        'level': Level,
    }

    def save(self):
        if self.model != Package:
            package_name = self.reader.package_names_by_dir[self.package_dir]
            self.data['package'] = self.reader.saved_items[Package][package_name].obj

        # Change name references to the referenced object
        for name, model in self.relations.items():
            if name in self.data:
                self.data[name] = self.reader.saved_items[model][self.data[name]].obj

        obj, created = self.model.objects.update_or_create(name=self.data['name'], defaults=self.data)
        if created:
            print('- Created %s: %s' % (self.model.__name__, obj.name))

        self.obj = obj
        self.reader.saved_items[self.model][obj.name] = self
