import mimetypes
import os
import typing
from contextlib import suppress

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.core.exceptions import FieldDoesNotExist, ObjectDoesNotExist, PermissionDenied
from django.db import IntegrityError, models
from django.db.models import Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _
from django.views.decorators.http import etag

from c3nav.editor.forms import GraphEdgeSettingsForm, GraphEditorActionForm
from c3nav.editor.views.base import etag_func, sidebar_view
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.utils.user import can_access_editor


def child_model(request, model: typing.Union[str, models.Model], kwargs=None, parent=None):
    model = request.changeset.wrap_model(model)
    related_name = model._meta.default_related_name
    if parent is not None:
        qs = getattr(parent, related_name)
        if hasattr(model, 'q_for_request'):
            qs = qs.filter(model.q_for_request(request))
        count = qs.count()
    else:
        count = None
    return {
        'title': model._meta.verbose_name_plural,
        'url': reverse('editor.'+related_name+'.list', kwargs=kwargs),
        'count': count,
    }


@sidebar_view
@etag(etag_func)
def main_index(request):
    Level = request.changeset.wrap_model('Level')
    return render(request, 'editor/index.html', {
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'can_edit': request.changeset.can_edit(request),
        'child_models': [
            child_model(request, 'LocationGroupCategory'),
            child_model(request, 'LocationGroup'),
            child_model(request, 'WayType'),
            child_model(request, 'AccessRestriction'),
            child_model(request, 'AccessRestrictionGroup'),
            child_model(request, 'Source'),
        ],
    })


@sidebar_view
@etag(etag_func)
def level_detail(request, pk):
    Level = request.changeset.wrap_model('Level')
    qs = Level.objects.filter(Level.q_for_request(request))
    level = get_object_or_404(qs.select_related('on_top_of').prefetch_related('levels_on_top'), pk=pk)

    return render(request, 'editor/level.html', {
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'level': level,
        'level_url': 'editor.levels.detail',
        'level_as_pk': True,
        'can_edit': request.changeset.can_edit(request),

        'child_models': [child_model(request, model_name, kwargs={'level': pk}, parent=level)
                         for model_name in ('Building', 'Space', 'Door')],
        'levels_on_top': level.levels_on_top.filter(Level.q_for_request(request)).all(),
        'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
    })


@sidebar_view
@etag(etag_func)
def space_detail(request, level, pk):
    Level = request.changeset.wrap_model('Level')
    Space = request.changeset.wrap_model('Space')
    qs = Space.objects.filter(Space.q_for_request(request))
    space = get_object_or_404(qs.select_related('level'), level__pk=level, pk=pk)

    return render(request, 'editor/space.html', {
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'level': space.level,
        'level_url': 'editor.spaces.list',
        'space': space,
        'can_edit': request.changeset.can_edit(request),

        'child_models': [child_model(request, model_name, kwargs={'space': pk}, parent=space)
                         for model_name in ('POI', 'Area', 'Obstacle', 'LineObstacle', 'Stair', 'Ramp', 'Column',
                                            'Hole', 'AltitudeMarker', 'LeaveDescription', 'CrossDescription',
                                            'WifiMeasurement')],
        'geometry_url': '/api/editor/geometries/?space='+pk,
    })


def get_changeset_exceeded(request):
    return request.user_permissions.max_changeset_changes <= request.changeset.changed_objects_count


