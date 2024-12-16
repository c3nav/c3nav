from c3nav.editor.forms import get_editor_form
from c3nav.editor.views.base import (APIHybridError, APIHybridFormTemplateResponse,
                                     APIHybridMessageRedirectResponse, APIHybridTemplateContextResponse,
                                     editor_etag_func, sidebar_view, accesses_mapdata)
from django.shortcuts import get_object_or_404
from django.views.decorators.http import etag
from django.urls import reverse
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ObjectDoesNotExist, PermissionDenied
from django.contrib import messages
from django.db import IntegrityError

from c3nav.editor.utils import DefaultEditUtils, LevelChildEditUtils
from c3nav.editor.views.edit import get_changeset_exceeded
from c3nav.mapdata.models import DataOverlay, Level, DataOverlayFeature


@etag(editor_etag_func)
@accesses_mapdata
@sidebar_view(api_hybrid=True)
def overlays_list(request, level):
    queryset = DataOverlay.objects.all().order_by('id')
    if hasattr(DataOverlay, 'q_for_request'):
        queryset = queryset.filter(DataOverlay.q_for_request(request))

    level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
    edit_utils = LevelChildEditUtils(level, request)

    ctx = {
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'level': level,
        'level_url': 'editor.levels.overlays',
        'geometry_url': edit_utils.geometry_url,
        'overlays': queryset,
    }

    return APIHybridTemplateContextResponse('editor/overlays.html', ctx, fields=('overlays',))

@etag(editor_etag_func)
@accesses_mapdata
@sidebar_view(api_hybrid=True)
def overlay_features(request, level, pk):
    ctx = {
        'path': request.path,
        'overlay_id': pk,
    }

    queryset = DataOverlayFeature.objects.filter(level_id=level, overlay_id=pk).order_by('id')
    add_cols = []

    level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
    overlay = get_object_or_404(DataOverlay.objects.filter(DataOverlay.q_for_request(request)), pk=pk)
    edit_utils = LevelChildEditUtils(level, request)
    ctx.update({
        'title': overlay.title,
        'back_url': reverse('editor.levels.overlays', kwargs={'level': level.pk}),
        'back_title': _('back to overlays'),
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'level': level,

        # TODO: this makes the level switcher always link to the overview of all overlays, rather than the current overlay
        #       unclear how to make it possible to switch to the correct overlay
        'level_url': 'editor.levels.overlays',
    })

    for obj in queryset:
        obj.edit_url = reverse('editor.overlayfeatures.edit', kwargs={'pk': obj.pk})
        obj.add_cols = tuple(getattr(obj, col) for col in add_cols)


    ctx.update({
        'can_create': True,
        'geometry_url': edit_utils.geometry_url,
        'add_cols': add_cols,
        'create_url': reverse('editor.levels.overlay.create', kwargs={'level': level.pk, 'overlay': overlay.pk}),
        'features': queryset,
        'extra_json_data': {
            'activeOverlayId': overlay.pk
        },
    })

    return APIHybridTemplateContextResponse('editor/overlay_features.html', ctx,
                                            fields=('can_create', 'create_url', 'objects'))

