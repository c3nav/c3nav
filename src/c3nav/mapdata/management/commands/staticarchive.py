import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

from django.core.management.base import BaseCommand
from django.utils.translation import gettext_lazy as _
from django.utils.translation import ngettext_lazy

from c3nav.mapdata.models import AccessRestriction

SERVER_CODE = """
import http.server
import socketserver

from http import HTTPStatus

PORT = 8000

class StaticArchiveHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def send_error(self, code, message=None, explain=None):
        if code == 404:
            if self.path.startswith("/map/") and (self.path.endswith(".webp") or self.path.endswith(".png")):
                self.send_response(HTTPStatus.SEE_OTHER)
                self.send_header("Location", f"/map/blank/{self.path.split('/')[-1]}")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

            target = redirects.get(self.path if self.path.endswith("/") else f"{self.path}/", None)
            if target:
                self.send_response(HTTPStatus.FOUND)
                self.send_header("Location", target)
                self.send_header("Content-Length", "0")
                self.end_headers()
                return

        return super().send_error(code, message, explain)

    def translate_path(self, path):
        if path.startswith('/o/') or path.startswith('/d/'):
            path = f"/l/{path[3:]}"
        elif path.startswith('/r/'):
            split = path[3:].split("/")
            if len(split) > 3:
                path = f"/l/{split[3]}"
        result = super().translate_path(path).split("@")[0]
        if result.endswith("/details/"):
            result = result.removesuffix('details/')
        return result


with socketserver.TCPServer(("", PORT), StaticArchiveHTTPRequestHandler) as httpd:
    print("serving at port", PORT)
    httpd.serve_forever()
    
    {"logged_in":false,"allow_editor":false,"allow_control_panel":false,"mesh_control":false,"has_positions":false,"title":"Archive","subtitle":null,"permissions":[],"overlays":[],"quests":{}}
"""


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

        redirects = {}

        site_static_archive(output_dir=output_dir, permissions=permissions, redirects=redirects, png=include_png)
        mapdata_static_archive(output_dir=output_dir, permissions=permissions, redirects=redirects, png=include_png)

        redirects = {f"/{from_path}/": f"/{to_path}/" for from_path, to_path in redirects.items()}

        with (output_dir / "server.py").open("w") as f:
            f.write(SERVER_CODE)
            f.write(f"\n\nredirects = {json.dumps(redirects, indent=4, sort_keys=True)}\n\n")

