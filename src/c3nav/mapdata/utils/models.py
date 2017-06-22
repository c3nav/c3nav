import typing
from itertools import chain

from django.db import models

_submodels_by_model = {}


def get_submodels(model: typing.Type[models.Model]) -> typing.List[typing.Type[models.Model]]:
    """
    Get non-abstract submodels for a model including the model itself.
    Result is cached.
    """
    try:
        return _submodels_by_model[model]
    except KeyError:
        pass
    all_models = model.__subclasses__()
    result = []
    if not model._meta.abstract:
        result.append(model)
    result.extend(chain(*(get_submodels(model) for model in all_models)))
    _submodels_by_model[model] = result
    return result
