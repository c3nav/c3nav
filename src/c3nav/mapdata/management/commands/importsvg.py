import argparse
import logging
import re
from xml.etree import ElementTree

from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext_lazy as _
from shapely.affinity import scale, translate
from shapely.geometry import Polygon

from c3nav.mapdata.models import Area, MapUpdate, Obstacle, Space
from c3nav.mapdata.utils.cache.changes import changed_geometries


class Command(BaseCommand):
    help = 'import svg file'

    @staticmethod
    def space_value(value):
        try:
            space = Space.objects.get(pk=value)
        except Space.DoesNotExist:
            raise argparse.ArgumentTypeError(
                _('unknown space')
            )
        return space

    def add_arguments(self, parser):
        parser.add_argument('svgfile', type=argparse.FileType('r'), help=_('svg file to import'))
        parser.add_argument('name', type=str, help=_('name of the import'))
        parser.add_argument('--type', type=str, required=True, choices=('areas', 'obstacles'),
                            help=_('type of objects to create'))
        parser.add_argument('--space', type=self.space_value, required=True,
                            help=_('space to add the objects to'))
        parser.add_argument('--minx', type=float, required=True,
                            help=_('minimum x coordinate, everthing left of it will be cropped'))
        parser.add_argument('--miny', type=float, required=True,
                            help=_('minimum y coordinate, everthing below it will be cropped'))
        parser.add_argument('--maxx', type=float, required=True,
                            help=_('maximum x coordinate, everthing right of it will be cropped'))
        parser.add_argument('--maxy', type=float, required=True,
                            help=_('maximum y coordinate, everthing above it will be cropped'))

    @staticmethod
    def parse_svg_data(data):
        first = False

        last_point = (0, 0)
        last_end_point = None

        done_subpaths = []
        current_subpath = []
        while data:
            data = data.lstrip().replace(',', ' ')
            command = data[0]
            if first and command not in 'Mm':
                raise ValueError('path data has to start with moveto command.')
            data = data[1:].lstrip()
            first = False

            numbers = []
            while True:
                match = re.match(r'^-?[0-9]+(\.[0-9]+)?(e-?[0-9]+)?', data)
                if match is None:
                    break
                numbers.append(float(match.group(0)))
                data = data[len(match.group(0)):].lstrip()

            relative = command.islower()
            if command in 'Mm':
                if not len(numbers) or len(numbers) % 2:
                    raise ValueError('Invalid number of arguments for moveto command!')
                numbers = iter(numbers)
                first = True
                for x, y in zip(numbers, numbers):
                    if relative:
                        x, y = last_point[0] + x, last_point[1] + y
                    if first:
                        first = False
                        if current_subpath:
                            done_subpaths.append(current_subpath)
                            last_end_point = current_subpath[-1]
                            current_subpath = []
                    current_subpath.append((x, y))
                    last_point = (x, y)

            elif command in 'Ll':
                if not len(numbers) or len(numbers) % 2:
                    raise ValueError('Invalid number of arguments for lineto command!')
                numbers = iter(numbers)
                for x, y in zip(numbers, numbers):
                    if relative:
                        x, y = last_point[0] + x, last_point[1] + y
                    if not current_subpath:
                        current_subpath.append(last_end_point)
                    current_subpath.append((x, y))
                    last_point = (x, y)

            elif command in 'Hh':
                if not len(numbers):
                    raise ValueError('Invalid number of arguments for horizontal lineto command!')
                y = last_point[1]
                for x in numbers:
                    if relative:
                        x = last_point[0] + x
                    if not current_subpath:
                        current_subpath.append(last_end_point)
                    current_subpath.append((x, y))
                    last_point = (x, y)

            elif command in 'Vv':
                if not len(numbers):
                    raise ValueError('Invalid number of arguments for vertical lineto command!')
                x = last_point[0]
                for y in numbers:
                    if relative:
                        y = last_point[1] + y
                    if not current_subpath:
                        current_subpath.append(last_end_point)
                    current_subpath.append((x, y))
                    last_point = (x, y)

            elif command in 'Zz':
                if numbers:
                    raise ValueError('Invalid number of arguments for closepath command!')
                current_subpath.append(current_subpath[0])
                done_subpaths.append(current_subpath)
                last_end_point = current_subpath[-1]
                current_subpath = []

            else:
                raise ValueError('unknown svg command: ' + command)

        if current_subpath:
            done_subpaths.append(current_subpath)
        return done_subpaths

    def handle(self, *args, **options):
        minx = options['minx']
        miny = options['miny']
        maxx = options['maxx']
        maxy = options['maxy']

        if minx >= maxx:
            raise CommandError(_('minx has to be lower than maxx'))
        if miny >= maxy:
            raise CommandError(_('miny has to be lower than maxy'))

        width = maxx-minx
        height = maxy-miny

        model = {'areas': Area, 'obstacles': Obstacle}[options['type']]

        namespaces = {'svg': 'http://www.w3.org/2000/svg'}

        svg = ElementTree.fromstring(options['svgfile'].read())
        svg_width = float(svg.attrib['width'])
        svg_height = float(svg.attrib['height'])
        svg_viewbox = svg.attrib.get('viewBox')

        if svg_viewbox:
            offset_x, offset_y, svg_width, svg_height = [float(i) for i in svg_viewbox.split(' ')]
        else:
            offset_x, offset_y = 0, 0

        for element in svg.findall('.//svg:clipPath/..', namespaces):
            for clippath in element.findall('./svg:clipPath', namespaces):
                element.remove(clippath)

        for element in svg.findall('.//svg:symbol/..', namespaces):
            for clippath in element.findall('./svg:symbol', namespaces):
                element.remove(clippath)

        if svg.findall('.//*[@transform]'):
            raise CommandError(_('svg contains transform attributes. Use inkscape apply transforms.'))

        if model.objects.filter(space=options['space'], import_tag=options['name']).exists():
            raise CommandError(_('objects with this import tag already exist in this space.'))

        with MapUpdate.creation_lock():
            changed_geometries.reset()
            for path in svg.findall('.//svg:path', namespaces):
                for polygon in self.parse_svg_data(path.attrib['d']):
                    if len(polygon) < 3:
                        continue
                    polygon = Polygon(polygon).buffer(0)
                    polygon = translate(polygon, xoff=-offset_x, yoff=-offset_y)
                    polygon = scale(polygon, xfact=1, yfact=-1, origin=(0, svg_height/2))
                    polygon = scale(polygon, xfact=width / svg_width, yfact=height / svg_height, origin=(0, 0))
                    polygon = translate(polygon, xoff=minx, yoff=miny)
                    obj = model(geometry=polygon, space=options['space'], import_tag=options['name'])
                    obj.save()
            MapUpdate.objects.create(type='importsvg')

        logger = logging.getLogger('c3nav')
        logger.info('Imported, map update created.')
        logger.info('Next step: go into the shell and edit them using '
                    '%s.objects.filter(space_id=%r, import_tag=%r)' %
                    (model.__name__, options['space'].pk, options['name']))
