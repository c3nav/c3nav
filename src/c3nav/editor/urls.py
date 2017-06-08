from django.apps import apps
from django.conf.urls import url

from c3nav.editor.views import edit, list_objects, main_index, section_detail, space_detail


def add_editor_urls(model_name, parent_model_name=None, with_list=True, explicit_edit=False):
    model = apps.get_model('mapdata', model_name)
    model_name_plural = model._meta.default_related_name
    if parent_model_name:
        parent_model = apps.get_model('mapdata', parent_model_name)
        parent_model_name_plural = parent_model._meta.default_related_name
        prefix = (parent_model_name_plural+r'/(?P<'+parent_model_name.lower()+'>[0-9]+)/')+model_name_plural
    else:
        prefix = model_name_plural

    name_prefix = 'editor.'+model_name_plural+'.'
    kwargs = {'model': model_name, 'explicit_edit': explicit_edit}
    explicit_edit = r'edit' if explicit_edit else ''

    result = []
    if with_list:
        result.append(url(r'^'+prefix+r'/$', list_objects, name=name_prefix+'list', kwargs=kwargs))
    result.extend([
        url(r'^'+prefix+r'/(?P<pk>\d+)/'+explicit_edit+'$', edit, name=name_prefix+'edit', kwargs=kwargs),
        url(r'^'+prefix+r'/create$', edit, name=name_prefix+'create', kwargs=kwargs),
    ])
    return result


urlpatterns = [
    url(r'^$', main_index, name='editor.index'),
    url(r'^sections/(?P<pk>[0-9]+)/$', section_detail, name='editor.sections.detail'),
    url(r'^sections/(?P<section>[0-9]+)/spaces/(?P<pk>[0-9]+)/$', space_detail, name='editor.spaces.detail'),
]
urlpatterns.extend(add_editor_urls('Section', with_list=False, explicit_edit=True))
urlpatterns.extend(add_editor_urls('LocationGroup'))
urlpatterns.extend(add_editor_urls('Source'))
urlpatterns.extend(add_editor_urls('Building', 'Section'))
urlpatterns.extend(add_editor_urls('Space', 'Section', explicit_edit=True))
urlpatterns.extend(add_editor_urls('Door', 'Section'))
urlpatterns.extend(add_editor_urls('Hole', 'Space'))
urlpatterns.extend(add_editor_urls('Area', 'Space'))
urlpatterns.extend(add_editor_urls('Stair', 'Space'))
urlpatterns.extend(add_editor_urls('Obstacle', 'Space'))
urlpatterns.extend(add_editor_urls('LineObstacle', 'Space'))
urlpatterns.extend(add_editor_urls('Point', 'Space'))
