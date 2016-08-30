import sys

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from ...packageio import read_packages


class Command(BaseCommand):
    help = 'Load the map package files into the database'

    def add_arguments(self, parser):
        parser.add_argument('--yes', '-y', action='store_const', const=True, default=False,
                            help='don\'t ask for confirmation')

    def handle(self, *args, **options):
        with transaction.atomic():
            read_packages()
            print()
            if not options['yes'] and input('Confirm (y/N): ') != 'y':
                raise CommandError('Aborted.')
