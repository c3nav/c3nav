import json
import os

from collections import OrderedDict
from django.core.files import File

from django.core.management.base import CommandError


class PackageIOError(CommandError):
    pass


class MapPackagesIO():
    def __init__(self, directories):
        print('Opening Map Packages…')
        self.packages = OrderedDict()
        self.levels = OrderedDict()
        self.sources = OrderedDict()

        for directory in directories:
            print('- '+directory)

            try:
                package = json.load(open(os.path.join(directory, 'pkg.json')))
            except FileNotFoundError:
                raise PackageIOError('no pkg.json found in %s' % directory)

            if package['name'] in self.packages:
                raise PackageIOError('Duplicate package name: %s' % package['name'])

            if 'bounds' in package:
                self._validate_bounds(package['bounds'])

            package['directory'] = directory
            self.packages[package['name']] = package

            for level in package.get('levels', []):
                level = level.copy()
                if level['name'] in self.levels:
                    raise PackageIOError('Duplicate level name: %s in packages %s and %s' %
                                         (level, self.levels[level]['name'], package['name']))

                if not isinstance(level['altitude'], (int, float)):
                    raise PackageIOError('levels: %s: altitude has to be int or float.' % level['name'])

                level['package'] = package['name']
                self.levels[level['name']] = level

            for source in package.get('sources', []):
                source = source.copy()
                if source['name'] in self.sources:
                    raise PackageIOError('Duplicate source name: %s in packages %s and %s' %
                                         (source['name'], self.sources[source['name']]['name'], package['name']))

                self._validate_bounds(source['bounds'], 'sources: %s: ' % source['name'])

                source['filename'] = os.path.join(directory, source['src'])
                if not os.path.isfile(source['filename']):
                    raise PackageIOError('Source file not found: '+source['filename'])

                source['package'] = package['name']
                self.sources[source['name']] = source

    def _validate_bounds(self, bounds, prefix=''):
        if len(bounds) != 2 or len(bounds[0]) != 2 or len(bounds[1]) != 2:
            raise PackageIOError(prefix+'Invalid bounds format.')
        if not all(isinstance(i, (float, int)) for i in sum(bounds, [])):
            raise PackageIOError(prefix+'All bounds coordinates have to be int or float.')
        if bounds[0][0] >= bounds[1][0] or bounds[0][1] >= bounds[1][1]:
            raise PackageIOError(prefix+'bounds: lower coordinate has to be first.')

    def update_to_db(self):
        from .models import MapPackage, MapLevel, MapSource
        print('Updating Map database…')

        # Add new Packages
        packages = {}
        print('- Updating packages…')
        for name, package in self.packages.items():
            bounds = package.get('bounds')
            defaults = {
                'bottom': bounds[0][0],
                'left': bounds[0][1],
                'top': bounds[1][0],
                'right': bounds[1][1],
            } if bounds else {}

            package, created = MapPackage.objects.update_or_create(name=name, defaults=defaults)
            packages[name] = package
            if created:
                print('- Created package: '+name)

        # Add new levels
        print('- Updating levels…')
        for name, level in self.levels.items():
            package, created = MapLevel.objects.update_or_create(name=name, defaults={
                'package': packages[level['package']],
                'altitude': level['altitude'],
                'name': level['name'],
            })
            if created:
                print('- Created level: '+name)

        # Add new map sources
        print('- Updating sources…')
        for name, source in self.sources.items():
            source, created = MapSource.objects.update_or_create(name=name, defaults={
                'package': packages[source['package']],
                'image': File(open(source['filename'], 'rb')),
                'bottom': source['bounds'][0][0],
                'left': source['bounds'][0][1],
                'top': source['bounds'][1][0],
                'right': source['bounds'][1][1],
            })
            if created:
                print('- Created source: '+name)

        # Remove old sources
        for source in MapSource.objects.exclude(name__in=self.sources.keys()):
            print('- Deleted source: '+source.name)
            source.delete()

        # Remove old levels
        for level in MapLevel.objects.exclude(name__in=self.levels.keys()):
            print('- Deleted level: '+level.name)
            level.delete()

        # Remove old packages
        for package in MapPackage.objects.exclude(name__in=self.packages.keys()):
            print('- Deleted package: '+package.name)
            package.delete()
