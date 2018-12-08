import logging

from django.core import management
from django.core.exceptions import ObjectDoesNotExist
from django.core.management import BaseCommand

from c3nav.mapdata.management.commands import clearmapcache


class Command(BaseCommand):
    help = 'Wipes users, changesets and mapupdates to reset a instance'

    def add_arguments(self, parser):
        parser.add_argument('--yes', action='store_const', const=True, default=False,
                            help='really delete it')

    def handle(self, *args, **options):
        from c3nav.control.models import UserPermissions
        from c3nav.mapdata.models import MapUpdate
        from c3nav.mapdata.models.access import AccessPermissionToken
        from c3nav.editor.models import ChangeSet, ChangeSetUpdate
        from c3nav.site.models import Announcement
        from django.contrib.auth import get_user_model

        logger = logging.getLogger('c3nav')

        if not options['yes']:
            print("please add --yes to confirm that you really want to delete all users, changesets, and mapupdates")
            return

        try:
            ChangeSet.objects.all().delete()
            logger.info('Deleted all ChangeSets')
        except ObjectDoesNotExist:
            pass
        try:
            # should not be necessary, but just to make sure
            ChangeSetUpdate.objects.all().delete()
            logger.info('Deleted all ChangeSetsUpdates')
        except ObjectDoesNotExist:
            pass
        try:
            MapUpdate.objects.all().delete()
            logger.info('Deleted all MapUpdates')
        except ObjectDoesNotExist:
            pass

        try:
            AccessPermissionToken.objects.all().delete()
            logger.info('Deleted all AccessPermissionTokens')
        except ObjectDoesNotExist:
            pass
        try:
            Announcement.objects.filter(author__is_superuser=False).delete()
            logger.info('Deleted all Announcements nor attached to a super user')
        except ObjectDoesNotExist:
            pass
        try:
            UserPermissions.objects.filter(user__is_superuser=False).delete()
            logger.info('Deleted all UserPermissions not attached to a super user')
        except ObjectDoesNotExist:
            pass

        try:
            get_user_model().objects.filter(is_superuser=False).delete()
            logger.info('Deleted all Users who are not a super user')
        except ObjectDoesNotExist:
            pass

        management.call_command(clearmapcache.Command(), include_history=True, include_geometries=True)
