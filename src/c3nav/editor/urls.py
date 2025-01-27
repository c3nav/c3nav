from django.apps import apps
from django.urls import path
from django.views.generic import TemplateView

from c3nav.editor.views.account import change_password_view, login_view, logout_view, register_view
from c3nav.editor.views.changes import changeset_detail, changeset_edit, changeset_redirect
from c3nav.editor.views.edit import edit, graph_edit, level_detail, list_objects, main_index, sourceimage, space_detail
from c3nav.editor.views.overlays import overlays_list, overlay_features, overlay_feature_edit
from c3nav.editor.views.quest import QuestFormView
from c3nav.editor.views.users import user_detail, user_redirect


def add_editor_urls(model_name, parent_model_name=None, with_list=True, explicit_edit=False):
    model = apps.get_model('mapdata', model_name)
    model_name_plural = model._meta.default_related_name
    if parent_model_name:
        parent_model = apps.get_model('mapdata', parent_model_name)
        parent_model_name_plural = parent_model._meta.default_related_name
        prefix = (parent_model_name_plural+r'/<int:'+parent_model_name.lower()+'>/')+model_name_plural
    else:
        prefix = model_name_plural

    name_prefix = 'editor.'+model_name_plural+'.'
    kwargs = {'model': model_name, 'explicit_edit': explicit_edit}
    explicit_edit = 'edit' if explicit_edit else ''

    result = []
    if with_list:
        result.append(path(prefix+'/', list_objects, name=name_prefix+'list', kwargs=kwargs))
    result.extend([
        path(prefix+'/<int:pk>/'+explicit_edit, edit, name=name_prefix+'edit', kwargs=kwargs),
        path(prefix+'/create', edit, name=name_prefix+'create', kwargs=kwargs),
    ])
    return result


# todo: custom path converters
urlpatterns = [
    path('levels/<int:pk>/', level_detail, name='editor.levels.detail'),
    path('levels/<int:level>/spaces/<int:pk>/', space_detail, name='editor.spaces.detail'),
    path('levels/<int:on_top_of>/levels_on_top/create', edit, {'model': 'Level'},
         name='editor.levels_on_top.create'),
    path('levels/<int:level>/graph/', graph_edit, name='editor.levels.graph'),
    path('spaces/<int:space>/graph/', graph_edit, name='editor.spaces.graph'),
    path('levels/<int:level>/overlays/', overlays_list, name='editor.levels.overlays'),
    path('levels/<int:level>/overlays/<int:pk>/', overlay_features, name='editor.levels.overlay'),
    path('levels/<int:level>/overlays/<int:overlay>/create', overlay_feature_edit, name='editor.levels.overlay.create'),
    path('levels/<int:level>/overlays/<int:overlay>/features/<int:pk>', overlay_feature_edit, name='editor.levels.overlay.edit'),
    path('overlayfeatures/<int:pk>', overlay_feature_edit, name='editor.overlayfeatures.edit'),
    path('changeset/', changeset_redirect, name='editor.changesets.current'),
    path('changesets/<int:pk>/', changeset_detail, name='editor.changesets.detail'),
    path('changesets/<int:pk>/edit', changeset_edit, name='editor.changesets.edit'),
    path('sourceimage/<str:filename>', sourceimage, name='editor.sourceimage'),
    path('user/', user_redirect, name='editor.users.redirect'),
    path('users/<int:pk>/', user_detail, name='editor.users.detail'),
    path('login', login_view, name='editor.login'),
    path('logout', logout_view, name='editor.logout'),
    path('register', register_view, name='editor.register'),
    path('change_password', change_password_view, name='editor.change_password'),
    path('quests/<str:quest_type>/<str:identifier>/', QuestFormView.as_view(), name='editor.quest'),
    path('thanks/', TemplateView.as_view(template_name="editor/thanks.html"), name='editor.thanks'),
    path('', main_index, name='editor.index'),
]
urlpatterns.extend(add_editor_urls('Level', with_list=False, explicit_edit=True))
urlpatterns.extend(add_editor_urls('SpecificLocation'))
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
urlpatterns.extend(add_editor_urls('LoadGroup'))
urlpatterns.extend(add_editor_urls('Theme'))
urlpatterns.extend(add_editor_urls('DataOverlay'))
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
