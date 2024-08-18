from django.apps import apps
from django.urls import path, register_converter

from c3nav.editor.converters import EditPkConverter
from c3nav.editor.views.account import change_password_view, login_view, logout_view, register_view
from c3nav.editor.views.changes import changeset_detail, changeset_edit, changeset_redirect
from c3nav.editor.views.edit import edit, graph_edit, level_detail, list_objects, main_index, sourceimage, space_detail, mapupdate_viz
from c3nav.editor.views.users import user_detail, user_redirect

register_converter(EditPkConverter, 'editpk')


def add_editor_urls(model_name, parent_model_name=None, with_list=True, explicit_edit=False):
    model = apps.get_model('mapdata', model_name)
    model_name_plural = model._meta.default_related_name
    if parent_model_name:
        parent_model = apps.get_model('mapdata', parent_model_name)
        parent_model_name_plural = parent_model._meta.default_related_name
        prefix = (parent_model_name_plural+r'/<editpk:'+parent_model_name.lower()+'>/')+model_name_plural
    else:
        prefix = model_name_plural

    name_prefix = 'editor.'+model_name_plural+'.'
    kwargs = {'model': model_name, 'explicit_edit': explicit_edit}
    explicit_edit = 'edit' if explicit_edit else ''

    result = []
    if with_list:
        result.append(path(prefix+'/', list_objects, name=name_prefix+'list', kwargs=kwargs))
    result.extend([
        path(prefix+'/<editpk:pk>/'+explicit_edit, edit, name=name_prefix+'edit', kwargs=kwargs),
        path(prefix+'/create', edit, name=name_prefix+'create', kwargs=kwargs),
    ])
    return result


# todo: custom path converters
urlpatterns = [
    path('levels/<editpk:pk>/', level_detail, name='editor.levels.detail'),
    path('levels/<editpk:level>/spaces/<editpk:pk>/', space_detail, name='editor.spaces.detail'),
    path('levels/<editpk:on_top_of>/levels_on_top/create', edit, {'model': 'Level'},
         name='editor.levels_on_top.create'),
    path('levels/<editpk:level>/graph/', graph_edit, name='editor.levels.graph'),
    path('levels/<editpk:level>/mapupdate/<int:pk>/', mapupdate_viz, name='editor.levels.mapupdate'),
    path('spaces/<editpk:space>/graph/', graph_edit, name='editor.spaces.graph'),
    path('changeset/', changeset_redirect, name='editor.changesets.current'),
    path('changesets/<editpk:pk>/', changeset_detail, name='editor.changesets.detail'),
    path('changesets/<editpk:pk>/edit', changeset_edit, name='editor.changesets.edit'),
    path('sourceimage/<str:filename>', sourceimage, name='editor.sourceimage'),
    path('user/', user_redirect, name='editor.users.redirect'),
    path('users/<int:pk>/', user_detail, name='editor.users.detail'),
    path('login', login_view, name='editor.login'),
    path('logout', logout_view, name='editor.logout'),
    path('register', register_view, name='editor.register'),
    path('change_password', change_password_view, name='editor.change_password'),
    path('', main_index, name='editor.index'),
]
urlpatterns.extend(add_editor_urls('Level', with_list=False, explicit_edit=True))
urlpatterns.extend(add_editor_urls('LocationGroupCategory'))
urlpatterns.extend(add_editor_urls('LocationGroup'))
urlpatterns.extend(add_editor_urls('ObstacleGroup'))
urlpatterns.extend(add_editor_urls('DynamicLocation'))
urlpatterns.extend(add_editor_urls('WayType'))
urlpatterns.extend(add_editor_urls('GroundAltitude'))
urlpatterns.extend(add_editor_urls('AccessRestriction'))
urlpatterns.extend(add_editor_urls('AccessRestrictionGroup'))
urlpatterns.extend(add_editor_urls('Source'))
urlpatterns.extend(add_editor_urls('LabelSettings'))
urlpatterns.extend(add_editor_urls('Theme'))
urlpatterns.extend(add_editor_urls('Building', 'Level'))
urlpatterns.extend(add_editor_urls('Space', 'Level', explicit_edit=True))
urlpatterns.extend(add_editor_urls('Door', 'Level'))
urlpatterns.extend(add_editor_urls('Hole', 'Space'))
urlpatterns.extend(add_editor_urls('Area', 'Space'))
urlpatterns.extend(add_editor_urls('Stair', 'Space'))
urlpatterns.extend(add_editor_urls('Ramp', 'Space'))
urlpatterns.extend(add_editor_urls('Obstacle', 'Space'))
urlpatterns.extend(add_editor_urls('LineObstacle', 'Space'))
urlpatterns.extend(add_editor_urls('Column', 'Space'))
urlpatterns.extend(add_editor_urls('POI', 'Space'))
urlpatterns.extend(add_editor_urls('AltitudeMarker', 'Space'))
urlpatterns.extend(add_editor_urls('LeaveDescription', 'Space'))
urlpatterns.extend(add_editor_urls('CrossDescription', 'Space'))
urlpatterns.extend(add_editor_urls('BeaconMeasurement', 'Space'))
urlpatterns.extend(add_editor_urls('RangingBeacon', 'Space'))
