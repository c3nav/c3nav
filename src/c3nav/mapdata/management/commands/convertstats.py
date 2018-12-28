import argparse
import json
import socket

import dateutil
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.cache.stats import convert_stats


class Command(BaseCommand):
    help = 'convert stats file'

    def add_arguments(self, parser):
        parser.add_argument('statsfile', type=argparse.FileType('r'), help=_('stats file to convert'))
        parser.add_argument('--graphite', type=str, help=_('graphite address'), default=None)
        parser.add_argument('--graphite-port', type=int, default=2003, help=_('graphite port (default 2003)'))

    def _output_graphite(self, s, prefix, result, timestamp):
        for name, value in result.items():
            if isinstance(value, dict):
                self._output_graphite(s, prefix+name+'.', value, timestamp)
                continue
            s.sendall(('%s%s %s %s\n' % (prefix, name, value, timestamp)).encode())

    def handle(self, *args, **options):
        data = json.load(options['statsfile'])
        end_time = int(dateutil.parser.parse(data['end_date']).timestamp())
        result = convert_stats(data)
        if options['graphite']:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect((options['graphite'], options['graphite_port']))
                self._output_graphite(s, 'c3nav.%s.' % settings.INSTANCE_NAME, result, end_time)
            finally:
                s.close()
        else:
            print(json.dumps(result, indent=4))
