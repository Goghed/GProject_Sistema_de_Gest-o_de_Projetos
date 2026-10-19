import uuid
from django.db import models
from django.conf import settings
from django.contrib.auth import get_user_model

COLOR_CHOICES = [
    ("#5b4cf5","Violeta"),("#0ea5e9","Azul"),("#34d399","Verde"),
    ("#fbbf24","Âmbar"),("#ff6b6b","Coral"),("#a855f7","Roxo"),
    ("#ec4899","Rosa"),("#14b8a6","Teal"),
]

CIDADE_CHOICES = [("londrina", "Londrina"), ("itu", "Itu")]

class Project(models.Model):
    STATUS_CHOICES = [
        ("active","Ativo"),("on_hold","Em Pausa"),
        ("completed","Concluído"),("archived","Arquivado"),
    ]
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name        = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    color       = models.CharField(max_length=7, default="#5b4cf5")
    status      = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")
    owner       = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name="owned_projects")
    # Gestor do projeto — responsável por criar e gerir tarefas
    manager     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, blank=True, related_name="managed_projects")
    members     = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                         related_name="projects", blank=True)
    scope       = models.TextField(blank=True, help_text="Escopo detalhado do projeto")
    cover_image = models.ImageField(upload_to="projects/covers/", null=True, blank=True)
    went_well   = models.TextField(blank=True, help_text="O que deu certo no projeto (retrospectiva)")
    went_wrong  = models.TextField(blank=True, help_text="O que não deu certo / deve ser evitado (retrospectiva)")
    cidade      = models.CharField(max_length=20, choices=CIDADE_CHOICES, blank=True, default="", verbose_name="Cidade")
    start_date  = models.DateField(null=True, blank=True)
    due_date    = models.DateField(null=True, blank=True)
    created_at  = models.DateTimeField(auto_now_add=True)
    updated_at  = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "projects_project"
        ordering = ["-created_at"]

    def __str__(self):
        return self.name

    @property
    def task_count(self):
        return self.tasks.count()

    @property
    def completed_count(self):
        return self.tasks.filter(status="done").count()

    @property
    def progress(self):
        total = self.task_count
        if not total:
            return 0
        return int(self.completed_count / total * 100)

    def can_create_tasks(self, user):
        """Retorna True se o usuário pode criar tarefas neste projeto."""
        if user.role in ("owner", "admin"):
            return True
        if self.manager_id and self.manager_id == user.id:
            return True
        return False


class ProjectMemberActivity(models.Model):
    """Atividade/função de cada membro dentro do projeto."""
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project  = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="member_activities")
    user     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="project_activities")
    activity = models.CharField(max_length=300, blank=True, help_text="O que este membro irá fazer no projeto")

    class Meta:
        db_table        = "projects_member_activity"
        unique_together = [("project", "user")]

    def __str__(self):
        return f"{self.user} em {self.project.name}"


class Column(models.Model):
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project  = models.ForeignKey(Project, on_delete=models.CASCADE, related_name="columns")
    name     = models.CharField(max_length=100)
    color    = models.CharField(max_length=7, default="#8888aa")
    position = models.PositiveIntegerField(default=0)
    is_done_column = models.BooleanField(default=False)

    class Meta:
        db_table = "projects_column"
        ordering = ["position"]

    def __str__(self):
        return f"{self.project.name} → {self.name}"

User = get_user_model()


