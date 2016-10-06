from collections import Iterable

from django.db.models.manager import BaseManager
from rest_framework import serializers


class PkField(serializers.DictField):
    """
    give primary key
    """
    def to_representation(self, obj):
        if hasattr(obj, 'pk'):
            return obj.pk
        elif isinstance(obj, Iterable):
            return tuple(self.to_representation(elem) for elem in obj)
        elif isinstance(obj, BaseManager):
            return tuple(self.to_representation(elem) for elem in obj.all())
        return None


class RecursiveSerializerMixin(serializers.Serializer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        request = self.context.get('request')
        request_sparse = self.context['request_sparse'] = request is not None and request.GET.get('sparse')
        sparse = self.context['sparse'] = request_sparse or self.context.get('sparse')

        if sparse:
            for name in getattr(self.Meta, 'sparse_exclude', ()):
                value = self.fields.get(name)
                if value is not None and isinstance(value, serializers.Serializer):
                    self.fields[name] = PkField()

            if request_sparse:
                for name in tuple(self.fields):
                    if name == 'url' or name.endswith('_url'):
                        self.fields.pop(name)

    def sparse_context(self):
        return {'request': self.context.get('request'), 'sparse': True}

    def recursive_value(self, serializer, obj, *args, **kwargs):
        if self.context.get('sparse'):
            return PkField().to_representation(obj)
        return serializer(obj, *args, **kwargs, context=self.sparse_context()).data
