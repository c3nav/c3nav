# -*- coding: utf-8 -*-
# Generated by Django 1.11.7 on 2017-12-20 19:44
from __future__ import unicode_literals

import c3nav.mapdata.fields
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0064_access_permission_unique_key'),
    ]

    operations = [
        migrations.CreateModel(
            name='AccessRestrictionGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', c3nav.mapdata.fields.I18nField(blank=True, fallback_any=True, fallback_value='{model} {pk}', plural_name='titles', verbose_name='Title')),
            ],
            options={
                'verbose_name': 'Access Restriction Group',
                'verbose_name_plural': 'Access Restriction Groups',
                'default_related_name': 'accessrestrictiongroups',
            },
        ),
        migrations.AddField(
            model_name='accessrestriction',
            name='groups',
            field=models.ManyToManyField(blank=True, related_name='accessrestrictions', to='mapdata.AccessRestrictionGroup', verbose_name='Groups'),
        ),
    ]
