from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...packageio import read_packages


class Command(BaseCommand):
    help = 'Update the map database'

    def add_arguments(self, parser):
        parser.add_argument('-y', action='store_const', const=True, default=False,
                            help='don\'t ask for confirmation')

    def handle(self, *args, **options):
        with transaction.atomic():
            read_packages()
            print()
            if input('Confirm (y/N): ') != 'y':
                raise CommandError('Aborted.')
