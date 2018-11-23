from django.contrib import messages
from django.contrib.auth import login, logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, PasswordChangeForm, UserCreationForm
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.translation import ugettext_lazy as _

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
            return redirect(redirect_path)
    else:
        form = AuthenticationForm(request)

    return render(request, 'editor/account_form.html', {
        'title': _('Log in'),
        'form': form,
        'bottom_link_url': reverse('site.register'),
        'bottom_link_text': _('Create new account')
    })


@sidebar_view
def logout_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.login')
    logout(request)
    return redirect(redirect_path)


@sidebar_view
def register_view(request):
    redirect_path = request.GET['r'] if request.GET.get('r', '').startswith('/editor/') else reverse('editor.index')
    if request.user.is_authenticated:
        return redirect(redirect_path)

    if request.method == 'POST':
        form = UserCreationForm(data=request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect(redirect_path)
    else:
        form = UserCreationForm()

    form.fields['username'].max_length = 20
    for field in form.fields.values():
        field.help_text = None

    return render(request, 'editor/account_form.html', {
        'title': _('Create new account'),
        'back_url': reverse('site.login'),
        'form': form
    })


@sidebar_view
@login_required(login_url='editor.login', redirect_field_name='r')
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(user=request.user, data=request.POST)
        if form.is_valid():
            form.save()
            login(request, request.user)
            messages.success(request, _('Password successfully changed.'))
            return redirect('editor.users.detail', pk=request.user.pk)

    else:
        form = PasswordChangeForm(user=request.user)

    for field in form.fields.values():
        field.help_text = None

    return render(request, 'editor/account_form.html', {
        'title': _('Change password'),
        'back_url': reverse('site.account'),
        'form': form
    })
