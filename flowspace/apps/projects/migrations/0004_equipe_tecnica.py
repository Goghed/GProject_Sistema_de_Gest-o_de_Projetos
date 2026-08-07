import uuid
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('projects', '0003_add_retrospective_fields'),
    ]

    operations = [
        migrations.CreateModel(
            name='EquipeTecnica',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('tecnico', models.CharField(max_length=100, verbose_name='Técnico')),
                ('auxiliar', models.CharField(blank=True, max_length=100, verbose_name='Auxiliar')),
                ('veiculo', models.CharField(blank=True, max_length=100, verbose_name='Veículo')),
                ('is_active', models.BooleanField(default=True, verbose_name='Ativa')),
                ('ordem', models.PositiveSmallIntegerField(default=0, verbose_name='Ordem de exibição')),
            ],
            options={
                'verbose_name': 'Equipe Técnica',
                'verbose_name_plural': 'Equipes Técnicas',
                'db_table': 'projects_equipe_tecnica',
                'ordering': ['ordem', 'tecnico'],
            },
        ),
        migrations.CreateModel(
            name='AtribuicaoEquipe',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('equipe', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='atribuicoes', to='projects.equipetecnica', verbose_name='Equipe')),
                ('projeto', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='atribuicoes_equipe', to='projects.project', verbose_name='Projeto')),
                ('posicao', models.PositiveSmallIntegerField(choices=[(0, 'Atualmente'), (1, 'Fila 1'), (2, 'Fila 2'), (3, 'Fila 3')], default=0, verbose_name='Posição na fila')),
                ('tipo_instalacao', models.CharField(blank=True, max_length=100, verbose_name='Tipo de instalação')),
                ('varejo_projeto', models.CharField(blank=True, max_length=50, verbose_name='Varejo/Projeto')),
                ('dias_execucao', models.CharField(blank=True, max_length=50, verbose_name='Dias de execução')),
                ('data_inicio', models.DateField(blank=True, null=True, verbose_name='Data de início')),
                ('data_termino', models.DateField(blank=True, null=True, verbose_name='Data de término')),
            ],
            options={
                'verbose_name': 'Atribuição de Equipe',
                'verbose_name_plural': 'Atribuições de Equipes',
                'db_table': 'projects_atribuicao_equipe',
                'ordering': ['equipe', 'posicao'],
            },
        ),
        migrations.AlterUniqueTogether(
            name='atribuicaoequipe',
            unique_together={('equipe', 'posicao')},
        ),
    ]
