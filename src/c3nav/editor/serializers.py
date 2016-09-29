from rest_framework import serializers


class HosterSerializer(serializers.Serializer):
    name = serializers.CharField()
    base_url = serializers.CharField()
    packages = serializers.SerializerMethodField()

    def get_packages(self, obj):
        return tuple(obj.get_packages().values_list('name', flat=True))
