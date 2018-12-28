import argparse
import json

import dateutil
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.cache.stats import convert_stats


class Command(BaseCommand):
    help = 'convert stats file'

    def add_arguments(self, parser):
        parser.add_argument('statsfile', type=argparse.FileType('r'), help=_('stats file to convert'))
        parser.add_argument('--graphite', action='store_const', const=True, default=False,
                            help=_('graphite format'))

    def _output_graphite(self, prefix, result, timestamp):
        for name, value in result.items():
            if isinstance(value, dict):
                self._output_graphite(prefix+name+'.', value, timestamp)
                continue
            print('%s%s %s %s' % (prefix, name, value, timestamp))

    def handle(self, *args, **options):
        data = json.load(options['statsfile'])
        end_time = int(dateutil.parser.parse(data['end_date']).timestamp())
        result = convert_stats(data)
        if options['graphite']:
            self._output_graphite('c3nav.%s.' % settings.INSTANCE_NAME, result, end_time)
        else:
            print(json.dumps(result, indent=4))
