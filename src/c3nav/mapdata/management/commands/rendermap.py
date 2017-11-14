import argparse
import os

from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.models import AccessRestriction, Level, Source
from c3nav.mapdata.render import MapRenderer
from c3nav.mapdata.render.engines import get_engine, get_engine_filetypes


class Command(BaseCommand):
    help = 'render the map'

    @staticmethod
    def levels_value(value):
        if value == '*':
            return Level.objects.filter(on_top_of__isnull=True)

        values = set(v for v in value.split(',') if v)
        levels = Level.objects.filter(on_top_of__isnull=True, short_label__in=values)

        not_found = values - set(level.short_label for level in levels)
        if not_found:
            raise argparse.ArgumentTypeError(
                ungettext_lazy('Unknown level: %s', 'Unknown levels: %s', len(not_found)) % ', '.join(not_found)
            )

        return levels

    @staticmethod
    def permissions_value(value):
        if value == '*':
            return AccessRestriction.objects.all()
        if value == '0':
            return ()

        values = set(v for v in value.split(',') if v)
        permissions = AccessRestriction.objects.all().filter(pk__in=values)

        not_found = values - set(str(permission.pk) for permission in permissions)
        if not_found:
            raise argparse.ArgumentTypeError(
                ungettext_lazy('Unknown access restriction: %s',
                               'Unknown access restrictions: %s', len(not_found)) % ', '.join(not_found)
            )

        return permissions

    def add_arguments(self, parser):
        parser.add_argument('filetype', type=str, choices=get_engine_filetypes(),
                            help=_('filetype to render'))
        parser.add_argument('--levels', default='*', type=self.levels_value,
                            help=_('levels to render, e.g. 0,1,2 or * for all levels (default)'))
        parser.add_argument('--permissions', default='0', type=self.permissions_value,
                            help=_('permissions, e.g. 2,3 or * for all permissions or 0 for none (default)'))
        parser.add_argument('--full-levels', action='store_const', const=True, default=False,
                            help=_('render all levels completely'))
        parser.add_argument('--no-center', action='store_const', const=True, default=False,
                            help=_('do not center the output'))

    def handle(self, *args, **options):
        (minx, miny), (maxx, maxy) = Source.max_bounds()
        for level in options['levels']:
            renderer = MapRenderer(level.pk, minx, miny, maxx, maxy, access_permissions=options['permissions'],
                                   full_levels=options['full_levels'])

            filename = os.path.join(settings.RENDER_ROOT,
                                    'level_%s_%s.%s' % (level.short_label,
                                                        renderer.access_cache_key.replace('_', '-'),
                                                        options['filetype']))

            render = renderer.render(get_engine(options['filetype']), center=not options['no_center'])
            data = render.render(filename)
            if isinstance(data, tuple):
                other_data = data[1:]
                data = data[0]
            else:
                other_data = ()

            open(filename, 'wb').write(data)
            for filename, data in other_data:
                open(filename, 'wb').write(data)
