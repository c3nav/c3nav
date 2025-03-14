# Generated by Django 5.0.8 on 2024-12-12 22:28

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('control', '0014_userpermissions_sources_access'),
    ]

    operations = [
        migrations.AddField(
            model_name='userpermissions',
            name='view_users',
            field=models.BooleanField(default=False, verbose_name='view user list in control panel'),
        ),
        migrations.AlterField(
            model_name='userpermissions',
            name='max_changeset_changes',
            field=models.PositiveSmallIntegerField(default=20, verbose_name='max changes per changeset'),
        ),
    ]
