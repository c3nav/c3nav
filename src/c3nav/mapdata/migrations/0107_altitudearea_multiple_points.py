# Generated by Django 5.0.8 on 2024-08-17 17:50

import django.core.serializers.json
import django_pydantic_field.compat.django
import django_pydantic_field.fields
import types
import typing
from django.db import migrations, models
from shapely.geometry import Point

from c3nav.mapdata.models.geometry.level import AltitudeAreaPoint


def forwards_func(apps, schema_editor):
    AltitudeArea = apps.get_model('mapdata', 'AltitudeArea')
    for area in AltitudeArea.objects.all():
        if area.point1 is not None:
            area.points = [
                AltitudeAreaPoint(coordinates=[area.point1.x, area.point1.y], altitude=float(area.altitude)),
                AltitudeAreaPoint(coordinates=[area.point2.x, area.point2.y], altitude=float(area.altitude2))
            ]
            area.altitude = None
            area.save()


def backwards_func(apps, schema_editor):
    AltitudeArea = apps.get_model('mapdata', 'AltitudeArea')
    for area in AltitudeArea.objects.all():
        if area.points is not None:
            area.point1 = Point(*area.points[0].coordinates)
            area.point2 = Point(*area.points[-1].coordinates)
            area.altitude = area.points[0].altitude
            area.altitude2 = area.points[-1].altitude
            area.save()


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0106_rename_wifi_to_beaconmeasurement'),
    ]

    operations = [
        migrations.AddField(
            model_name='altitudearea',
            name='points',
            field=django_pydantic_field.fields.PydanticSchemaField(config=None, encoder=django.core.serializers.json.DjangoJSONEncoder, null=True, schema=django_pydantic_field.compat.django.GenericContainer(typing.Union, (django_pydantic_field.compat.django.GenericContainer(list, (AltitudeAreaPoint,)), types.NoneType))),
        ),
        migrations.AlterField(
            model_name='altitudearea',
            name='altitude',
            field=models.DecimalField(decimal_places=2, max_digits=6, null=True, verbose_name='altitude'),
        ),
        migrations.RunPython(forwards_func, backwards_func),
        migrations.RemoveField(
            model_name='altitudearea',
            name='altitude2',
        ),
        migrations.RemoveField(
            model_name='altitudearea',
            name='point1',
        ),
        migrations.RemoveField(
            model_name='altitudearea',
            name='point2',
        ),
    ]
