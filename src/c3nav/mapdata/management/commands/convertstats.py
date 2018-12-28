import argparse
import json

from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _

from c3nav.mapdata.utils.cache.stats import convert_stats


class Command(BaseCommand):
    help = 'convert stats file'

    def add_arguments(self, parser):
        parser.add_argument('statsfile', type=argparse.FileType('r'), help=_('stats file to convert'))

    def handle(self, *args, **options):
        data = json.load(options['statsfile'])
        result = convert_stats(data)
        print(json.dumps(result, indent=4))
