from c3nav.celery import app


@app.task()
def request_access_token(hoster, *args, **kwargs):
    from c3nav.editor.hosters import hosters
    return hosters[hoster].do_request_access_token(*args, **kwargs)


@app.task()
def check_access_token(hoster, access_token):
    from c3nav.editor.hosters import hosters
    return hosters[hoster].do_check_access_token(access_token)


@app.task()
def submit_edit(hoster, access_token, data):
    from c3nav.editor.hosters import hosters
    return hosters[hoster].do_submit_edit(access_token, data)
