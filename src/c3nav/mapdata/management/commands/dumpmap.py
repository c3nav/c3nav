from django.core.management.base import BaseCommand
from django.db import transaction

from ...packageio import write_packages


class Command(BaseCommand):
    help = 'Dump the map database'

    def add_arguments(self, parser):
        parser.add_argument('--no-prettify', dest='prettify', action='store_const', const=False, default=True,
                            help='dont\'t prettify existing files')

    def handle(self, *args, **options):
        with transaction.atomic():
            write_packages(prettify=options['prettify'])
            print()
