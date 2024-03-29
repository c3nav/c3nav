# Generated by Django 4.2.7 on 2024-01-02 19:57

import c3nav.mapdata.fields
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0098_report_import_tag'),
    ]

    operations = [
        migrations.CreateModel(
            name='ObstacleGroup',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', c3nav.mapdata.fields.I18nField(blank=True, fallback_any=True, fallback_value='{model} {pk}', plural_name='titles', verbose_name='Title')),
                ('color', models.CharField(blank=True, max_length=32, null=True)),
            ],
            options={
                'verbose_name': 'Obstacle Group',
                'verbose_name_plural': 'Obstacle Groups',
                'default_related_name': 'groups',
            },
        ),
        migrations.CreateModel(
            name='Theme',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('title', c3nav.mapdata.fields.I18nField(blank=True, fallback_any=True, fallback_value='{model} {pk}', plural_name='titles', verbose_name='Title')),
                ('description', models.TextField(verbose_name='Description')),
                ('public', models.BooleanField(default=False, verbose_name='Public')),
                ('color_background', models.CharField(max_length=32, verbose_name='background color')),
                ('color_wall_fill', models.CharField(max_length=32, verbose_name='wall fill color')),
                ('color_wall_border', models.CharField(max_length=32, verbose_name='wall border color')),
                ('color_door_fill', models.CharField(max_length=32, verbose_name='door fill color')),
                ('color_ground_fill', models.CharField(max_length=32, verbose_name='ground fill color')),
                ('color_obstacles_default_fill', models.CharField(max_length=32, verbose_name='default fill color for obstacles')),
                ('color_obstacles_default_border', models.CharField(max_length=32, verbose_name='default border color for obstacles')),
                ('last_updated', models.DateTimeField(auto_now=True)),
            ],
            options={
                'verbose_name': 'Theme',
                'verbose_name_plural': 'Themes',
                'default_related_name': 'themes',
            },
        ),
        migrations.CreateModel(
            name='ThemeObstacleGroupBackgroundColor',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fill_color', models.CharField(blank=True, max_length=32, null=True)),
                ('border_color', models.CharField(blank=True, max_length=32, null=True)),
                ('obstacle_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='theme_colors', to='mapdata.obstaclegroup')),
                ('theme', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='obstacle_groups', to='mapdata.theme')),
            ],
        ),
        migrations.CreateModel(
            name='ThemeLocationGroupBackgroundColor',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('fill_color', models.CharField(blank=True, max_length=32, null=True)),
                ('border_color', models.CharField(blank=True, max_length=32, null=True)),
                ('location_group', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='theme_colors', to='mapdata.locationgroup')),
                ('theme', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='location_groups', to='mapdata.theme')),
            ],
        ),
        migrations.AddField(
            model_name='lineobstacle',
            name='group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='mapdata.obstaclegroup'),
        ),
        migrations.AddField(
            model_name='obstacle',
            name='group',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='mapdata.obstaclegroup'),
        ),
    ]
