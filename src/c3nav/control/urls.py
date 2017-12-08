from django.conf.urls import url

from c3nav.control.views import main_index

urlpatterns = [
    url(r'^$', main_index, name='control.index'),
]
