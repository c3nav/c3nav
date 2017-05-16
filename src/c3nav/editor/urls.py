from django.conf.urls import url

from c3nav.editor.views import edit_mapitem, list_mapitems, list_mapitemtypes, main_index, section_detail

urlpatterns = [
    url(r'^$', main_index, name='editor.index'),
    url(r'^sections/(?P<section>[0-9]+)/$', section_detail, name='editor.section'),
    url(r'^sections/(?P<section>[0-9]+)/edit$', section_detail, name='editor.section.edit'),
    url(r'^mapitemtypes/(?P<level>[^/]+)/$', list_mapitemtypes, name='editor.mapitemtypes'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/list/$', list_mapitems, name='editor.mapitems'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/list/(?P<sectionl>[0-9]+)/$', list_mapitems, name='editor.mapitems.level'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/add/$', edit_mapitem, name='editor.mapitems.add'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/edit/(?P<id>[^/]+)/$', edit_mapitem, name='editor.mapitems.edit'),
]
