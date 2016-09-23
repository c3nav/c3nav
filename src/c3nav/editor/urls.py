from django.conf.urls import url
from django.views.generic import TemplateView

from c3nav.editor.views import add_feature

urlpatterns = [
    url(r'^$', TemplateView.as_view(template_name='editor/map.html'), name='editor.index'),
    url(r'^features/(?P<feature_type>[^/]+)/add/$', add_feature, name='editor.feature.add')
]
