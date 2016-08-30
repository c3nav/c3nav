import os
import tempfile

from django.core.management import call_command
from django.core.management.base import BaseCommand
from django.db import connections, router


class Command(BaseCommand):
    help = 'Check if there are errors in the map package files'

    def add_arguments(self, parser):
        parser.add_argument('--no-prettify', dest='prettify', action='store_const', const=False, default=True,
                            help='ignore formatting errors')

    def handle(self, *args, **options):
        print('Creating temporary database for checking…\n')

        _, tmp = tempfile.mkstemp(suffix='.sqlite3', prefix='c3nav-checkmap-')
        connections.databases['tmpdb'] = {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': tmp,
        }

        # This is not nice, but the easiest way
        def tmpdb(*args, **kwargs):
            return 'tmpdb'
        router.db_for_read = tmpdb
        router.db_for_write = tmpdb

        try:
            call_command('migrate', database='tmpdb')
            call_command('loadmap', yes=True)
            call_command('dumpmap', prettify=options['prettify'], check_only=True)
        finally:
            os.remove(tmp)
