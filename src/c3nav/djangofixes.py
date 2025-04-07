from types import GenericAlias

from django.db.migrations.serializer import Serializer, TypeSerializer, IterableSerializer
from collections.abc import Iterable


"""
Give django migrations the ability to serialize GenericAlias. 
Since python3.11 it no longer is an instance of type, so TypeSerializer isn't used.
It is also iterable, which is why we need to move the IterableSerializer to the end. 
"""
Serializer.unregister(Iterable)
Serializer.register(GenericAlias, TypeSerializer)
Serializer.register(Iterable, IterableSerializer)