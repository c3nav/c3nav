import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail

from c3nav.celery import app

logger = logging.getLogger('c3nav')


@app.task(bind=True, max_retries=3)
def send_changeset_proposed_notification(self, pk, author, title, description):
    subject = '[c3nav] New Changeset by %s: %s' % (author, title)
    for user in User.objects.filter(permissions__review_changesets=True):
        if not user.email:
            continue
        text = (
            ('Hi %s!\n\n' % user.username) +
            ('A new Changeset has been proposed by %s:\n\n' % author) +
            ('---\n\n') +
            (title+'\n\n'+description)
        )
        send_mail(subject, text, settings.MAIL_FROM, [user.email])
