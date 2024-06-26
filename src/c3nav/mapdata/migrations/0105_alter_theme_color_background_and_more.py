# Generated by Django 5.0.1 on 2024-03-30 18:02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0104_theme_color_css_grid_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='theme',
            name='color_background',
            field=models.CharField(blank=True, max_length=32, verbose_name='background color'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_door_fill',
            field=models.CharField(blank=True, max_length=32, verbose_name='door fill color'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_ground_fill',
            field=models.CharField(blank=True, max_length=32, verbose_name='ground fill color'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_obstacles_default_border',
            field=models.CharField(blank=True, max_length=32, verbose_name='default border color for obstacles'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_obstacles_default_fill',
            field=models.CharField(blank=True, max_length=32, verbose_name='default fill color for obstacles'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_wall_border',
            field=models.CharField(blank=True, max_length=32, verbose_name='wall border color'),
        ),
        migrations.AlterField(
            model_name='theme',
            name='color_wall_fill',
            field=models.CharField(blank=True, max_length=32, verbose_name='wall fill color'),
        ),
    ]