@etag(editor_etag_func)
@accesses_mapdata
@sidebar_view(api_hybrid=True)
def overlay_feature_edit(request, level=None, overlay=None, pk=None):
    changeset_exceeded = get_changeset_exceeded(request)

    can_edit_changeset = request.changeset.can_edit(request)

    obj = None
    edit_utils = DefaultEditUtils(request)
    if pk is not None:
        # Edit existing map item
        kwargs = {'pk': pk}
        qs = DataOverlayFeature.objects.all()
        if hasattr(DataOverlayFeature, 'q_for_request'):
            qs = qs.filter(DataOverlayFeature.q_for_request(request))

        qs = qs.select_related('level')
        qs = qs.select_related('overlay')
        utils_cls = LevelChildEditUtils
        
        obj = get_object_or_404(qs, **kwargs)
        level = obj.level
        overlay = obj.overlay
        edit_utils = utils_cls.from_obj(obj, request)
    else:
        level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
        overlay = get_object_or_404(DataOverlay.objects.filter(DataOverlay.q_for_request(request)), pk=overlay)
        edit_utils = LevelChildEditUtils(level, request)
    
    new = obj is None

    if new and not edit_utils.can_create:
        raise PermissionDenied

    geometry_url = edit_utils.geometry_url

    # noinspection PyProtectedMember
    ctx = {
        'path': request.path,
        'pk': pk,
        'model_name': DataOverlayFeature.__name__.lower(),
        'model_title': DataOverlayFeature._meta.verbose_name,
        'can_edit': can_edit_changeset,
        'new': new,
        'title': obj.title if obj else None,
        'geometry_url': geometry_url,
        'geomtype': 'polygon,linestring,point',
        'default_geomtype': overlay.default_geomtype,
    }

    space_id = None

    ctx.update({
        'level': level,
        'back_url': reverse('editor.levels.overlay', kwargs={'level': level.pk, 'pk': overlay.pk}),
    })

    nosave = False
    if changeset_exceeded:
        if new:
            return APIHybridMessageRedirectResponse(
                level='error', message=_('You can not create new objects because your changeset is full.'),
                redirect_to=ctx['back_url'], status_code=409,
            )
        elif obj.pk not in request.changeset.changes.objects.get(obj._meta.model_name, {}):
            messages.warning(request, _('You can not edit this object because your changeset is full.'))
            nosave = True

    ctx.update({
        'nosave': nosave
    })

    if new:
        ctx.update({
            'nozoom': True
        })

    error = None
    delete = getattr(request, 'is_delete', None)
    
    if request.method == 'POST' or (not new and delete):
        if nosave:
            return APIHybridMessageRedirectResponse(
                level='error', message=_('You can not edit this object because your changeset is full.'),
                redirect_to=request.path, status_code=409,
            )

        if not can_edit_changeset:
            return APIHybridMessageRedirectResponse(
                level='error', message=_('You can not edit changes on this changeset.'),
                redirect_to=request.path, status_code=403,
            )

        if not new and ((request.POST.get('delete') == '1' and delete is not False) or delete):
            # Delete this mapitem!
            try:
                if not request.changeset.get_changed_object(obj).can_delete():
                    raise PermissionError
            except (ObjectDoesNotExist, PermissionError):
                return APIHybridMessageRedirectResponse(
                    level='error',
                    message=_('You can not delete this object because other objects still depend on it.'),
                    redirect_to=request.path, status_code=409,
                )

            if request.POST.get('delete_confirm') == '1' or delete:
                with request.changeset.lock_to_edit(request) as changeset:
                    if changeset.can_edit(request):
                        obj.delete()
                    else:
                        return APIHybridMessageRedirectResponse(
                            level='error',
                            message=_('You can not edit changes on this changeset.'),
                            redirect_to=request.path, status_code=403,
                        )

                redirect_to = ctx['back_url']
                return APIHybridMessageRedirectResponse(
                    level='success',
                    message=_('Object was successfully deleted.'),
                    redirect_to=redirect_to
                )
            ctx['obj_title'] = obj.title
            return APIHybridTemplateContextResponse('editor/delete.html', ctx, fields=())

        json_body = getattr(request, 'json_body', None)
        data = json_body if json_body is not None else request.POST
        form = get_editor_form(DataOverlayFeature)(instance=DataOverlayFeature() if new else obj, data=data, is_json=json_body is not None,
                                request=request, space_id=space_id,
                                geometry_editable=edit_utils.can_access_child_base_mapdata)
        if form.is_valid():
            # Update/create objects
            obj = form.save(commit=False)

            obj.level = level
            obj.overlay = overlay

            with request.changeset.lock_to_edit(request) as changeset:
                if changeset.can_edit(request):
                    try:
                        obj.save()
                    except IntegrityError as e:
                        error = APIHybridError(status_code=400, message=_('Duplicate entry.'))
                    else:
                        if form.redirect_slugs is not None:
                            for slug in form.add_redirect_slugs:
                                obj.redirects.create(slug=slug)

                            for slug in form.remove_redirect_slugs:
                                obj.redirects.filter(slug=slug).delete()

                        form.save_m2m()
                        return APIHybridMessageRedirectResponse(
                            level='success',
                            message=_('Object was successfully saved.'),
                            redirect_to=ctx['back_url']
                        )
                else:
                    error = APIHybridError(status_code=403, message=_('You can not edit changes on this changeset.'))

    else:
        form = get_editor_form(DataOverlayFeature)(instance=obj, request=request, space_id=space_id,
                                      geometry_editable=edit_utils.can_access_child_base_mapdata)

    ctx.update({
        'form': form,
        'extra_json_data': {
            'activeOverlayId': overlay.pk
        }
    })

    return APIHybridFormTemplateResponse('editor/edit.html', ctx, form=form, error=error)

