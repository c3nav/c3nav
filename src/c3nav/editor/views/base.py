from contextlib import contextmanager
from functools import wraps

from django.contrib.messages import get_messages
from django.core.exceptions import PermissionDenied
from django.http import HttpResponseNotModified, HttpResponseRedirect
from django.shortcuts import render
from django.utils.cache import patch_vary_headers
from django.utils.translation import get_language

from c3nav.editor.models import ChangeSet
from c3nav.editor.overlay import DatabaseOverlayManager
from c3nav.mapdata.models import MapUpdate
from c3nav.mapdata.models.access import AccessPermission
from c3nav.mapdata.utils.cache.changes import changed_geometries
from c3nav.mapdata.utils.user import can_access_editor


@contextmanager
def maybe_lock_changeset_to_edit(changeset):
    """ Lock the changeset of the given request, if it can be locked (= has ever been saved to the database)"""
    if changeset.pk:
        with changeset.lock_to_edit() as locked_changeset:
            yield locked_changeset
    else:
        yield changeset


@contextmanager
def within_changeset(changeset, user):
    with maybe_lock_changeset_to_edit(changeset=changeset) as locked_changeset:
        # Turn the changes from the changeset into a list of operations
        operations = locked_changeset.as_operations

        # Enable the overlay manager, temporarily applying the changeset changes
        # commit is set to false, meaning all changes will be reset once we leave the manager
        with DatabaseOverlayManager.enable(operations=operations, commit=False) as manager:
            yield locked_changeset
        if manager.operations:
            # Add new operations to changeset
            locked_changeset.changes.add_operations(manager.operations)
            locked_changeset.save()

            # Add new changeset update
            update = locked_changeset.updates.create(user=user, objects_changed=True)
            locked_changeset.last_update = update
            locked_changeset.last_change = update
            locked_changeset.save()


@contextmanager
def noctx():
    yield


def accesses_mapdata(func):
    """
    Decorator for editor views that access map data, will honor changesets etc
    """
    @wraps(func)
    def wrapped(request, *args, **kwargs):
        # Omly POST and PUT methods may actually commit changes to the database
        writable_method = request.method in ("POST", "PUT")

        if request.changeset.direct_editing:
            # For direct editing, a mapupdate is created if any changes are made
            # So, if this request may commit changes, lock the MapUpdate system, which also starts a transaction.
            with (MapUpdate.lock() if writable_method else noctx()):
                # Reset the changed geometries tracker, this will be read when a MapUpdate is created.
                changed_geometries.reset()

                # Enable the overlay manager to monitor changes, so we know if any changes even happened
                # If this request may commit changes, commit is set to True, so everything will be commited.
                with DatabaseOverlayManager.enable(operations=None, commit=writable_method) as manager:
                    result = func(request, *args, **kwargs)

                # If any operations took place, we create a MapUpdate
                if manager.operations:
                    if writable_method:
                        MapUpdate.objects.create(user=request.user, type='direct_edit')
                    else:
                        # todo: time for a good error message, even though this case should not be possible
                        raise ValueError  # todo: good error message, but this shouldn't happen
        else:
            # For non-direct editing, we will interact with the changeset
            with within_changeset(changeset=request.changeset, user=request.user) as locked_changeset:
                request.changeset = locked_changeset
                return func(request, *args, **kwargs)
        return result

    return wrapped


def sidebar_view(func=None, select_related=None):
    if func is None:
        def wrapped(inner_func):
            return sidebar_view(inner_func, select_related=select_related)
        return wrapped

    @wraps(func)
    def wrapped(request, *args, **kwargs):
        if not can_access_editor(request):
            raise PermissionDenied

        if getattr(request, "changeset", None) is None:
            request.changeset = ChangeSet.get_for_request(request, select_related)

        ajax = request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET
        if not ajax:
            request.META.pop('HTTP_IF_NONE_MATCH', None)

        response = func(request, *args, **kwargs)

        if ajax:
            if isinstance(response, HttpResponseRedirect):
                return render(request, 'editor/redirect.html', {'target': response['location']})
            if not isinstance(response, HttpResponseNotModified):
                response.write(render(request, 'editor/fragment_nav.html', {}).content)
                if request.mobileclient:
                    response.write(render(request, 'editor/fragment_mobileclientdata.html', {}).content)
            response['Cache-Control'] = 'no-cache'
            patch_vary_headers(response, ('X-Requested-With', ))
            return response
        if isinstance(response, HttpResponseRedirect):
            return response
        response = render(request, 'editor/map.html', {'content': response.content.decode()})
        response['Cache-Control'] = 'no-cache'
        patch_vary_headers(response, ('X-Requested-With', ))
        return response

    return wrapped

gi
def editor_etag_func(request, *args, **kwargs):
    try:
        changeset = request.changeset
    except AttributeError:
        changeset = ChangeSet.get_for_request(request)
        request.changeset = changeset

    if len(get_messages(request)):
        return None

    return (get_language() + ':' + changeset.raw_cache_key_by_changes + ':' +
            AccessPermission.cache_key_for_request(request, with_update=False) + ':' + str(request.user.pk or 0)
            + ':' + str(int(request.user_permissions.can_access_base_mapdata))
            + ':' + ','.join(str(i) for i in request.user_space_accesses)
            + ':' + str(int(request.user.is_superuser))
            + ':' + str(int(request.headers.get('x-requested-with') == 'XMLHttpRequest' or 'ajax' in request.GET)))
