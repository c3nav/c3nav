from datetime import datetime

from django.contrib.auth import get_user_model
from django.core.handlers.wsgi import WSGIRequest
from ninja import Router as APIRouter

from c3nav.api.schema import StatsSchema
from c3nav.mapdata.models.report import Report

stats_api_router = APIRouter(tags=["stats"])


@stats_api_router.get('/stats/', auth=None, summary="get stats")
def stats(request: WSGIRequest) -> StatsSchema:
    return StatsSchema(
        users_total=get_user_model().objects.count(),
        reports_total=Report.objects.count(),
        reports_open=Report.objects.filter(open=True).count(),
        reports_today=Report.objects.filter(created__date=datetime.today().date()).count(),
    )
