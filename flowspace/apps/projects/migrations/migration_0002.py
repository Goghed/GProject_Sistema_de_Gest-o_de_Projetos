from django.conf import settings
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0001_initial'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    # 0001_initial already creates the `manager` field (added there after this
    # migration was written) — kept as a no-op so the dependency graph and
    # already-applied databases stay intact, without re-adding the column.
    operations = []
