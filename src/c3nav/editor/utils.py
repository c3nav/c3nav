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
    lang = None
    if isinstance(field, str):
        name = field
        model = type(obj)
        if '__i18n__' in name:
            orig_name, i18n, lang = name.split('__')
            field = model._meta.get_field(orig_name)
        else:
            field = model._meta.get_field(name)
    else:
        name = field.name
    try:
        current_value = getattr(obj, field.attname)
    except AttributeError:
        current_value = field.to_prep_value(getattr(obj, field.name))
    if lang:
        current_value = current_value.get(lang, '')
    return current_value
