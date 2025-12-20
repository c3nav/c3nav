class SignedIntConverter:
    regex = r'-?\d+'

    def to_python(self, value):
        return int(value)

    def to_url(self, value):
        return str(value)


class AccessPermissionsConverter:
    regex = r'\d+(-\d+)*'

    def to_python(self, value):
        return set(int(i) for i in value.split('-'))

    def to_url(self, value):
        return '-'.join(str(i) for i in value)


class TileFileExtConverter:
    regex = '(png|webp)'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class HistoryModeConverter:
    regex = '(base|composite)'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class HistoryFileExtConverter:
    regex = '(png|json|data)'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class ArchiveFileExtConverter:
    regex = r'tar(\.(gz|xz|zst))?'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value
