from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('tasks', '0001_initial'),
    ]

    # 0001_initial already creates needs_review/started_at/deadline_days
    # (added there after this migration was written) — kept as a no-op so the
    # dependency graph and already-applied databases stay intact.
    operations = []
