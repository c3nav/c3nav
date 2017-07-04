from django.contrib.auth import login, logout
from django.contrib.auth.forms import AuthenticationForm
from django.shortcuts import redirect, render
from django.urls import reverse

from c3nav.editor.views.base import sidebar_view


@sidebar_view
def login_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.index')
    if request.user.is_authenticated:
        return redirect(redirect_path)

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            login(request, form.user_cache)

            if request.changeset.pk is not None:
                request.changeset.author = form.user_cache
                request.changeset.save()
            return redirect(redirect_path)
    else:
        form = AuthenticationForm(request)

    return render(request, 'editor/login.html', {'form': form})


@sidebar_view
def logout_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.login')
    logout(request)
    return redirect(redirect_path)
