from django.urls import path, register_converter

from c3nav.site.converters import LocationConverter, CoordinatesConverter, AtPositionConverter, IsEmbedConverter
from c3nav.site.views import (about_view, access_redeem_view, account_view, change_password_view, choose_language,
                              login_view, logout_view, map_index, position_create, position_detail, position_list,
                              position_set, qr_code, register_view, report_create, report_detail, report_list)

register_converter(LocationConverter, 'loc')
register_converter(CoordinatesConverter, 'coords')
register_converter(AtPositionConverter, 'at_pos')
register_converter(IsEmbedConverter, 'is_embed')

embed = '<is_embed:embed>'
pos = '<at_pos:pos>'

urlpatterns = [
    path(f'{embed}l/<loc:slug>/{pos}', map_index, {'mode': 'l'}, name='site.index', ),
    path(f'{embed}l/<loc:slug>/details/{pos}', map_index, {'mode': 'l', 'details': True}, name='site.index'),
    path(f'{embed}l/<loc:slug>/nearby/{pos}', map_index, {'mode': 'l', 'nearby': True}, name='site.index'),
    path(f'{embed}o/<loc:slug>/{pos}', map_index, {'mode': 'o'}, name='site.index'),
    path(f'{embed}d/<loc:slug>/{pos}', map_index, {'mode': 'd'}, name='site.index'),
    path(f'{embed}r/{pos}', map_index, {'mode': 'r'}, name='site.index'),
    path(f'{embed}r/<loc:slug>/<loc:slug2>/{pos}', map_index, {'mode': 'r'}, name='site.index'),
    path(f'{embed}r/<loc:slug>/<loc:slug2>/details{pos}', map_index, {'mode': 'r', 'details': True}, name='site.index'),
    path(f'{embed}r/<loc:slug>/<loc:slug2>/options{pos}', map_index, {'mode': 'r', 'options': True}, name='site.index'),
    path(f'{embed}r/<loc:slug>/<loc:slug2>/options{pos}', map_index, {'mode': 'r', 'options': True}, name='site.index'),
    path(f'{embed}{pos}', map_index, name='site.index'),
    path('qr/<path:path>', qr_code, name='site.qr'),
    path('login', login_view, name='site.login'),
    path('logout', logout_view, name='site.logout'),
    path('register', register_view, name='site.register'),
    path('account/', account_view, name='site.account'),
    path('account/change_password', change_password_view, name='site.account.change_password'),
    path('access/<str:token>', access_redeem_view, name='site.access.redeem'),
    path('lang/', choose_language, name='site.language'),
    path('about/', about_view, name='site.about'),
    path('reports/open/', report_list, {'filter': 'open'}, name='site.report_list'),
    path('reports/all/', report_list, {'filter': 'all'}, name='site.report_list'),
    path('reports/<int:pk>/', report_detail, name='site.report_detail'),
    path('reports/<int:pk>/<str:secret>/', report_detail, name='site.report_detail'),
    path('report/l/<coords:coordinates>/', report_create, name='site.report_create'),
    path('report/l/<int:location>/', report_create, name='site.report_create'),
    path('report/r/<str:origin>/<str:destination>/<str:options>/', report_create, name='site.report_create'),
    path('positions/', position_list, name='site.position_list'),
    path('positions/create/', position_create, name='site.position_create'),
    path('positions/<int:pk>/', position_detail, name='site.position_detail'),
    path('positions/set/<coords:coordinates>/', position_set, name='site.position_set'),
]
