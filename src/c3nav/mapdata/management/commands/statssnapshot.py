import json
import os
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.cache.stats import stats_snapshot


class Command(BaseCommand):
    help = 'get stats snapshot'

    def add_arguments(self, parser):
        parser.add_argument('--reset', action='store_const', const=True, default=False,
                            help=_('reset the values'))
        parser.add_argument('--save', action='store_const', const=True, default=False,
                            help=_('save result to the stats directory'))

    def handle(self, *args, **options):
        result = stats_snapshot(reset=options['reset'])
        if options['save']:
            filename = os.path.join(settings.STATS_ROOT,
                                    'stats_%s_%s.json' % (result['start_date'], result['end_date']))
            json.dump(result, open(filename, 'w'), indent=4)
            print('saved to %s' % filename)
        else:
            print(json.dumps(result, indent=4))
