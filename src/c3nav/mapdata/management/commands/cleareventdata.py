import logging

from django.core import management
from django.core.management import BaseCommand
from django.db import transaction

from c3nav.mapdata.management.commands import clearmapcache


class Command(BaseCommand):
    help = 'Wipes users, changesets and mapupdates to reset a instance'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_true', help='really delete it')
        parser.add_argument('--wifi-measurements', action='store_true', help='delete wifi measurements')

    def handle(self, *args, **options):
        from django.contrib.auth import get_user_model

        from c3nav.control.models import UserPermissions
        from c3nav.editor.models import ChangeSet
        from c3nav.mapdata.models import MapUpdate
        from c3nav.mapdata.models.access import AccessPermissionToken
        from c3nav.mapdata.models.geometry.space import WifiMeasurement
        from c3nav.site.models import Announcement

        logger = logging.getLogger('c3nav')

        if not options['yes']:
            print("please add --yes to confirm that you really want to delete all users, changesets, and mapupdates")
            return

        with transaction.atomic():
            ChangeSet.objects.all().delete()
            logger.info('Deleted all ChangeSets')

            MapUpdate.objects.all().delete()
            logger.info('Deleted all MapUpdates')

            AccessPermissionToken.objects.all().delete()
            logger.info('Deleted all AccessPermissionTokens')

            Announcement.objects.filter(author__is_superuser=False).delete()
            logger.info('Deleted all Announcements nor attached to a super user')

            UserPermissions.objects.filter(user__is_superuser=False).delete()
            logger.info('Deleted all UserPermissions not attached to a super user')

            if options['wifi_measurements']:
                WifiMeasurement.objects.all().delete()
                logger.info('Deleted all WifiMeasurements')

            get_user_model().objects.filter(is_superuser=False).delete()
            logger.info('Deleted all Users who are not a super user')

        management.call_command(clearmapcache.Command(), include_history=True, include_geometries=True)
