from django.conf.urls import url

from c3nav.control.views import main_index, user_list

urlpatterns = [
    url(r'^users/$', user_list, name='control.users'),
    url(r'^$', main_index, name='control.index'),
]
