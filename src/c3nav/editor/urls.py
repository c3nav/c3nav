from django.conf.urls import url

from c3nav.editor.views import edit, main_index, section_detail

urlpatterns = [
    url(r'^$', main_index, name='editor.index'),
    url(r'^sections/(?P<pk>[0-9]+)/$', section_detail, name='editor.section'),
    url(r'^sections/(?P<pk>[0-9]+)/edit$', edit, name='editor.section.edit', kwargs={'model': 'Section'}),
    url(r'^sections/create$', edit, name='editor.section.create', kwargs={'model': 'Section'}),
]
