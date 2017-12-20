import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail

from c3nav.celery import app

logger = logging.getLogger('c3nav')


@app.task(bind=True, max_retries=3)
def send_changeset_proposed_notification(self, changeset):
    subject = '[c3nav] New Changeset by %s: %s' % (changeset.author.username, changeset.title)
    for user in User.objects.filter(permissions__review_changesets=True):
        if not user.email:
            continue
        text = (
            ('Hi %s!\n\n' % user.username) +
            ('A new Changeset has been proposed by %s:\n\n' % changeset.author.username) +
            ('---\n\n') +
            (changeset.title+'\n\n'+changeset.description)
        )
        send_mail(subject, text, settings.MAIL_FROM, [user.email])
