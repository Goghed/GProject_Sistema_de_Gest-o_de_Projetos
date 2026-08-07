from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0005_equipe_tecnica_users'),
    ]

    operations = [
        migrations.AddField(
            model_name='equipetecnica',
            name='foto',
            field=models.ImageField(
                blank=True, null=True,
                upload_to='equipes/fotos/',
                verbose_name='Foto do Técnico',
            ),
        ),
    ]
