# -*- coding: utf-8 -*-
# Generated by Django 1.9.6 on 2016-11-04 13:50
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('cookies', '0024_auto_20161016_1047'),
    ]

    operations = [
        migrations.AddField(
            model_name='userjob',
            name='progress',
            field=models.FloatField(default=0.0),
        ),
    ]
