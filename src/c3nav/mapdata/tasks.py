from django.utils.formats import date_format
from django.utils.translation import ugettext_lazy as _
from django.utils.translation import ungettext_lazy

from c3nav.celery import app


@app.task(rate_limit='1/m')
def process_map_updates():
    from c3nav.mapdata.models import MapUpdate
    updates = MapUpdate.process_updates()

    if updates:
        print()

    print(ungettext_lazy('%d map update processed.', '%d map updates processed.', len(updates)) % len(updates))

    if updates:
        print(_('Last processed update: %(date)s (#%(id)d)') % {
            'date': date_format(updates[-1].datetime, 'DATETIME_FORMAT'),
            'id': updates[-1].pk,
        })
