from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.utils.translation import ugettext_lazy as _

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view


@sidebar_view
def user_detail(request, pk):
    user = request.user
    if str(pk) != str(user.pk):
        user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        if request.POST.get('deactivate_changeset') == '1' and request.user == user and 'changeset' in request.session:
            request.session.pop('changeset', None)
            messages.success(request, _('You deactivated your current changeset.'))
            return redirect(request.path)

    ctx = {
        'user': user,
        'recent_changesets': ChangeSet.objects.filter(author=user).order_by('-last_update')[:10],
    }

    return render(request, 'editor/user.html', ctx)
