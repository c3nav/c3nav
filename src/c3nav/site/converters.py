from collections import namedtuple


class LocationConverter:
    regex = '[a-zA-Z0-9-_.:]+'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


class CoordinatesConverter:
    regex = r'[a-z0-9-_.]+:-?\d+(\.\d+)?:-?\d+(\.\d+)?'

    def to_python(self, value):
        return value

    def to_url(self, value):
        return value


AtPos = namedtuple('AtPos', ('level', 'x', 'y', 'zoom'))


class AtPositionConverter:
    regex = r'(@[a-z0-9-_.]+,-?\d+(\.\d+)?,-?\d+(\.\d+)?,-?\d+(\.\d+)?)?'

    def to_python(self, value):
        if not value:
            return None
        value = AtPos(*value.split(','))
        return AtPos(value.level[1:], float(value.x), float(value.y), float(value.zoom))

    def to_url(self, value):
        return '@' + ','.join(str(s) for s in value)


class ConditionalConverter:
    # noinspection PyMethodOverriding
    def __init_subclass__(cls, /, name):
        cls.path = '%s/' % name
        cls.regex = '(%s/)?' % name

    def to_python(self, value):
        return value != ''

    def to_url(self, value):
        return self.path if value else ''


class IsEmbedConverter(ConditionalConverter, name='embed'):
    pass
