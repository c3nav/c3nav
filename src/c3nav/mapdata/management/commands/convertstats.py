import argparse
import json
import socket

import dateutil
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _

from c3nav.mapdata.permissions import active_map_permissions, ManualMapPermissions
from c3nav.mapdata.utils.cache.stats import convert_stats


class Command(BaseCommand):
    help = 'convert stats file'

    def add_arguments(self, parser):
        parser.add_argument('statsfile', type=argparse.FileType('r'), help=_('stats file to convert'))
        parser.add_argument('--graphite', type=str, help=_('graphite address'), default=None)
        parser.add_argument('--graphite-port', type=int, default=2003, help=_('graphite port (default 2003)'))

    def _output_graphite(self, lines, prefix, result, timestamp):
        for name, value in result.items():
            if isinstance(value, dict):
                self._output_graphite(lines, prefix+name+'.', value, timestamp)
                continue
            lines.append('%s%s %s %s' % (prefix, name, value, timestamp))

    def handle(self, *args, **options):
        data = json.load(options['statsfile'])
        end_time = int(dateutil.parser.parse(data['end_date']).timestamp())
        with active_map_permissions.override(ManualMapPermissions.get_full_access()):
            result = convert_stats(data)
        if options['graphite']:
            lines = []
            self._output_graphite(lines, 'c3nav.%s.' % settings.INSTANCE_NAME, result, end_time)
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            try:
                s.connect((options['graphite'], options['graphite_port']))
                message = '\n'.join(lines) + '\n'  # all lines must end in a newline
                print(message)
                s.sendall(message.encode())
            finally:
                s.close()
        else:
            print(json.dumps(result, indent=4))
