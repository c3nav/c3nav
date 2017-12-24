from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'create a site update, asking users to reload the page'

    def handle(self, *args, **options):
        result = input('Type YES to create a new site update: ')

        if result == 'YES':
            from c3nav.site.models import SiteUpdate
            SiteUpdate.objects.create()
            print('New site update created.')
        else:
            print('Aborted.')
