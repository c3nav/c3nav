from django.core.management.base import BaseCommand
from django.db import transaction

from c3nav.mapdata.models.geometry.base import GeometryMixin
from c3nav.mapdata.utils.models import get_submodels


class Command(BaseCommand):
    help = 'clean-up/fix all geometries in the database'

    def handle(self, *args, **options):
        with transaction.atomic():
            for model in get_submodels(GeometryMixin):
                for instance in model.objects.all():
                    old_geom = instance.geometry.wrapped_geojson
                    instance.save()
                    instance.refresh_from_db()
                    if instance.geometry.wrapped_geojson != old_geom:
                        print('Fixed %s' % instance)
