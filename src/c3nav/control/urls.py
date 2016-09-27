from django.conf.urls import url

from c3nav.control.views import dashboard

urlpatterns = [
    url(r'^$', dashboard, name='control.dashboard'),
]
