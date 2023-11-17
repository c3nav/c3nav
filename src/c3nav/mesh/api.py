import hashlib
import json

from django.db import transaction
from rest_framework.authentication import SessionAuthentication
from rest_framework.exceptions import ParseError, PermissionDenied
from rest_framework.mixins import CreateModelMixin
from rest_framework.response import Response
from rest_framework.status import HTTP_201_CREATED
from rest_framework.viewsets import ReadOnlyModelViewSet

from c3nav.control.models import UserPermissions
from c3nav.mesh.dataformats import ChipType
from c3nav.mesh.models import FirmwareVersion


class FirmwareViewSet(CreateModelMixin, ReadOnlyModelViewSet):
    """
    List and download firmwares, ordered by last update descending. Use ?offset= to specify an offset.
    Don't forget to set X-Csrftoken for POST requests!
    """
    queryset = FirmwareVersion.objects.all()

    def get_queryset(self):
        # todo: permissions
        return FirmwareVersion.objects.all()

    def _list(self, request, qs):
        offset = 0
        if 'offset' in request.GET:
            if not request.GET['offset'].isdigit():
                raise ParseError('offset has to be a positive integer.')
            offset = int(request.GET['offset'])
        return Response([obj.serialize() for obj in qs.order_by('-created')[offset:offset+20]])

    def list(self, request, *args, **kwargs):
        return self._list(request, self.get_queryset())

    def create(self, request, *args, **kwargs):

        # todo: this should probably be tested
        if not isinstance(request._auth, UserPermissions):
            # check only for not-secret auth
            SessionAuthentication().enforce_csrf(request)

        if not request.user.is_superuser:
            # todo: make this proper
            raise PermissionDenied()

        # todo: permissions
        try:
            with transaction.atomic():
                version_data = json.loads(request.data["version"])

                version = FirmwareVersion.objects.create(
                    project_name=version_data["project_name"],
                    version=version_data["version"],
                    idf_version=version_data["idf_version"],
                    uploader=request.user,
                )

                for variant, build_data in version_data["builds"].items():
                    bin_file = request.data[f"build_{variant}"]

                    if bin_file.size > 4*1024*1024:
                        raise ValueError  # todo: better error

                    h = hashlib.sha256()
                    h.update(bin_file.open('rb').read())
                    sha256_bin_file = h.hexdigest()

                    if sha256_bin_file != build_data["sha256_hash"]:
                        raise ValueError

                    build = version.builds.create(
                        variant=variant,
                        chip=[chiptype.value for chiptype in ChipType
                              if chiptype.name.replace('_', '').lower() == build_data["chip"]][0],
                        sha256_hash=sha256_bin_file,
                        project_description=build_data["project_description"],
                        binary=bin_file,
                    )

                    for board in build_data["boards"]:
                        build.firmwarebuildboard_set.create(board=board)

        except:  # noqa
            raise  # todo: better error handling

        return Response(version.serialize(), status=HTTP_201_CREATED)
