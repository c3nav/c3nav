# Generated by Django 5.1.3 on 2024-12-29 18:36

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('mapdata', '0137_position_short_name'),
    ]

    operations = [
        migrations.AddField(
            model_name='rangingbeacon',
            name='max_observed_num_clients',
            field=models.IntegerField(default=0, verbose_name='highest observed number of clients'),
        ),
        migrations.AddField(
            model_name='rangingbeacon',
            name='num_clients',
            field=models.IntegerField(default=0, verbose_name='current number of clients'),
        ),
    ]
