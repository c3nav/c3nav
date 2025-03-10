from django.core.exceptions import ObjectDoesNotExist


class LocationById:
    def __init__(self):
        super().__init__()
        self.name = None
        self.cached_id = None
        self.cached_value = None

    def __set_name__(self, owner, name):
        self.name = name

    def __get__(self, instance, owner=None):
        value_id = getattr(instance, self.name+'_id')
        if value_id is None:
            self.cached_pk = None
            self.cached_value = None
            return None

        if value_id == self.cached_id:
            return self.cached_value

        from c3nav.mapdata.utils.locations import get_location
        value = get_location(value_id)
        if value is None:
            raise ObjectDoesNotExist
        self.cached_id = value_id
        self.cached_value = value
        return value

    def __set__(self, instance, value):
        value_id = None if value is None else value.id
        self.cached_id = value_id
        self.cached_value = value
        setattr(instance, self.name+'_id', value_id)
