from django.conf.urls import url
from django.views.generic import TemplateView

from c3nav.editor.views import edit_mapitem, list_mapitems, list_mapitemtypes

urlpatterns = [
    url(r'^$', TemplateView.as_view(template_name='editor/map.html'), name='editor.index'),
    url(r'^mapitemtypes/(?P<level>[^/]+)/$', list_mapitemtypes, name='editor.mapitemtypes'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/list/$', list_mapitems, name='editor.mapitems'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/list/(?P<level>[^/]+)/$', list_mapitems, name='editor.mapitems.level'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/add/$', edit_mapitem, name='editor.mapitems.add'),
    url(r'^mapitems/(?P<mapitem_type>[^/]+)/edit/(?P<id>[^/]+)/$', edit_mapitem, name='editor.mapitems.edit'),
]
