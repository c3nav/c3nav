from django.core.management.base import BaseCommand, CommandError

from ...packageio import MapdataWriter


class Command(BaseCommand):
    help = 'Dump the map database into the map package files'

    def add_arguments(self, parser):
        parser.add_argument('--yes', '-y', action='store_const', const=True, default=False,
                            help='don\'t ask for confirmation')
        parser.add_argument('--no-prettify', dest='prettify', action='store_const', const=False, default=True,
                            help='don\'t prettify existing files')
        parser.add_argument('--diff', action='store_const', const=True, default=False,
                            help='show changes as diff')
        parser.add_argument('--check-only', action='store_const', const=True, default=False,
                            help='check if there are files to update')

    def handle(self, *args, **options):
        writer = MapdataWriter()
        count = writer.prepare_write_packages(prettify=options['prettify'], diff=options['diff'])

        if options['check_only']:
            if count:
                raise CommandError('Check resulted in files to update.')
            print('Nothing to do.')
        else:
            if not count:
                print('Nothing to do.')
            else:
                if not options['yes'] and input('Confirm (y/N): ') != 'y':
                    raise CommandError('Aborted.')
                writer.do_write_packages()
