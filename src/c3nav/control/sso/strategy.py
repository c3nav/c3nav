from social_core.utils import SETTING_PREFIX as SOCIAL_AUTH_SETTING_PREFIX
from social_django.strategy import DjangoStrategy

from django.conf import settings


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
