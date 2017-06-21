from c3nav.editor.wrappers.query import BaseQueryWrapper


class ManagerWrapper(BaseQueryWrapper):
    def get_queryset(self):
        qs = self._wrap_queryset(self._obj.model.objects.all())
        return qs.exclude(pk__in=self._changeset.deleted_existing.get(self._obj.model, ()))


class RelatedManagerWrapper(ManagerWrapper):
    def _get_cache_name(self):
        return self._obj.field.related_query_name()

    def get_queryset(self):
        return super().get_queryset().filter(**self._obj.core_filters)

    def all(self):
        try:
            return self.instance._prefetched_objects_cache[self._get_cache_name()]
        except(AttributeError, KeyError):
            pass
        return super().all()

    def create(self, *args, **kwargs):
        if self.instance.pk is None:
            raise TypeError
        kwargs[self._obj.field.name] = self.instance
        super().create(*args, **kwargs)


class ManyRelatedManagerWrapper(RelatedManagerWrapper):
    def _check_through(self):
        if not self._obj.through._meta.auto_created:
            raise AttributeError('Cannot do this an a ManyToManyField which specifies an intermediary model.')

    def _get_cache_name(self):
        return self._obj.prefetch_cache_name

    def set(self, objs, author=None):
        if author is None:
            author = self._author

        old_ids = set(self.values_list('pk', flat=True))
        new_ids = set(obj.pk for obj in objs)

        self.remove(*(old_ids - new_ids), author=author)
        self.add(*(new_ids - old_ids), author=author)

    def add(self, *objs, author=None):
        if author is None:
            author = self._author

        for obj in objs:
            pk = (obj.pk if isinstance(obj, self._obj.model) else obj)
            self._changeset.add_m2m_add(self._obj.instance, name=self._get_cache_name(), value=pk, author=author)

    def remove(self, *objs, author=None):
        if author is None:
            author = self._author

        for obj in objs:
            pk = (obj.pk if isinstance(obj, self._obj.model) else obj)
            self._changeset.add_m2m_remove(self._obj.instance, name=self._get_cache_name(), value=pk, author=author)

    def all(self):
        try:
            return self.instance._prefetched_objects_cache[self._get_cache_name()]
        except(AttributeError, KeyError):
            pass
        return super().all()

    def create(self, *args, **kwargs):
        raise NotImplementedError