class EquipeTecnica(models.Model):
    STATUS_CHOICES = [
        ("ativa",   "Ativa"),
        ("inativa", "Inativa"),
        ("ferias",  "Férias"),
    ]
    id            = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    tecnico       = models.CharField(max_length=100, verbose_name="Nome do Técnico")
    tecnico_user  = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="equipes_tecnico",
        verbose_name="Técnico (usuário do sistema)",
    )
    auxiliar      = models.CharField(max_length=100, blank=True, verbose_name="Nome do Auxiliar")
    auxiliar_user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="equipes_auxiliar",
        verbose_name="Auxiliar (usuário do sistema)",
    )
    foto      = models.ImageField(upload_to="equipes/fotos/", null=True, blank=True, verbose_name="Foto do Técnico")
    foto_auxiliar = models.ImageField(upload_to="equipes/fotos/", null=True, blank=True, verbose_name="Foto do Auxiliar")
    veiculo   = models.CharField(max_length=100, blank=True, verbose_name="Veículo")
    placa     = models.CharField(max_length=10, blank=True, verbose_name="Placa do Veículo")
    cidade    = models.CharField(max_length=20, choices=CIDADE_CHOICES, blank=True, default="", verbose_name="Cidade")
    status    = models.CharField(max_length=10, choices=STATUS_CHOICES, default="ativa", verbose_name="Status")
    ordem     = models.PositiveSmallIntegerField(default=0, verbose_name="Ordem de exibição")

    class Meta:
        db_table = "projects_equipe_tecnica"
        ordering = ["ordem", "tecnico"]
        verbose_name = "Equipe Técnica"
        verbose_name_plural = "Equipes Técnicas"

    def __str__(self):
        return f"Equipe {self.tecnico}"

    @property
    def tecnico_display(self):
        if self.tecnico_user_id:
            return self.tecnico_user.get_full_name() or self.tecnico_user.username
        return self.tecnico

    @property
    def auxiliar_display(self):
        if self.auxiliar_user_id:
            return self.auxiliar_user.get_full_name() or self.auxiliar_user.username
        return self.auxiliar

    def membros_sistema(self):
        """Retorna lista de usuários vinculados à equipe."""
        return [u for u in [self.tecnico_user, self.auxiliar_user] if u]


class AtribuicaoEquipe(models.Model):
    POSICAO_CHOICES = [
        (0, "Atualmente"),
        (1, "Fila 1"),
        (2, "Fila 2"),
        (3, "Fila 3"),
    ]
    id              = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    equipe          = models.ForeignKey(EquipeTecnica, on_delete=models.CASCADE, related_name="atribuicoes")
    projeto         = models.ForeignKey("Project", on_delete=models.SET_NULL, null=True, blank=True, related_name="atribuicoes_equipe", verbose_name="Projeto")
    posicao         = models.PositiveSmallIntegerField(choices=POSICAO_CHOICES, default=0, verbose_name="Posição na fila")
    tipo_instalacao = models.CharField(max_length=100, blank=True, verbose_name="Tipo de instalação")
    varejo_projeto  = models.CharField(max_length=50, blank=True, verbose_name="Varejo/Projeto")
    dias_execucao   = models.CharField(max_length=50, blank=True, verbose_name="Dias de execução")
    data_inicio     = models.DateField(null=True, blank=True, verbose_name="Data de início")
    data_termino    = models.DateField(null=True, blank=True, verbose_name="Data de término")

    class Meta:
        db_table        = "projects_atribuicao_equipe"
        ordering        = ["equipe", "posicao"]
        unique_together = [("equipe", "posicao")]
        verbose_name = "Atribuição de Equipe"
        verbose_name_plural = "Atribuições de Equipes"

    def __str__(self):
        label = dict(self.POSICAO_CHOICES).get(self.posicao, "?")
        nome_projeto = self.projeto.name if self.projeto else "—"
        return f"{self.equipe} — {label}: {nome_projeto}"


class ProjectDocument(models.Model):

    project = models.ForeignKey(
        "Project",
        on_delete=models.CASCADE,
        related_name="documents"
    )

    title = models.CharField(
        max_length=255
    )

    file = models.FileField(
        upload_to="projects/documents/"
    )

    description = models.TextField(
        blank=True
    )

    uploaded_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(
        auto_now_add=True
    )

    def __str__(self):
        return self.title


class ProjectPauseNote(models.Model):
    """Observação registrada pelo gestor ao pausar um projeto (o motivo que
    aparece no ícone de sirene do card da equipe)."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project    = models.ForeignKey("Project", on_delete=models.CASCADE, related_name="pause_notes")
    note       = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "projects_pause_note"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Pausa de {self.project.name} em {self.created_at:%d/%m/%Y}"