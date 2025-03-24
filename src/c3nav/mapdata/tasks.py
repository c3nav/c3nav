import logging

from django.contrib.auth import get_user_model

from c3nav.celery import app

logger = logging.getLogger('c3nav')


@app.task(bind=True)
def schedule_available_mapupdate_jobs(self):
    from c3nav.mapdata.updatejobs import schedule_available_mapupdate_jobs_as_tasks
    schedule_available_mapupdate_jobs_as_tasks()


@app.task(bind=True)
def run_mapupdate_job(self, job_type: str):
    from c3nav.mapdata.updatejobs import run_job, CantStartMapUpdateJob
    try:
        run_job(job_type, schedule_next=True)
    except CantStartMapUpdateJob:
        logger.info(f'Cannot run job: {job_type}')


@app.task(bind=True, max_retries=10)
def update_ap_names_bssid_mapping(self, map_name, user_id):
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None:
        return
    from c3nav.mapdata.models.geometry.space import RangingBeacon
    todo = []
    for beacon in RangingBeacon.objects.filter(ap_name__in=map_name.keys(),
                                               beacon_type=RangingBeacon.BeaconType.EVENT_WIFI):
        print(beacon, "add ssids", set(map_name[beacon.ap_name]))
        if set(map_name[beacon.ap_name]) - set(beacon.addresses):
            todo.append((beacon, list(set(beacon.addresses) | set(map_name[beacon.ap_name]))))

    if todo:
        from c3nav.editor.models import ChangeSet
        from c3nav.editor.views.base import within_changeset
        changeset = ChangeSet()
        changeset.author = user
        with within_changeset(changeset=changeset, user=user) as locked_changeset:
            for beacon, addresses in todo:
                beacon.addresses = addresses
                beacon.save()
        with changeset.lock_to_edit() as locked_changeset:
            locked_changeset.title = 'passive update bssids'
            locked_changeset.apply(user)
