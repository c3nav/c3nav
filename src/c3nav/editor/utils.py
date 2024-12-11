class DefaultEditUtils:
    def __init__(self, request):
        self.request = request

    @classmethod
    def from_obj(cls, obj, request):
        return cls(request)

    @property
    def can_access_child_base_mapdata(self):
        return self.request.user_permissions.can_access_base_mapdata

    @property
    def can_create(self):
        return self.can_access_child_base_mapdata

    @property
    def _geometry_url(self):
        return None

    @property
    def geometry_url(self):
        return self._geometry_url if self.can_access_child_base_mapdata else None


class LevelChildEditUtils(DefaultEditUtils):
    def __init__(self, level, request):
        super().__init__(request)
        self.level = level

    @classmethod
    def from_obj(cls, obj, request):
        return cls(obj.level, request)

    @property
    def _geometry_url(self):
        return '/api/v2/editor/geometries/level/' + str(self.level.primary_level_pk)  # todo: resolve correctly


class SpaceChildEditUtils(DefaultEditUtils):
    def __init__(self, space, request):
        super().__init__(request)
        self.space = space

    @classmethod
    def from_obj(cls, obj, request):
        return cls(obj.space, request)

    @property
    def can_access_child_base_mapdata(self):
        return (self.request.user_permissions.can_access_base_mapdata or
                self.space.base_mapdata_accessible or
                self.space.pk in self.request.user_space_accesses)

    @property
    def _geometry_url(self):
        return '/api/v2/editor/geometries/space/'+str(self.space.pk)  # todo: resolve correctly
