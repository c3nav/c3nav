from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.translation import ugettext_lazy as _


class Command(BaseCommand):
    help = 'clear the mapdata cache'

    def handle(self, *args, **options):
        from c3nav.mapdata.models import MapUpdate
        MapUpdate.objects.create(type='management')

        if not settings.HAS_REAL_CACHE:
            print(_('You have no external cache configured, so don\'t forget to restart your c3nav instance!'))
