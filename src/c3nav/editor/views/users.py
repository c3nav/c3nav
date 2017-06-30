from django.contrib.auth.models import User
from django.db.models import Max
from django.shortcuts import get_object_or_404, render

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view


@sidebar_view
def user_detail(request, pk):
    user = request.user
    if str(pk) != str(user.pk):
        user = get_object_or_404(User, pk=pk)

    qs = ChangeSet.objects.filter(author=user)
    qs = qs.annotate(last_change_cache=Max('changed_objects_set__last_update')).order_by('-last_change_cache')

    ctx = {
        'user': user,
        'changesets': qs,
    }

    return render(request, 'editor/user.html', ctx)
