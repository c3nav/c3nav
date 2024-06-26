# Generated by Django 4.2.1 on 2023-10-03 15:31

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('mesh', '0005_meshnode_last_signin'),
    ]

    operations = [
        migrations.RenameField(
            model_name='meshnode',
            old_name='route',
            new_name='uplink',
        ),
        migrations.AlterField(
            model_name='meshnode',
            name='uplink',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='routed_nodes',
                                    to='mesh.meshnode', verbose_name='uplink'),
        ),
    ]
