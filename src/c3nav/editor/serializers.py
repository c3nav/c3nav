from rest_framework import serializers


class HosterSerializer(serializers.Serializer):
    name = serializers.CharField()
    base_url = serializers.CharField()
    packages = serializers.SerializerMethodField()
    signed_in = serializers.SerializerMethodField()

    def get_packages(self, obj):
        return tuple(obj.get_packages().values_list('name', flat=True))

    def get_signed_in(self, obj):
        return obj.is_access_granted(self.context['request']) if 'request' in self.context else None
