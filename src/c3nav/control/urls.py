from django.conf.urls import url

from c3nav.control.views import main_index, user_detail, user_list

urlpatterns = [
    url(r'^users/$', user_list, name='control.users'),
    url(r'^users/(?P<user>\d+)/$', user_detail, name='control.users.detail'),
    url(r'^$', main_index, name='control.index'),
]
