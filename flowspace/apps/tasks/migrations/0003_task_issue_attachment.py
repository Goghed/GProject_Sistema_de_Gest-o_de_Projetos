import django.db.models.deletion
import uuid
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0002_task_needs_review_started_at_deadline_days'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # Campo is_blocked na Task
        migrations.AddField(
            model_name='task',
            name='is_blocked',
            field=models.BooleanField(default=False, db_index=True),
        ),

        # Modelo TaskIssue
        migrations.CreateModel(
            name='TaskIssue',
            fields=[
                ('id',               models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('description',      models.TextField()),
                ('manager_response', models.TextField(blank=True)),
                ('responded_at',     models.DateTimeField(blank=True, null=True)),
                ('resolved',         models.BooleanField(default=False)),
                ('created_at',       models.DateTimeField(auto_now_add=True)),
                ('task',             models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='issues', to='tasks.task')),
                ('reported_by',      models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reported_issues', to=settings.AUTH_USER_MODEL)),
                ('responded_by',     models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='responded_issues', to=settings.AUTH_USER_MODEL)),
                ('support_task',     models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='origin_issue', to='tasks.task')),
            ],
            options={'db_table': 'tasks_issue', 'ordering': ['-created_at']},
        ),

        # Modelo TaskAttachment
        migrations.CreateModel(
            name='TaskAttachment',
            fields=[
                ('id',          models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False, serialize=False)),
                ('file',        models.FileField(upload_to='task_attachments/%Y/%m/')),
                ('filename',    models.CharField(max_length=255)),
                ('file_size',   models.PositiveIntegerField(default=0)),
                ('is_image',    models.BooleanField(default=False)),
                ('created_at',  models.DateTimeField(auto_now_add=True)),
                ('task',        models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='attachments', to='tasks.task')),
                ('uploaded_by', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
            ],
            options={'db_table': 'tasks_attachment', 'ordering': ['-created_at']},
        ),
    ]