@sidebar_view
@etag(etag_func)
def edit(request, pk=None, model=None, level=None, space=None, on_top_of=None, explicit_edit=False):
    changeset_exceeded = get_changeset_exceeded(request)
    model_changes = {}
    if changeset_exceeded:
        model_changes = request.changeset.get_changed_objects_by_model(model)

    model = request.changeset.wrap_model(model)
    related_name = model._meta.default_related_name

    Level = request.changeset.wrap_model('Level')
    Space = request.changeset.wrap_model('Space')

    can_edit = request.changeset.can_edit(request)

    obj = None
    if pk is not None:
        # Edit existing map item
        kwargs = {'pk': pk}
        qs = model.objects.all()
        if hasattr(model, 'q_for_request'):
            qs = qs.filter(model.q_for_request(request))
        if level is not None:
            kwargs.update({'level__pk': level})
            qs = qs.select_related('level')
        elif space is not None:
            kwargs.update({'space__pk': space})
            qs = qs.select_related('space')
        obj = get_object_or_404(qs, **kwargs)
    elif level is not None:
        level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
    elif space is not None:
        space = get_object_or_404(Space.objects.filter(Space.q_for_request(request)), pk=space)
    elif on_top_of is not None:
        on_top_of = get_object_or_404(Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
                                      pk=on_top_of)

    new = obj is None
    # noinspection PyProtectedMember
    ctx = {
        'path': request.path,
        'pk': pk,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'can_edit': can_edit,
        'new': new,
        'title': obj.title if obj else None,
    }

    with suppress(FieldDoesNotExist):
        ctx.update({
            'geomtype': model._meta.get_field('geometry').geomtype,
        })

    space_id = None
    if model == Level:
        ctx.update({
            'level': obj,
            'back_url': reverse('editor.index') if new else reverse('editor.levels.detail', kwargs={'pk': pk}),
            'nozoom': True,
        })
        if not new:
            ctx.update({
                'geometry_url': '/api/editor/geometries/?level='+str(obj.primary_level_pk),
                'on_top_of': obj.on_top_of,
            })
        elif on_top_of:
            ctx.update({
                'geometry_url': '/api/editor/geometries/?level=' + str(on_top_of.pk),
                'on_top_of': on_top_of,
                'back_url': reverse('editor.levels.detail', kwargs={'pk': on_top_of.pk}),
            })
    elif model == Space and not new:
        level = obj.level
        ctx.update({
            'level': obj.level,
            'back_url': reverse('editor.spaces.detail', kwargs={'level': obj.level.pk, 'pk': pk}),
            'geometry_url': '/api/editor/geometries/?space='+pk,
            'nozoom': True,
        })
    elif model == Space and new:
        ctx.update({
            'level': level,
            'back_url': reverse('editor.spaces.list', kwargs={'level': level.pk}),
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
            'nozoom': True,
        })
    elif hasattr(model, 'level'):
        if not new:
            level = obj.level
        ctx.update({
            'level': level,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'level': level.pk}),
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
        })
    elif hasattr(model, 'space'):
        if not new:
            space = obj.space
        space_id = space.pk
        ctx.update({
            'level': space.level,
            'back_url': reverse('editor.'+related_name+'.list', kwargs={'space': space.pk}),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
    else:
        kwargs = {}
        if level is not None:
            kwargs.update({'level': level})
        elif space is not None:
            kwargs.update({'space': space})

        kwargs.update(get_visible_spaces_kwargs(model, request))

        ctx.update({
            'back_url': reverse('.'.join(request.resolver_match.url_name.split('.')[:-1]+['list']), kwargs=kwargs),
        })

    nosave = False
    if changeset_exceeded:
        if new:
            messages.error(request, _('You can not create new objects because your changeset is full.'))
            return redirect(ctx['back_url'])
        elif obj.pk not in model_changes:
            messages.warning(request, _('You can not edit this object because your changeset is full.'))
            nosave = True

    ctx.update({
        'nosave': nosave
    })

    if new:
        ctx.update({
            'nozoom': True
        })

    if new and model.__name__ == 'WifiMeasurement' and not request.user.is_authenticated:
        messages.info(request, _('You need to log in to create Wifi Measurements.'))
        return redirect_to_login(request.path_info, 'editor.login')

    if request.method == 'POST':
        if nosave:
            messages.error(request, _('You can not edit this object because your changeset is full.'))
            return redirect(request.path)

        if not new and request.POST.get('delete') == '1':
            # Delete this mapitem!
            try:
                if not request.changeset.get_changed_object(obj).can_delete():
                    raise PermissionError
            except (ObjectDoesNotExist, PermissionError):
                messages.error(request, _('You can not delete this object because other objects still depend on it.'))
                return redirect(request.path)

            if request.POST.get('delete_confirm') == '1':
                with request.changeset.lock_to_edit(request) as changeset:
                    if changeset.can_edit(request):
                        obj.delete()
                    else:
                        messages.error(request, _('You can not edit changes on this changeset.'))
                        return redirect(request.path)
                messages.success(request, _('Object was successfully deleted.'))
                if model == Level:
                    if obj.on_top_of_id is not None:
                        return redirect(reverse('editor.levels.detail', kwargs={'pk': obj.on_top_of_id}))
                    return redirect(reverse('editor.index'))
                elif model == Space:
                    return redirect(reverse('editor.spaces.list', kwargs={'level': obj.level.pk}))
                return redirect(ctx['back_url'])
            ctx['obj_title'] = obj.title
            return render(request, 'editor/delete.html', ctx)

        form = model.EditorForm(instance=model() if new else obj, data=request.POST,
                                request=request, space_id=space_id)
        if form.is_valid():
            # Update/create objects
            obj = form.save(commit=False)

            if level is not None:
                obj.level = level

            if space is not None:
                obj.space = space

            if on_top_of is not None:
                obj.on_top_of = on_top_of

            with request.changeset.lock_to_edit(request) as changeset:
                if changeset.can_edit(request):
                    try:
                        obj.save()
                    except IntegrityError:
                        messages.error(request, _('Duplicate entry.'))
                    else:
                        if form.redirect_slugs is not None:
                            for slug in form.add_redirect_slugs:
                                obj.redirects.create(slug=slug)

                            for slug in form.remove_redirect_slugs:
                                obj.redirects.filter(slug=slug).delete()

                        form.save_m2m()
                        messages.success(request, _('Object was successfully saved.'))
                        return redirect(ctx['back_url'])
                else:
                    messages.error(request, _('You can not edit changes on this changeset.'))

    else:
        form = model.EditorForm(instance=obj, request=request, space_id=space_id)

    ctx.update({
        'form': form,
    })

    return render(request, 'editor/edit.html', ctx)


def get_visible_spaces(request):
    cache_key = 'editor:visible_spaces:%s:%s' % (
        request.changeset.raw_cache_key_by_changes,
        AccessPermission.cache_key_for_request(request, with_update=False)
    )
    visible_spaces = cache.get(cache_key, None)
    if visible_spaces is None:
        Space = request.changeset.wrap_model('Space')
        visible_spaces = tuple(Space.qs_for_request(request).values_list('pk', flat=True))
        cache.set(cache_key, visible_spaces, 900)
    return visible_spaces


def get_visible_spaces_kwargs(model, request):
    kwargs = {}
    if hasattr(model, 'target_space'):
        visible_spaces = get_visible_spaces(request)
        kwargs['target_space_id__in'] = visible_spaces
        if hasattr(model, 'origin_space'):
            kwargs['origin_space_id__in'] = visible_spaces
    return kwargs


@sidebar_view
@etag(etag_func)
def list_objects(request, model=None, level=None, space=None, explicit_edit=False):
    if not request.resolver_match.url_name.endswith('.list'):
        raise ValueError('url_name does not end with .list')

    model = request.changeset.wrap_model(model)

    Level = request.changeset.wrap_model('Level')
    Space = request.changeset.wrap_model('Space')

    can_edit = request.changeset.can_edit(request)

    ctx = {
        'path': request.path,
        'model_name': model.__name__.lower(),
        'model_title': model._meta.verbose_name,
        'model_title_plural': model._meta.verbose_name_plural,
        'explicit_edit': explicit_edit,
        'can_edit': can_edit,
    }

    queryset = model.objects.all().order_by('id')
    if hasattr(model, 'q_for_request'):
        queryset = queryset.filter(model.q_for_request(request))
    reverse_kwargs = {}

    if level is not None:
        reverse_kwargs['level'] = level
        level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
        queryset = queryset.filter(level=level).defer('geometry')
        ctx.update({
            'back_url': reverse('editor.levels.detail', kwargs={'pk': level.pk}),
            'back_title': _('back to level'),
            'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
            'level': level,
            'level_url': request.resolver_match.url_name,
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
        })
    elif space is not None:
        reverse_kwargs['space'] = space
        sub_qs = Space.objects.filter(Space.q_for_request(request)).select_related('level').defer('geometry')
        space = get_object_or_404(sub_qs, pk=space)
        queryset = queryset.filter(space=space).filter(**get_visible_spaces_kwargs(model, request))

        try:
            model._meta.get_field('geometry')
        except FieldDoesNotExist:
            pass
        else:
            queryset = queryset.defer('geometry')

        try:
            model._meta.get_field('origin_space')
        except FieldDoesNotExist:
            pass
        else:
            queryset = queryset.select_related('origin_space')

        try:
            model._meta.get_field('target_space')
        except FieldDoesNotExist:
            pass
        else:
            queryset = queryset.select_related('target_space')

        ctx.update({
            'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
            'level': space.level,
            'level_url': 'editor.spaces.list',
            'space': space,
            'back_url': reverse('editor.spaces.detail', kwargs={'level': space.level.pk, 'pk': space.pk}),
            'back_title': _('back to space'),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
    else:
        ctx.update({
            'back_url': reverse('editor.index'),
            'back_title': _('back to overview'),
        })

    edit_url_name = request.resolver_match.url_name[:-4]+('detail' if explicit_edit else 'edit')
    for obj in queryset:
        reverse_kwargs['pk'] = obj.pk
        obj.edit_url = reverse(edit_url_name, kwargs=reverse_kwargs)
    reverse_kwargs.pop('pk', None)

    ctx.update({
        'create_url': reverse(request.resolver_match.url_name[:-4] + 'create', kwargs=reverse_kwargs),
        'objects': queryset,
    })

    return render(request, 'editor/list.html', ctx)


def connect_nodes(request, active_node, clicked_node, edge_settings_form):
    changeset_exceeded = get_changeset_exceeded(request)
    graphedge_changes = {}
    if changeset_exceeded:
        graphedge_changes = request.changeset.get_changed_objects_by_model('GraphEdge')

    new_connections = []
    new_connections.append((active_node, clicked_node, False))
    if not edge_settings_form.cleaned_data['oneway']:
        new_connections.append((clicked_node, active_node, True))

    instance = edge_settings_form.instance
    for from_node, to_node, is_reverse in new_connections:
        existing = from_node.edges_from_here.filter(to_node=to_node).first()
        if changeset_exceeded and (not existing or existing.pk not in graphedge_changes):
            messages.error(request, _('Could not edit edge because your changeset is full.'))
            return
        if existing is None:
            instance.pk = None
            instance.from_node = from_node
            instance.to_node = to_node
            instance.save()
            messages.success(request, _('Reverse edge created.') if is_reverse else _('Edge created.'))
        elif existing.waytype == instance.waytype and existing.access_restriction == instance.access_restriction:
            existing.delete()
            messages.success(request, _('Reverse edge deleted.') if is_reverse else _('Edge deleted.'))
        else:
            existing.waytype = instance.waytype
            existing.access_restriction = instance.access_restriction
            existing.save()
            messages.success(request, _('Reverse edge overwritten.') if is_reverse else _('Edge overwritten.'))


@sidebar_view
@etag(etag_func)
def graph_edit(request, level=None, space=None):
    Level = request.changeset.wrap_model('Level')
    Space = request.changeset.wrap_model('Space')
    GraphNode = request.changeset.wrap_model('GraphNode')
    GraphEdge = request.changeset.wrap_model('GraphEdge')

    can_edit = request.changeset.can_edit(request)

    ctx = {
        'path': request.path,
        'can_edit': can_edit,
        'levels': Level.objects.filter(Level.q_for_request(request), on_top_of__isnull=True),
        'level_url': 'editor.levels.graph',
    }

    create_nodes = False

    if level is not None:
        level = get_object_or_404(Level.objects.filter(Level.q_for_request(request)), pk=level)
        ctx.update({
            'back_url': reverse('editor.levels.detail', kwargs={'pk': level.pk}),
            'back_title': _('back to level'),
            'level': level,
            'geometry_url': '/api/editor/geometries/?level='+str(level.primary_level_pk),
        })
    elif space is not None:
        queryset = Space.objects.filter(Space.q_for_request(request)).select_related('level').defer('geometry')
        space = get_object_or_404(queryset, pk=space)
        level = space.level
        ctx.update({
            'space': space,
            'level': space.level,
            'back_url': reverse('editor.spaces.detail', kwargs={'level': level.pk, 'pk': space.pk}),
            'back_title': _('back to space'),
            'parent_url': reverse('editor.levels.graph', kwargs={'level': level.pk}),
            'parent_title': _('to level graph'),
            'geometry_url': '/api/editor/geometries/?space='+str(space.pk),
        })
        create_nodes = True

    if request.method == 'POST':
        changeset_exceeded = get_changeset_exceeded(request)
        graphnode_changes = {}
        if changeset_exceeded:
            graphnode_changes = request.changeset.get_changed_objects_by_model('GraphNode')

        if request.POST.get('delete') == '1':
            # Delete this graphnode!
            node = get_object_or_404(GraphNode, pk=request.POST.get('pk'))

            if changeset_exceeded and node.pk not in graphnode_changes:
                messages.error(request, _('You can not delete this graph node because your changeset is full.'))
                return redirect(request.path)

            if request.POST.get('delete_confirm') == '1':
                with request.changeset.lock_to_edit(request) as changeset:
                    if changeset.can_edit(request):
                        node.edges_from_here.all().delete()
                        node.edges_to_here.all().delete()
                        node.delete()
                    else:
                        messages.error(request, _('You can not edit changes on this changeset.'))
                        return redirect(request.path)
                messages.success(request, _('Graph Node was successfully deleted.'))
                return redirect(request.path)
            return render(request, 'editor/delete.html', {
                'model_title': GraphNode._meta.verbose_name,
                'pk': node.pk,
                'obj_title': node.title
            })

        permissions = AccessPermission.get_for_request(request) | set([None])
        edge_settings_form = GraphEdgeSettingsForm(instance=GraphEdge(), request=request, data=request.POST)
        graph_action_form = GraphEditorActionForm(request=request, allow_clicked_position=create_nodes,
                                                  data=request.POST)
        if edge_settings_form.is_valid() and graph_action_form.is_valid():
            goto_space = graph_action_form.cleaned_data['goto_space']
            if goto_space is not None:
                return redirect(reverse('editor.spaces.graph', kwargs={'space': goto_space.pk}))

            set_active_node = False
            active_node = graph_action_form.cleaned_data['active_node']
            clicked_node = graph_action_form.cleaned_data['clicked_node']
            clicked_position = graph_action_form.cleaned_data.get('clicked_position')
            if clicked_node is not None and clicked_position is None:
                if active_node is None:
                    active_node = clicked_node
                    set_active_node = True
                elif active_node == clicked_node:
                    active_node = None
                    set_active_node = True
                else:
                    with request.changeset.lock_to_edit(request) as changeset:
                        if changeset.can_edit(request):
                            connect_nodes(request, active_node, clicked_node, edge_settings_form)
                            active_node = clicked_node if edge_settings_form.cleaned_data['activate_next'] else None
                            set_active_node = True
                        else:
                            messages.error(request, _('You can not edit changes on this changeset.'))

            elif (clicked_node is None and clicked_position is not None and
                  active_node is None and space.geometry.contains(clicked_position)):

                if changeset_exceeded:
                    messages.error(request, _('You can not add graph nodes because your changeset is full.'))
                    return redirect(request.path)

                with request.changeset.lock_to_edit(request) as changeset:
                    if changeset.can_edit(request):
                        node = GraphNode(space=space, geometry=clicked_position)
                        node.save()
                        messages.success(request, _('New graph node created.'))

                        active_node = None
                        set_active_node = True
                    else:
                        messages.error(request, _('You can not edit changes on this changeset.'))

            if set_active_node:
                connections = {}
                if active_node:
                    for self_node, other_node in (('from_node', 'to_node'), ('to_node', 'from_node')):
                        conn_qs = GraphEdge.objects.filter(Q(**{self_node+'__pk': active_node.pk}))
                        conn_qs = conn_qs.select_related(other_node+'__space', other_node+'__space__level',
                                                         'waytype', 'access_restriction')

                        for edge in conn_qs:
                            edge.other_node = getattr(edge, other_node)
                            if (edge.other_node.space.access_restriction_id not in permissions
                                    or edge.other_node.space.level.access_restriction_id not in permissions):
                                continue
                            connections.setdefault(edge.other_node.space_id, []).append(edge)
                    connections = sorted(
                        connections.values(),
                        key=lambda c: (c[0].other_node.space.level == level,
                                       c[0].other_node.space == space,
                                       c[0].other_node.space.level.base_altitude)
                    )
                ctx.update({
                    'set_active_node': set_active_node,
                    'active_node': active_node,
                    'active_node_connections': connections,
                })
    else:
        edge_settings_form = GraphEdgeSettingsForm(request=request)

    graph_action_form = GraphEditorActionForm(request=request, allow_clicked_position=create_nodes)

    ctx.update({
        'edge_settings_form': edge_settings_form,
        'graph_action_form': graph_action_form,
        'create_nodes': create_nodes,
    })

    return render(request, 'editor/graph.html', ctx)


def sourceimage(request, filename):
    if not request.user.is_superuser:
        raise PermissionDenied

    if not can_access_editor(request):
        return PermissionDenied

    try:
        return HttpResponse(open(os.path.join(settings.SOURCES_ROOT, filename), 'rb'),
                            content_type=mimetypes.guess_type(filename)[0])
    except FileNotFoundError:
        raise Http404
