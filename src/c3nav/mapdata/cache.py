from django.db.models.signals import m2m_changed, post_delete

from c3nav.mapdata.utils.models import get_submodels


class GeometryChangeTracker:
    def __init__(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()

    def register(self, level_id, geometry):
        self._geometries_by_level.setdefault(level_id, []).append(geometry)

    def level_deleted(self, level_id):
        self._deleted_levels.add(level_id)

    def reset(self):
        self._geometries_by_level = {}
        self._deleted_levels = set()


changed_geometries = GeometryChangeTracker()


def geometry_deleted(sender, instance, **kwargs):
    instance.register_delete()


def locationgroup_changed(sender, instance, action, reverse, model, pk_set, using, **kwargs):
    if action not in ('post_add', 'post_remove', 'post_clear'):
        return

    if not reverse:
        instance.register_change(force=True)
    else:
        if action not in 'post_clear':
            raise NotImplementedError
        query = model.objects.filter(pk__in=pk_set)
        from c3nav.mapdata.models.geometry.space import SpaceGeometryMixin
        if issubclass(model, SpaceGeometryMixin):
            query = query.select_related('space')
        for obj in query:
            obj.register_change(force=True)


def register_signals():
    from c3nav.mapdata.models.geometry.base import GeometryMixin
    for model in get_submodels(GeometryMixin):
        post_delete.connect(geometry_deleted, sender=model)

    from c3nav.mapdata.models.locations import SpecificLocation
    for model in get_submodels(SpecificLocation):
        m2m_changed.connect(locationgroup_changed, sender=model.groups.through)
