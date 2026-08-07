from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0008_task_dependency'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='work_saturday',
            field=models.BooleanField(default=False, help_text='Sábado é dia útil para esta tarefa'),
        ),
        migrations.AddField(
            model_name='task',
            name='work_sunday',
            field=models.BooleanField(default=False, help_text='Domingo é dia útil para esta tarefa'),
        ),
    ]
