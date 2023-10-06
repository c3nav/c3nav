# Generated by Django 4.0.3 on 2022-04-15 18:52

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='MeshNode',
            fields=[
                ('address', models.CharField(max_length=17, primary_key=True, serialize=False, verbose_name='mac address')),
                ('first_seen', models.DateTimeField(auto_now_add=True, verbose_name='first seen')),
                ('parent_node', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='child_nodes', to='mesh.meshnode', verbose_name='parent node')),
                ('route', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='routed_nodes', to='mesh.meshnode', verbose_name='route')),
            ],
        ),
        migrations.CreateModel(
            name='NodeMessage',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('datetime', models.DateTimeField(auto_now_add=True, db_index=True, verbose_name='datetime')),
                ('message_type', models.SmallIntegerField(choices=[(1, 'ECHO_REQUEST'), (2, 'ECHO_RESPONSE'), (3, 'MESH_SIGNIN'), (4, 'MESH_LAYER_ANNOUNCE'), (5, 'MESH_ADD_DESTINATIONS'), (6, 'MESH_REMOVE_DESTINATIONS'), (16, 'CONFIG_DUMP'), (17, 'CONFIG_FIRMWARE'), (18, 'CONFIG_POSITION'), (19, 'CONFIG_LED'), (20, 'CONFIG_UPLINK')], db_index=True, verbose_name='message type')),
                ('data', models.JSONField(verbose_name='message data')),
                ('node', models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='received_messages', to='mesh.meshnode', verbose_name='node')),
            ],
        ),
        migrations.CreateModel(
            name='Firmware',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('chip', models.SmallIntegerField(choices=[(2, 'ESP32-S2'), (5, 'ESP32-C3')], db_index=True, verbose_name='chip')),
                ('project_name', models.CharField(max_length=32, verbose_name='project name')),
                ('version', models.CharField(max_length=32, verbose_name='firmware version')),
                ('idf_version', models.CharField(max_length=32, verbose_name='IDF version')),
                ('compile_time', models.DateTimeField(verbose_name='compile time')),
                ('sha256_hash', models.CharField(max_length=64, unique=True, verbose_name='SHA256 hash')),
                ('binary', models.FileField(null=True, upload_to='', verbose_name='firmware file')),
            ],
            options={
                'unique_together': {('chip', 'project_name', 'version', 'idf_version', 'compile_time', 'sha256_hash')},
            },
        ),
    ]