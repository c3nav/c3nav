from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, render

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view


@sidebar_view
def user_detail(request, pk):
    user = request.user
    if str(pk) != str(user.pk):
        user = get_object_or_404(User, pk=pk)

    qs = ChangeSet.objects.filter(author=user).order_by('-last_update')[:10]

    ctx = {
        'user': user,
        'changesets': qs,
    }

    return render(request, 'editor/user.html', ctx)
