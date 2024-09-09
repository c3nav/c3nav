from django.conf import settings
from social_core.utils import SETTING_PREFIX as SOCIAL_AUTH_SETTING_PREFIX
from social_core.backends.utils import load_backends
from social_django.strategy import DjangoStrategy

_sso_services = None


def get_sso_services() -> dict[str, str]:
    global _sso_services
    from social_django.utils import load_strategy

    if _sso_services is None:
        _sso_services = dict()
        for backend in load_backends(load_strategy().get_backends()).values():
            _sso_services[backend.name] = getattr(backend, 'verbose_name', backend.name.replace('-', ' ').capitalize())

    return _sso_services


class C3navStrategy(DjangoStrategy):
    """A subclass of DjangoStrategy that uses our config parser in addition to django settings"""
    _list_keys = {'authentication_backends', 'pipeline'}

    def get_setting(self, name: str):
        config_name = name.removeprefix(SOCIAL_AUTH_SETTING_PREFIX + '_').lower()
        value = settings.C3NAV_CONFIG.get('sso', config_name,
                                          fallback=None)
        if value is not None:
            if config_name in self._list_keys:
                value = tuple(item.strip() for item in value.split(','))
        else:
            value = super().get_setting(name)
        return value
