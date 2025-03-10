from django.contrib import messages
from django.contrib.auth.models import User
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.translation import gettext_lazy as _

from c3nav.editor.models import ChangeSet
from c3nav.editor.views.base import sidebar_view


@sidebar_view
def user_detail(request, pk):
    user = request.user
    if str(pk) != str(user.pk):
        user = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        if request.user == user:
            if 'changeset' in request.session and request.POST.get('deactivate_changeset') == '1':
                request.session.pop('changeset', None)
                messages.success(request, _('You deactivated your current changeset.'))
                return redirect(request.path)

            if request.changeset.pk is None and ChangeSet.can_direct_edit(request):
                if request.POST.get('direct_editing') == '1':
                    request.session['direct_editing'] = True
                    messages.success(request, _('You activated direct editing.'))
                    return redirect(request.path)
                elif request.POST.get('direct_editing') == '0':
                    request.session.pop('direct_editing', None)
                    messages.success(request, _('You deactivated direct editing.'))
                    return redirect(request.path)

    ctx = {
        'user': user,
        'can_direct_edit': ChangeSet.can_direct_edit(request),
        'recent_changesets': ChangeSet.objects.filter(author=user).order_by('-last_update')[:15],
    }

    if request.user_permissions.review_changesets:
        ctx.update({
            'can_review': True,
            'reviewing_changesets': ChangeSet.objects.filter(
                assigned_to=user, state='review'
            ).order_by('-last_update'),
            'to_review_changesets': ChangeSet.objects.filter(
                state__in=('proposed', 'reproposed'),
            ).order_by('-last_update'),
            'all_recent_changesets': ChangeSet.objects.exclude(state='unproposed').order_by('-last_update')[:20],
        })

    return render(request, 'editor/user.html', ctx)


@sidebar_view
def user_redirect(request):
    user = request.user
    if user.is_authenticated:
        return redirect(reverse('editor.users.detail', kwargs={'pk': request.user.pk}))
    return redirect(reverse('editor.login'))
