from configparser import _UNSET, RawConfigParser

from c3nav.utils.environ import Env


class C3navConfigParser(RawConfigParser):
    env: Env

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

    def get(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET, env: bool | str = True) -> str:
        if env and (value := self.env.str(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        return super().get(section, option, raw=raw, vars=vars, fallback=fallback)

    def getint(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
               env: bool | str = True, **kwargs) -> int:
        if env and (value := self.env.int(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        return super().getint(section, option, raw=raw, vars=vars, fallback=fallback)

    def getfloat(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
                 env: bool | str = True, **kwargs) -> float:
        if env and (value := self.env.float(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        return super().getfloat(section, option, raw=raw, vars=vars, fallback=fallback)

    def getboolean(self, section: str, option: str, *, raw=False, vars=None, fallback=_UNSET,
                   env: bool | str = True, **kwargs) -> bool:
        if env and (value := self.env.bool(self.get_env_key(section, option, env), default=None)) is not None:
            return value
        return super().getboolean(section, option, raw=raw, vars=vars, fallback=fallback)
