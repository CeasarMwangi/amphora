# -*- coding: utf-8 -*-
# Generated by Django 1.9.8 on 2016-07-29 18:04
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('cookies', '0009_value'),
    ]

    operations = [
        migrations.AlterField(
            model_name='conceptentity',
            name='concept',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, to='concepts.Concept'),
        ),
    ]
