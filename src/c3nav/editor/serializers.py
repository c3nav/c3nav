from rest_framework import serializers
from rest_framework.reverse import reverse


class HosterSerializer(serializers.Serializer):
    name = serializers.CharField()
    url = serializers.HyperlinkedIdentityField(view_name='api:hoster-detail', lookup_field='name')
    state_url = serializers.SerializerMethodField()
    auth_uri_url = serializers.SerializerMethodField()
    submit_url = serializers.SerializerMethodField()
    base_url = serializers.CharField()

    def get_state_url(self, obj):
        return reverse('api:hoster-state', args=(obj.name, ), request=self.context.get('request'))

    def get_auth_uri_url(self, obj):
        return reverse('api:hoster-auth-uri', args=(obj.name, ), request=self.context.get('request'))

    def get_submit_url(self, obj):
        return reverse('api:hoster-submit', args=(obj.name, ), request=self.context.get('request'))


class TaskSerializer(serializers.Serializer):
    id = serializers.CharField()
    url = serializers.HyperlinkedIdentityField(view_name='api:hoster-detail', lookup_field='id')
    started = serializers.SerializerMethodField()
    done = serializers.SerializerMethodField()
    success = serializers.SerializerMethodField()
    result = serializers.SerializerMethodField()
    error = serializers.SerializerMethodField()

    def get_started(self, obj):
        return obj.status != 'PENDING'

    def get_done(self, obj):
        return obj.ready()

    def get_success(self, obj):
        return (obj.successful() and obj.result['success']) if obj.ready() else None

    def get_result(self, obj):
        return obj.result if obj.ready() and obj.successful() else None

    def get_error(self, obj):
        success = self.get_success(obj)
        if success is not False:
            return None
        return 'Internal Error' if not obj.successful() else obj.result['error']
