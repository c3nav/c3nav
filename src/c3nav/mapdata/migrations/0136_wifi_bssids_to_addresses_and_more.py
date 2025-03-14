# Generated by Django 5.0.8 on 2024-12-28 14:15

import django.core.serializers.json
import django_pydantic_field.compat.django
import django_pydantic_field.fields
import pydantic_extra_types.mac_address
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0135_rangingbeacon_beacon_type'),
    ]

    operations = [
        migrations.RenameField(
            model_name='rangingbeacon',
            old_name='wifi_bssids',
            new_name='addresses',
        ),
        migrations.AlterField(
            model_name='rangingbeacon',
            name='addresses',
            field=django_pydantic_field.fields.PydanticSchemaField(config=None, default=list,
                                                                   encoder=django.core.serializers.json.DjangoJSONEncoder,
                                                                   help_text="uses node's value if not set",
                                                                   schema=django_pydantic_field.compat.django.GenericContainer(
                                                                       list,
                                                                       (pydantic_extra_types.mac_address.MacAddress,)),
                                                                   verbose_name='Mac Address / BSSIDs'),
        ),
        migrations.AlterField(
            model_name='rangingbeacon',
            name='ap_name',
            field=models.CharField(blank=True, max_length=32, null=True, verbose_name='AP name'),
        ),
    ]
