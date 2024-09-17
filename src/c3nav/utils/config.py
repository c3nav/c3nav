import re
from configparser import _UNSET, NoOptionError, NoSectionError, RawConfigParser
from contextlib import contextmanager

from django.core.exceptions import ImproperlyConfigured

from c3nav.utils.environ import Env


class C3navConfigParser(RawConfigParser):
    env: Env
    LIST_PATTERN = re.compile(r"[;,]")

    def __init__(self, env: Env = None, **kwargs):
        if env is None:
            env = Env()
        self.env = env
        super().__init__(**kwargs)

    @property
    def parser(self) -> RawConfigParser:
        return super()

    @staticmethod
    def get_env_key(section: str, option: str, env: bool | str) -> str:
        if isinstance(env, str):
            return env
        key = section.upper() + '_' + option.upper()
        if not key.startswith('C3NAV_'):
            key = 'C3NAV_' + key
        return key

    @classmethod
    @contextmanager
    def _error_wrapper(cls, section: str, option: str, env: bool | str):
        try:
            yield
        except (NoOptionError, NoSectionError) as e:
            error_msg = f'Missing required setting {section} -> {option}'
            if env:
                error_msg += f' ({cls.get_env_key(section, option, env)} environment variable)'
            raise ImproperlyConfigured(error_msg) from e

    # for our error wrapper to work we need to make sure getint, getfloat, and getboolean call the original get method
    def _get(self, section, conv, option, **kwargs):
        return conv(super().get(section, option, **kwargs))

    def get(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET, env: bool | str = True) -> str:
        if env and (value := self.env.str(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        with self._error_wrapper(section, option, env):
            return super().get(section, option, raw=raw, vars=vars, fallback=fallback)

    def getint(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
               env: bool | str = True, **kwargs) -> int:
        if env and (value := self.env.int(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        with self._error_wrapper(section, option, env):
            return super().getint(section, option, raw=raw, vars=vars, fallback=fallback)

    def getfloat(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
                 env: bool | str = True, **kwargs) -> float:
        if env and (value := self.env.float(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        with self._error_wrapper(section, option, env):
            return super().getfloat(section, option, raw=raw, vars=vars, fallback=fallback)

    def getboolean(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
                   env: bool | str = True, **kwargs) -> bool:
        if env and (value := self.env.bool(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        with self._error_wrapper(section, option, env):
            return super().getboolean(section, option, raw=raw, vars=vars, fallback=fallback)

    def getlist(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
                   env: bool | str = True, **kwargs) -> tuple[str] | None:
        value = self.env.str(self.get_env_key(section, option, env), default=None) if env else None
        if value is None:
            with self._error_wrapper(section, option, env):
                value = super().get(section, option, raw=raw, vars=vars, fallback=fallback)
        return tuple(i.strip() for i in self.LIST_PATTERN.split(value) if i) if value is not None else value
