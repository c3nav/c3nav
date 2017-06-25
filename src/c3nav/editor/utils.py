from typing import Union

from django.db import models


def is_created_pk(pk):
    return isinstance(pk, str) and pk.startswith('c') and pk[1:].isnumeric()


def get_current_obj(model, pk, only_field=None):
    if is_created_pk(pk):
        return model()
    if only_field is not None:
        return model.objects.only(only_field).get(pk=pk)
    return model.objects.get(pk=pk)


def get_field_value(obj, field: Union[str, models.Field]):
    if isinstance(field, str):
        name = field
        model = type(obj)
        field = model._meta.get_field('titles' if name.startswith('title_') else name)
    else:
        name = field.name
    try:
        current_value = getattr(obj, field.attname)
    except AttributeError:
        current_value = field.to_prep_value(getattr(obj, field.name))
    if name.startswith('title_'):
        current_value = current_value.get(name[6:], '')
    return current_value
