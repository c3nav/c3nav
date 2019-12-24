import logging

from django.conf import settings
from django.contrib.auth.models import User
from django.core.mail import send_mail

from c3nav.celery import app

logger = logging.getLogger('c3nav')


@app.task(bind=True, max_retries=3)
def send_report_notification(self, pk, author, title, description, reviewers):
    subject = '[c3nav] New Report by %s: %s' % (author, title)

    for user in User.objects.filter(pk=reviewers):
        if not user.email:
            continue
        text = (
            ('Hi %s!\n\n' % user.username) +
            ('A new Report has ben submitted by %s:\n\n' % author) +
            ('---\n\n') +
            (title+'\n\n'+description)
        )
        send_mail(subject, text, settings.MAIL_FROM, [user.email])
