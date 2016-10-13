from django.conf.urls import url
from django.views.generic import TemplateView

from c3nav.editor.views import edit_feature, finalize, oauth_callback

urlpatterns = [
    url(r'^$', TemplateView.as_view(template_name='editor/map.html'), name='editor.index'),
    url(r'^features/(?P<feature_type>[^/]+)/add/$', edit_feature, name='editor.feature.add'),
    url(r'^features/(?P<feature_type>[^/]+)/edit/(?P<name>[^/]+)/$', edit_feature, name='editor.feature.edit'),
    url(r'^finalize/$', finalize, name='editor.finalize'),
    url(r'^oauth/(?P<hoster>[^/]+)/callback$', oauth_callback, name='editor.oauth.callback')
]
