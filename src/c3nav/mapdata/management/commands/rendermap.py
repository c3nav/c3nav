from django.core.management.base import BaseCommand

from c3nav.mapdata.render import render_all_levels


class Command(BaseCommand):
    help = 'render the map'

    def add_arguments(self, parser):
        parser.add_argument('--show-accessibles', action='store_const', const=True, default=False,
                            help='highlight graph building areas (for debugging, but it looks nice, too)')

    def handle(self, *args, **options):
        render_all_levels(show_accessibles=options['show_accessibles'])
