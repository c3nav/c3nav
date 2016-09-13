import json

from django.core.management.base import CommandError

from ..models import Level, Package, Source
from ..utils import json_encoder_reindent


class ObjectCollection:
    def __init__(self):
        self.packages = {}
        self.levels = {}
        self.sources = {}

    def add_package(self, package):
        self._add(self.packages, 'package', package)

    def add_level(self, level):
        self._add(self.levels, 'level', level)

    def add_source(self, source):
        self._add(self.sources, 'source', source)

    def add_packages(self, packages):
        for package in packages:
            self.add_package(package)

    def add_levels(self, levels):
        for level in levels:
            self.add_level(level)

    def add_sources(self, sources):
        for source in sources:
            self.add_source(source)

    def _add(self, container, name, item):
        if item['name'] in container:
            raise CommandError('Duplicate %s name: %s' % (name, item['name']))
        container[item['name']] = item

    def apply_to_db(self):
        for name, package in tuple(self.packages.items()):
            for depname in package['depends']:
                if depname not in self.packages:
                    raise CommandError('Missing dependency: %s' % depname)

        for name, package in tuple(self.packages.items()):
            package = package.copy()
            orig_deps = package.pop('depends', [])
            package, created = Package.objects.update_or_create(name=name, defaults=package)
            package.orig_deps = orig_deps
            self.packages[name] = package
            if created:
                print('- Created package: '+name)

        for name, level in self.levels.items():
            level['package'] = self.packages[level['package']]
            level, created = Level.objects.update_or_create(name=name, defaults=level)
            self.levels[name] = level
            if created:
                print('- Created level: '+name)

        for name, source in self.sources.items():
            source['package'] = self.packages[source['package']]
            source, created = Source.objects.update_or_create(name=name, defaults=source)
            self.sources[name] = source
            if created:
                print('- Created source: '+name)

        for source in Source.objects.exclude(name__in=self.sources.keys()):
            print('- Deleted source: '+source.name)
            source.delete()

        for level in Level.objects.exclude(name__in=self.levels.keys()):
            print('- Deleted level: '+level.name)
            level.delete()

        for package in Package.objects.exclude(name__in=self.packages.keys()):
            print('- Deleted package: '+package.name)
            package.delete()

        for name, package in tuple(self.packages.items()):
            has_deps = []
            for dependency in tuple(package.depends.all()):
                if dependency.name not in package.orig_deps:
                    package.depends.remove(dependency)
                    print('- Removed dependency: '+dependency.name)
                else:
                    has_deps.append(dependency.name)

            for depname in package.orig_deps:
                if depname not in has_deps:
                    package.depends.add(self.packages[depname])
                    print('- Added dependency: '+depname)


def json_encode(data):
    return json_encoder_reindent(json.dumps, data, indent=4)+'\n'
