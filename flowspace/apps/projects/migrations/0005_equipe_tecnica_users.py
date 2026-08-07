import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0004_equipe_tecnica'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='equipetecnica',
            name='tecnico_user',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='equipes_tecnico',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Técnico (usuário do sistema)',
            ),
        ),
        migrations.AddField(
            model_name='equipetecnica',
            name='auxiliar_user',
            field=models.ForeignKey(
                blank=True, null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='equipes_auxiliar',
                to=settings.AUTH_USER_MODEL,
                verbose_name='Auxiliar (usuário do sistema)',
            ),
        ),
    ]
