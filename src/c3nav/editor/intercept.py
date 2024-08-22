from contextlib import contextmanager
from functools import wraps

from django.db import transaction

from c3nav.editor.models import ChangeSet

try:
    from asgiref.local import Local as LocalContext
except ImportError:
    from threading import local as LocalContext


intercept = LocalContext()


class InterceptAbortTransaction(Exception):
    pass


@contextmanager
def enable_changeset_overlay(changeset):
    try:
        with transaction.atomic():
            # todo: apply changes so far
            yield
            raise InterceptAbortTransaction
    except InterceptAbortTransaction:
        pass
