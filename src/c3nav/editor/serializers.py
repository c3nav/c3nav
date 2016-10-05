from rest_framework import serializers


class HosterSerializer(serializers.Serializer):
    name = serializers.CharField()
    base_url = serializers.CharField()
    packages = serializers.SerializerMethodField()

    def get_packages(self, obj):
        return tuple(obj.get_packages().values_list('name', flat=True))


class TaskSerializer(serializers.Serializer):
    id = serializers.CharField()
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
