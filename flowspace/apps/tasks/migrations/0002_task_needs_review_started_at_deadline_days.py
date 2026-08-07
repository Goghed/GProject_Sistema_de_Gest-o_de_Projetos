from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0001_initial'),
    ]

    operations = [
        migrations.AddField(
            model_name='task',
            name='needs_review',
            field=models.BooleanField(default=False, help_text='Precisa passar por revisão antes de concluir'),
        ),
        migrations.AddField(
            model_name='task',
            name='started_at',
            field=models.DateTimeField(blank=True, null=True, help_text='Quando a tarefa foi iniciada'),
        ),
        migrations.AddField(
            model_name='task',
            name='deadline_days',
            field=models.PositiveIntegerField(blank=True, null=True, help_text='Prazo estimado em dias úteis'),
        ),
    ]
