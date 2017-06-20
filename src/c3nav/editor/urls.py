from django.apps import apps
from django.conf.urls import url

from c3nav.editor.views.changes import changeset_detail, changeset_history
from c3nav.editor.views.edit import edit, level_detail, list_objects, main_index, space_detail
from c3nav.editor.views.login import login_view, logout_view


def add_editor_urls(model_name, parent_model_name=None, with_list=True, explicit_edit=False):
    model = apps.get_model('mapdata', model_name)
    model_name_plural = model._meta.default_related_name
    if parent_model_name:
        parent_model = apps.get_model('mapdata', parent_model_name)
        parent_model_name_plural = parent_model._meta.default_related_name
        prefix = (parent_model_name_plural+r'/(?P<'+parent_model_name.lower()+'>c?[0-9]+)/')+model_name_plural
    else:
        prefix = model_name_plural

    name_prefix = 'editor.'+model_name_plural+'.'
    kwargs = {'model': model_name, 'explicit_edit': explicit_edit}
    explicit_edit = r'edit' if explicit_edit else ''

    result = []
    if with_list:
        result.append(url(r'^'+prefix+r'/$', list_objects, name=name_prefix+'list', kwargs=kwargs))
    result.extend([
        url(r'^'+prefix+r'/(?P<pk>c?\d+)/'+explicit_edit+'$', edit, name=name_prefix+'edit', kwargs=kwargs),
        url(r'^'+prefix+r'/create$', edit, name=name_prefix+'create', kwargs=kwargs),
    ])
    return result


urlpatterns = [
    url(r'^$', main_index, name='editor.index'),
    url(r'^levels/(?P<pk>c?[0-9]+)/$', level_detail, name='editor.levels.detail'),
    url(r'^levels/(?P<level>c?[0-9]+)/spaces/(?P<pk>c?[0-9]+)/$', space_detail, name='editor.spaces.detail'),
    url(r'^levels/(?P<on_top_of>c?[0-9]+)/levels_on_top/create$', edit, name='editor.levels_on_top.create',
        kwargs={'model': 'Level'}),
    url(r'^changesets/(?P<pk>[0-9]+)/$', changeset_detail, name='editor.changesets.detail'),
    url(r'^changesets/(?P<pk>[0-9]+)/history$', changeset_history, name='editor.changesets.history'),
    url(r'^login$', login_view, name='editor.login'),
    url(r'^logout$', logout_view, name='editor.logout'),
]
urlpatterns.extend(add_editor_urls('Level', with_list=False, explicit_edit=True))
urlpatterns.extend(add_editor_urls('LocationGroup'))
urlpatterns.extend(add_editor_urls('Source'))
urlpatterns.extend(add_editor_urls('Building', 'Level'))
urlpatterns.extend(add_editor_urls('Space', 'Level', explicit_edit=True))
urlpatterns.extend(add_editor_urls('Door', 'Level'))
urlpatterns.extend(add_editor_urls('Hole', 'Space'))
urlpatterns.extend(add_editor_urls('Area', 'Space'))
urlpatterns.extend(add_editor_urls('Stair', 'Space'))
urlpatterns.extend(add_editor_urls('Obstacle', 'Space'))
urlpatterns.extend(add_editor_urls('LineObstacle', 'Space'))
urlpatterns.extend(add_editor_urls('Column', 'Space'))
urlpatterns.extend(add_editor_urls('Point', 'Space'))
