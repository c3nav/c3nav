import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.models import AccessRestriction, Source
from c3nav.mapdata.render.engines import get_engine
from c3nav.mapdata.render.renderer import MapRenderer


class Command(BaseCommand):
    help = 'create a static archive of the instance'

    @staticmethod
    def permissions_value(value) -> set[int]:
        if value == '*':
            return AccessRestriction.get_all()
        if value == '0':
            return AccessRestriction.get_all_public()

        values = set(v for v in value.split(',') if v)
        permissions = set(permission.pk for permission in AccessRestriction.objects.all().filter(pk__in=values))

        not_found = values - set(map(str, permissions))
        if not_found:
            raise argparse.ArgumentTypeError(
                ngettext_lazy('Unknown access restriction: %s',
                              'Unknown access restrictions: %s', len(not_found)) % ', '.join(not_found)
            )

        return permissions

    @staticmethod
    def dir_path(value):
        path = Path(value)
        if not path.is_dir():
            raise argparse.ArgumentTypeError(f"{path} is not a directory")
        #for child in path.iterdir():
        #    raise argparse.ArgumentTypeError(f"{path} is not an empty")
        return path

    def add_arguments(self, parser):
        parser.add_argument('--permissions', default='0', type=self.permissions_value,
                            help=_('permissions, e.g. 2,3 or * for all permissions or 0 for public (default)'))
        parser.add_argument('--output-dir', default=None, type=self.dir_path,
                            help=_('override filename'))
        parser.add_argument('--include-png', default=False, type=bool, help=_('include png renders'))

    def handle(self, *args, permissions: set[int], output_dir: Path, include_png: bool = False, **kwargs):
        if output_dir is None:
            output_dir = Path(TemporaryDirectory(suffix="c3nav_static_archive_", delete=False).name)

        from c3nav.site.archive import static_archive as site_static_archive
        from c3nav.mapdata.archive import static_archive as mapdata_static_archive
        site_static_archive(output_dir=output_dir, permissions=permissions, png=include_png)
        mapdata_static_archive(output_dir=output_dir, permissions=permissions, png=include_png)
