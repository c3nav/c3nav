from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from ...packageio import MapPackagesIO


class Command(BaseCommand):
    help = 'Load the given map packages into the database'

    def add_arguments(self, parser):
        parser.add_argument('mappkgdir', nargs='+', type=str, help='map package directories')
        parser.add_argument('-y', action='store_const', const=True, default=False,
                            help='don\'t ask for confirmation')

    def handle(self, *args, **options):
        with transaction.atomic():
            MapPackagesIO(options['mappkgdir']).update_to_db()
            print()
            if input('Confirm (y/N): ') != 'y':
                raise CommandError('Aborted.')
