from pathlib import Path
from tempfile import TemporaryDirectory

from django.test.utils import override_settings


class override_path_settings(override_settings):
    def __init__(self):
        super().__init__()

    def enable(self):
        self.tmpdir = TemporaryDirectory(prefix="c3nav_test_data_")
        self.options: dict = {
            "RENDER_ROOT": Path(self.tmpdir.name) / 'render',
            "TILES_ROOT": Path(self.tmpdir.name) / 'tiles',
            "CACHE_ROOT": Path(self.tmpdir.name) / 'cache',
            "STATS_ROOT": Path(self.tmpdir.name) / 'stats',
            "PREVIEWS_ROOT": Path(self.tmpdir.name) / 'previews',
        }
        super().enable()

    def disable(self):
        super().disable()
        self.tmpdir.cleanup()