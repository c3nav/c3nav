from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'clear the mapdata cache'

    def handle(self, *args, **options):
        from c3nav.mapdata.models import MapUpdate
        MapUpdate.objects.create(type='management')
