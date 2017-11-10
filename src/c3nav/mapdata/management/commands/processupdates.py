from django.core.management.base import BaseCommand
from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.mapdata.models import MapUpdate


class Command(BaseCommand):
    help = 'process unprocessed map updates'

    def handle(self, *args, **options):
        updates = MapUpdate.process_updates()

        print()
        print(ungettext_lazy('%d map update processed.', '%d map updates processed.', len(updates)) % len(updates))

        if updates:
            print(_('Last processed update: %(date)s (#%(id)d)') % {
                'date': date_format(updates[-1].datetime, 'DATETIME_FORMAT'),
                'id': updates[-1].pk,
            })
