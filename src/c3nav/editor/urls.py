from django.conf.urls import url

from c3nav.editor.views import edit, list_objects, main_index, section_detail


def add_editor_urls(name, model, parent_name_plural=None, parent_name=None):
    prefix = '' if parent_name is None else parent_name_plural+r'/(?P<'+parent_name+'>[0-9]+)/'
    return [
        url(r'^'+prefix+name+r'/$', list_objects, name='editor.'+name+'.list', kwargs={'model': model}),
        url(r'^'+prefix+name+r'/(?P<pk>[0-9]+)/$', edit, name='editor.'+name+'.edit', kwargs={'model': model}),
        url(r'^'+prefix+name+r'/create$', edit, name='editor.'+name+'.create', kwargs={'model': model}),
    ]


urlpatterns = [
    url(r'^$', main_index, name='editor.index'),
    url(r'^sections/(?P<pk>[0-9]+)/$', section_detail, name='editor.section'),
    url(r'^sections/(?P<pk>[0-9]+)/edit$', edit, name='editor.section.edit', kwargs={'model': 'Section'}),
    url(r'^sections/create$', edit, name='editor.section.create', kwargs={'model': 'Section'}),
]
urlpatterns.extend(add_editor_urls('locationgroups', 'LocationGroup'))
urlpatterns.extend(add_editor_urls('doors', 'Door', 'sections', 'section'))
