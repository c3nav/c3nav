from django.conf.urls import url
from django.views.generic import TemplateView

from c3nav.editor.views import (edit_feature, finalize, finalize_oauth_callback, finalize_oauth_progress,
                                finalize_oauth_redirect)

urlpatterns = [
    url(r'^$', TemplateView.as_view(template_name='editor/map.html'), name='editor.index'),
    url(r'^features/(?P<feature_type>[^/]+)/add/$', edit_feature, name='editor.feature.add'),
    url(r'^features/edit/(?P<name>[^/]+)/$', edit_feature, name='editor.feature.edit'),
    url(r'^finalize/$', finalize, name='editor.finalize'),
    url(r'^finalize/oauth/$', finalize_oauth_redirect, name='editor.finalize.oauth'),
    url(r'^finalize/oauth/progress$', finalize_oauth_progress, name='editor.finalize.oauth.progress'),
    url(r'^finalize/oauth/(?P<hoster>[^/]+)/callback$', finalize_oauth_callback, name='editor.finalize.oauth.callback')
]
