from django.conf.urls import url

from c3nav.editor.views import edit, list_objects, main_index, section_detail, space_detail


def add_editor_urls(name, model, parent_name_plural=None, parent_name=None, with_list=True, explicit_edit=False):
    prefix = ('' if parent_name is None else parent_name_plural+r'/(?P<'+parent_name+'>[0-9]+)/')+name
    name_prefix = 'editor.'+name+'.'
    kwargs = {'model': model, 'explicit_edit': explicit_edit}
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
urlpatterns.extend(add_editor_urls('sections', 'Section', with_list=False, explicit_edit=True))
urlpatterns.extend(add_editor_urls('locationgroups', 'LocationGroup'))
urlpatterns.extend(add_editor_urls('spaces', 'Space', 'sections', 'section', explicit_edit=True))
urlpatterns.extend(add_editor_urls('doors', 'Door', 'sections', 'section'))
