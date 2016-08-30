import sys

from django.core.management.base import BaseCommand, CommandError

from ...packageio import write_packages


class Command(BaseCommand):
    help = 'Dump the map database into the map package files'

    def add_arguments(self, parser):
        parser.add_argument('--no-prettify', dest='prettify', action='store_const', const=False, default=True,
                            help='dont\'t prettify existing files')
        parser.add_argument('--check-only', action='store_const', const=True, default=False,
                            help='check if there are files to update')

    def handle(self, *args, **options):
        count = write_packages(prettify=options['prettify'], check_only=options['check_only'])
        if options['check_only']:
            if count == 0:
                print('No errors found!')
            else:
                raise CommandError('Found errors in %s file(s)' % count)
        else:
            print('%s file(s) affected' % count)
