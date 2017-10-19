from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'rebuild level geometries'

    def handle(self, *args, **options):
        from c3nav.mapdata.render.base import LevelGeometries
        LevelGeometries.rebuild()
