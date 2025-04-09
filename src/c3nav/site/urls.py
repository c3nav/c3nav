from itertools import chain

from django.urls import path, register_converter

from c3nav.site.converters import AtPositionConverter, CoordinatesConverter, IsEmbedConverter
from c3nav.site.views import (about_view, access_redeem_view, account_manage, account_view, api_secret_create,
                              api_secret_list, change_password_view, choose_language, delete_account_view, login_view,
                              logout_view, map_index, position_create, position_detail, position_list, position_set,
                              qr_code, register_view, report_create, report_detail, report_list,
                              report_start_coordinates, report_start_location, report_start_route, report_missing_check,
                              report_select_location, report_missing_choose)

register_converter(CoordinatesConverter, 'coords')
register_converter(AtPositionConverter, 'at_pos')
register_converter(IsEmbedConverter, 'is_embed')

embed = '<is_embed:embed>'
pos = '<at_pos:pos>'


def index_paths(pre, suf):
    return [
        path(f'{pre}l/<loc:slug>/{suf}', map_index, {'mode': 'l', 'details': False, 'nearby': False},
             name='site.index'),
        path(f'{pre}l/<loc:slug>/details/{suf}', map_index, {'mode': 'l', 'details': True}, name='site.index'),
        path(f'{pre}l/<loc:slug>/nearby/{suf}', map_index, {'mode': 'l', 'nearby': True}, name='site.index'),
        path(f'{pre}o/<loc:slug>/{suf}', map_index, {'mode': 'o'}, name='site.index'),
        path(f'{pre}d/<loc:slug>/{suf}', map_index, {'mode': 'd'}, name='site.index'),
        path(f'{pre}r/{suf}', map_index, {'mode': 'r'}, name='site.index'),
        path(f'{pre}r/<loc:slug>/<loc:slug2>/{suf}', map_index, {'mode': 'r', 'details': False, 'options': False},
             name='site.index'),
        path(f'{pre}r/<loc:slug>/<loc:slug2>/details/{suf}', map_index, {'mode': 'r', 'details': True},
             name='site.index'),
        path(f'{pre}r/<loc:slug>/<loc:slug2>/options/{suf}', map_index, {'mode': 'r', 'options': True},
             name='site.index'),
        path(f'{pre}{suf}', map_index, name='site.index'),
    ]


urlpatterns = [
    *chain(*(index_paths(pre, suf) for pre in ('', embed) for suf in ('', pos))),
    path('qr/<path:path>', qr_code, name='site.qr'),
    path('login', login_view, name='site.login'),
    path('logout', logout_view, name='site.logout'),
    path('register', register_view, name='site.register'),
    path('account/', account_view, name='site.account'),
    path('account/manage/', account_manage, name='site.account.manage'),
    path('account/change_password/', change_password_view, name='site.account.change_password'),
    path('account/delete/', delete_account_view, name='site.account.delete'),
    path('access/<str:token>', access_redeem_view, name='site.access.redeem'),
    path('lang/', choose_language, name='site.language'),
    path('about/', about_view, name='site.about'),
    path('reports/open/', report_list, {'filter': 'open'}, name='site.report_list'),
    path('reports/all/', report_list, {'filter': 'all'}, name='site.report_list'),
    path('reports/<int:pk>/', report_detail, name='site.report_detail'),
    path('reports/<int:pk>/<str:secret>/', report_detail, name='site.report_detail'),
    path('report/l/<coords:coordinates>/', report_start_coordinates, name='site.report_start'),
    path('report/l/<coords:coordinates>/missing/', report_missing_check, name='site.report_missing_check'),
    path('report/l/<coords:coordinates>/existing/', report_select_location, name='site.report_select_location'),
    path('report/l/<coords:coordinates>/choose/', report_missing_choose, name='site.report_missing_choose'),
    path('report/l/<int:location>/', report_start_location, name='site.report_start'),
    path('report/r/<str:origin>/<str:destination>/<str:options>/', report_start_route, name='site.report_start'),
    path('report/create/l/<coords:coordinates>/', report_create, name='site.report_create'),
    path('report/create/l/<coords:coordinates>/<str:parent>/', report_create, name='site.report_create'),
    path('report/create/l/<int:location>/', report_create, name='site.report_create'),
    path('report/create/r/<str:origin>/<str:destination>/<str:options>/', report_create, name='site.report_create'),
    path('positions/', position_list, name='site.position_list'),
    path('positions/create/', position_create, name='site.position_create'),
    path('positions/<int:pk>/', position_detail, name='site.position_detail'),
    path('positions/set/<coords:coordinates>/', position_set, name='site.position_set'),
    path('api-secrets/', api_secret_list, name='site.api_secret_list'),
    path('api-secrets/create/', api_secret_create, name='site.api_secret_create'),
]
