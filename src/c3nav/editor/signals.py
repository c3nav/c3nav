from c3nav.editor.models import ChangeSet


def set_changeset_author_on_login(sender, user, request, **kwargs):
    try:
        changeset = request.changeset
    except AttributeError:
        changeset = ChangeSet.get_for_request(request, as_logged_out=True)

    if changeset.pk is not None:
        changeset.author = user
        changeset.save()
