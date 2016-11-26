from django.core.management.base import BaseCommand

from c3nav.mapdata.render import render_all_levels


class Command(BaseCommand):
    help = 'render the map'

    def handle(self, *args, **options):
        render_all_levels()
