from collections import OrderedDict

from django.core import signing
from django.core.signing import BadSignature
from django.http import Http404
from rest_framework.decorators import detail_route
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.viewsets import ViewSet

from c3nav.editor.hosters import get_hoster_for_package, hosters
from c3nav.editor.serializers import HosterSerializer, TaskSerializer
from c3nav.editor.tasks import submit_edit_task
from c3nav.mapdata.models.package import Package


class HosterViewSet(ViewSet):
    """
    Get Package Hosters
    """
    def retrieve(self, request, pk=None):
        if pk not in hosters:
            raise Http404
        serializer = HosterSerializer(hosters[pk])
        return Response(serializer.data)

    @detail_route(methods=['get'])
    def state(self, request, pk=None):
        if pk not in hosters:
            raise Http404

        hoster = hosters[pk]
        state = hoster.get_state(request)
        error = hoster.get_error(request) if state == 'logged_out' else None

        return Response(OrderedDict((
            ('state', state),
            ('error', error),
        )))

    @detail_route(methods=['post'])
    def auth_uri(self, request, pk=None):
        if pk not in hosters:
            raise Http404
        return Response({
            'auth_uri': hosters[pk].get_auth_uri(request)
        })

    @detail_route(methods=['post'])
    def submit(self, request, pk=None):
        if pk not in hosters:
            raise Http404
        hoster = hosters[pk]

        if 'data' not in request.POST:
            raise ValidationError('Missing POST parameter: data')

        if 'commit_msg' not in request.POST:
            raise ValidationError('Missing POST parameter: commit_msg')

        data = request.POST['data']
        commit_msg = request.POST['commit_msg'].strip()

        if not commit_msg:
            raise ValidationError('POST parameter may not be empty: commit_msg')

        try:
            data = signing.loads(data)
        except BadSignature:
            raise ValidationError('Bad data signature.')

        if data['type'] != 'editor.edit':
            raise ValidationError('Wrong data type.')

        package = Package.objects.filter(name=data['package_name']).first()
        data_hoster = None
        if package is not None:
            data_hoster = get_hoster_for_package(package)

        if hoster != data_hoster:
            raise ValidationError('Wrong hoster.')

        data['commit_msg'] = commit_msg

        task = hoster.submit_edit(request, data)

        serializer = TaskSerializer(task)
        return Response(serializer.data)


class SubmitTaskViewSet(ViewSet):
    """
    Get Submit Tasks
    """
    def retrieve(self, request, pk=None):
        task = submit_edit_task.AsyncResult(task_id=pk)
        try:
            task.ready()
        except:
            raise Http404

        serializer = TaskSerializer(task)
        return Response(serializer.data)
