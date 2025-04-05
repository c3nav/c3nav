import os
import subprocess
from contextlib import suppress
from pathlib import Path

import c3nav.djangofixes  # noqa


def _get_version():
    # first check for the environment variable that is set inside docker containers we build
    if version := os.environ.get('C3NAV_VERSION', None):
        return version.strip()

    # alternatively check if there is a `.version` file at the root of the c3nav module
    version_file = Path(__file__).resolve().parent / '.version'
    with suppress(FileNotFoundError):
        if version := version_file.read_text().strip():
            return version

    # last check if this a checkout of c3nav git repo and get the current HEAD
    if (Path(__file__).resolve().parent.parent.parent / '.git').exists():
        with suppress(FileNotFoundError, subprocess.SubprocessError):
            run = subprocess.run(['git', 'rev-parse', 'HEAD'], capture_output=True, encoding='utf-8')
            if run.returncode == 0:
                return run.stdout.strip()

    # if everything fails return None
    return None


__version__ = _get_version()
