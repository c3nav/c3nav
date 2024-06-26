# Generated by Django 4.2.1 on 2023-11-10 14:38

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ("mesh", "0009_meshuplink"),
    ]

    operations = [
        migrations.CreateModel(
            name="OTAUpdate",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "created",
                    models.DateTimeField(auto_now_add=True, verbose_name="creation"),
                ),
                (
                    "build",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        to="mesh.firmwarebuild",
                    ),
                ),
            ],
        ),
        migrations.CreateModel(
            name="OTAUpdateRecipient",
            fields=[
                (
                    "id",
                    models.AutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                (
                    "node",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="ota_updates",
                        to="mesh.meshnode",
                        verbose_name="node",
                    ),
                ),
                (
                    "update",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="recipients",
                        to="mesh.otaupdate",
                    ),
                ),
            ],
        ),
    ]
