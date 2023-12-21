import requests
from django.conf import settings
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'import from hub'

    def handle(self, *args, **options):
        r = requests.get(settings.HUB_API_BASE+"/integration/c3nav",
                         headers={"Authorization": "Token "+settings.HUB_API_SECRET})
        r.raise_for_status()
        from pprint import pprint
        pprint(r.json())