import typing as ty
from pathlib import Path

from environ import Env as BaseEnv


class Env(BaseEnv):

    def path(self, var, default=BaseEnv.NOTSET, parse_default=False) -> Path:
        return ty.cast(Path, self.get_value(var, cast=Path, default=default, parse_default=parse_default))
