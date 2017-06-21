import typing
from itertools import chain

from django.utils.functional import cached_property

from c3nav.editor.forms import create_editor_form
from c3nav.editor.wrappers import BaseWrapper, ModelInstanceWrapper


class ModelWrapper(BaseWrapper):
    _allowed_callables = ('EditorForm',)
    _submodels_by_model = {}

    def __eq__(self, other):
        if type(other) == ModelWrapper:
            return self._obj is other._obj
        return self._obj is other

    @cached_property
    def EditorForm(self):
        return create_editor_form(self._obj)

    @classmethod
    def get_submodels(cls, model):
        try:
            return cls._submodels_by_model[model]
        except KeyError:
            pass
        all_models = model.__subclasses__()
        result = []
        if not model._meta.abstract:
            result.append(model)
        result.extend(chain(*(cls.get_submodels(model) for model in all_models)))
        cls._submodels_by_model[model] = result
        return result

    @cached_property
    def _submodels(self):
        return self.get_submodels(self._obj)

    def create_wrapped_model_class(self) -> typing.Type['ModelInstanceWrapper']:
        # noinspection PyTypeChecker
        return self.create_metaclass()(self._obj.__name__ + 'InstanceWrapper', (ModelInstanceWrapper,), {})

    def __call__(self, **kwargs):
        instance = self._wrap_instance(self._obj())
        for name, value in kwargs.items():
            setattr(instance, name, value)
        return instance

    def create_metaclass(self):
        parent = self

        class ModelInstanceWrapperMeta(type):
            _parent = parent

            def __getattr__(self, name):
                return getattr(parent, name)

            def __setattr__(self, name, value):
                setattr(parent, name, value)

            def __delattr__(self, name):
                delattr(parent, name)

        ModelInstanceWrapperMeta.__name__ = self._obj.__name__+'InstanceWrapperMeta'

        return ModelInstanceWrapperMeta

    def __repr__(self):
        return '<ModelWrapper '+repr(self._obj.__name__)+'>'
