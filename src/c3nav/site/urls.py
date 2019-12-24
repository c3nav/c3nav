from django.conf.urls import url

from c3nav.site.views import (about_view, access_redeem_view, account_view, change_password_view, choose_language,
                              login_view, logout_view, map_index, qr_code, register_view, report_create, report_detail,
                              report_list)

slug = r'(?P<slug>[a-z0-9-_.:]+)'
coordinates = r'(?P<coordinates>[a-z0-9-_:]+:-?\d+(\.\d+)?:-?\d+(\.\d+)?)'
slug2 = r'(?P<slug2>[a-z0-9-_.:]+)'
details = r'(?P<details>details/)?'
nearby = r'(?P<nearby>nearby/)?'
options = r'(?P<options>options/)?'
pos = r'(@(?P<level>[a-z0-9-_:]+),(?P<x>-?\d+(\.\d+)?),(?P<y>-?\d+(\.\d+)?),(?P<zoom>-?\d+(\.\d+)?))?'
embed = r'(?P<embed>embed/)?'

urlpatterns = [
    url(r'^%s(?P<mode>[l])/%s/(%s|%s)%s$' % (embed, slug, details, nearby, pos), map_index, name='site.index'),
    url(r'^%s(?P<mode>[od])/%s/%s$' % (embed, slug, pos), map_index, name='site.index'),
    url(r'^%sr/%s/%s/(%s|%s)%s$' % (embed, slug, slug2, details, options, pos), map_index, name='site.index'),
    url(r'^%s(?P<mode>r)/%s$' % (embed, pos), map_index, name='site.index'),
    url(r'^%s%s$' % (embed, pos), map_index, name='site.index'),
    url(r'^qr/(?P<path>.*)$', qr_code, name='site.qr'),
    url(r'^login$', login_view, name='site.login'),
    url(r'^logout$', logout_view, name='site.logout'),
    url(r'^register$', register_view, name='site.register'),
    url(r'^account/$', account_view, name='site.account'),
    url(r'^account/change_password$', change_password_view, name='site.account.change_password'),
    url(r'^access/(?P<token>[^/]+)$', access_redeem_view, name='site.access.redeem'),
    url(r'^lang/$', choose_language, name='site.language'),
    url(r'^about/$', about_view, name='site.about'),
    url(r'^reports/(?P<filter>(open|all))/$', report_list, name='site.report_list'),
    url(r'^reports/(?P<pk>\d+)/$', report_detail, name='site.report_detail'),
    url(r'^reports/(?P<pk>\d+)/(?P<secret>[^/]+)/$', report_detail, name='site.report_detail'),
    url(r'^report/l/%s/$' % coordinates, report_create, name='site.report_create'),
    url(r'^report/l/(?P<location>\d+)/$', report_create, name='site.report_create'),
    url(r'^report/r/(?P<origin>[^/]+)/(?P<destination>[^/]+)/(?P<options>[^/]+)/$',
        report_create, name='site.report_create'),
]
