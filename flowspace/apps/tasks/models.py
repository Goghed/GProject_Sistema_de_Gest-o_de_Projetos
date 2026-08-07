import uuid
from django.db import models
from django.conf import settings


class Task(models.Model):
    PRIORITY_CHOICES = [
        ("urgent","Urgente"),("high","Alta"),("medium","Média"),("low","Baixa"),
    ]
    STATUS_CHOICES = [
        ("backlog","Backlog"),("todo","A Fazer"),("in_progress","Em Progresso"),
        ("review","Review"),("done","Concluído"),("archived","Arquivado"),
    ]
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    project      = models.ForeignKey("projects.Project", on_delete=models.CASCADE, related_name="tasks")
    column       = models.ForeignKey("projects.Column", on_delete=models.SET_NULL,
                                     null=True, blank=True, related_name="tasks")
    title        = models.CharField(max_length=300)
    description  = models.TextField(blank=True)
    status       = models.CharField(max_length=20, choices=STATUS_CHOICES, default="backlog", db_index=True)
    priority     = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default="medium")
    assignees    = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                          related_name="assigned_tasks", blank=True)
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name="created_tasks")
    due_date     = models.DateField(null=True, blank=True)
    position     = models.PositiveIntegerField(default=0)
    tags         = models.CharField(max_length=300, blank=True)
    progress     = models.PositiveIntegerField(default=0)
    needs_review  = models.BooleanField(default=False)
    start_date    = models.DateField(null=True, blank=True)
    duration_days = models.PositiveIntegerField(null=True, blank=True)
    started_at    = models.DateTimeField(null=True, blank=True)
    deadline_days = models.PositiveIntegerField(null=True, blank=True)
    # ── Bloqueio por problema ─────────────────────────────────────────────────
    is_blocked    = models.BooleanField(default=False, db_index=True,
                                        help_text="Tarefa bloqueada por problema em aberto")
    work_saturday = models.BooleanField(default=False,
                                        help_text="Sábado é dia útil para esta tarefa")
    work_sunday   = models.BooleanField(default=False,
                                        help_text="Domingo é dia útil para esta tarefa")
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "tasks_task"
        ordering = ["position", "-created_at"]

    def __str__(self):
        return self.title

    @property
    def tag_list(self):
        return [t.strip() for t in self.tags.split(",") if t.strip()]

    @property
    def done_subtasks_count(self):
        return self.subtasks.filter(done=True).count()

    @property
    def days_delta(self):
        if not self.started_at or not self.completed_at or self.deadline_days is None:
            return None
        return (self.completed_at.date() - self.started_at.date()).days - self.deadline_days

    @property
    def days_delta_label(self):
        delta = self.days_delta
        if delta is None:
            return None
        if delta < 0:
            return f"{abs(delta)}d adiantado"
        if delta > 0:
            return f"{delta}d atrasado"
        return "No prazo"

    @property
    def open_issue(self):
        return self.issues.filter(resolved=False).first()

    @property
    def daily_summary(self):
        """Resumo dos relatórios diários — usa cache do prefetch_related."""
        reports = list(self.daily_reports.all())
        accomplished     = sum(1 for r in reports if r.accomplished is True)
        not_accomplished = sum(1 for r in reports if r.accomplished is False)
        total_days       = self.duration_days or 0
        filled           = accomplished + not_accomplished
        pending          = max(0, total_days - filled)
        return {
            "accomplished":     accomplished,
            "not_accomplished": not_accomplished,
            "pending":          pending,
            "total":            total_days,
            "has_data":         total_days > 0,
        }


class SubTask(models.Model):
    id       = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task     = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="subtasks")
    title    = models.CharField(max_length=200)
    done     = models.BooleanField(default=False)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "tasks_subtask"
        ordering = ["position"]


class Comment(models.Model):
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task       = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    content    = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tasks_comment"
        ordering = ["created_at"]


class TaskIssue(models.Model):
    """Problema reportado em uma tarefa pelo responsável."""
    REASON_CHOICES = [
        ("obstacle",    "Obstáculo / Impedimento"),
        ("needs_info",  "Aguardando informação"),
        ("resource",    "Falta de recurso"),
        ("sick",        "Afastamento / Doença"),
        ("dependency",  "Dependência externa"),
        ("other",       "Outro"),
    ]
    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task        = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="issues")
    reported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                    null=True, related_name="reported_issues")
    reason      = models.CharField(max_length=30, choices=REASON_CHOICES, default="other",
                                   help_text="Motivo da pausa/problema (sincronizado com mobile)")
    description = models.TextField(help_text="Descrição do problema ou solicitação")
    # Resposta do gestor
    manager_response = models.TextField(blank=True)
    responded_by     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name="responded_issues")
    responded_at     = models.DateTimeField(null=True, blank=True)
    # Tarefa de suporte criada pelo gestor
    support_task     = models.ForeignKey(Task, on_delete=models.SET_NULL,
                                         null=True, blank=True, related_name="origin_issue")
    resolved         = models.BooleanField(default=False)
    created_at       = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table  = "tasks_issue"
        ordering  = ["-created_at"]

    def __str__(self):
        return f"Issue em {self.task.title}"


class IssueComment(models.Model):
    """Mensagem da conversa de resolução de um problema (suporta @menções)."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    issue      = models.ForeignKey(TaskIssue, on_delete=models.CASCADE, related_name="comments")
    author     = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                   null=True, related_name="issue_comments")
    content    = models.TextField()
    mentions   = models.ManyToManyField(settings.AUTH_USER_MODEL,
                                        related_name="issue_mentions", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tasks_issue_comment"
        ordering = ["created_at"]

    def __str__(self):
        return f"Comentário de {self.author} em issue {self.issue_id}"


class TaskAttachment(models.Model):
    """Arquivo ou foto anexada a uma tarefa."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task       = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="attachments")
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    file       = models.FileField(upload_to="task_attachments/%Y/%m/")
    filename   = models.CharField(max_length=255)
    file_size  = models.PositiveIntegerField(default=0)  # bytes
    is_image   = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "tasks_attachment"
        ordering = ["-created_at"]

    def __str__(self):
        return self.filename


class DailyReport(models.Model):
    """Relatório diário de progresso de uma tarefa (por dia de execução)."""
    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task         = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="daily_reports")
    day          = models.PositiveIntegerField(help_text="Número do dia (1, 2, 3...)")
    date         = models.DateField()
    accomplished = models.BooleanField(null=True, blank=True,
                                       help_text="True=realizado, False=não realizado, None=pendente")
    notes        = models.TextField(blank=True, help_text="Relato do dia")
    created_by   = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
                                     null=True, related_name="daily_reports")
    created_at   = models.DateTimeField(auto_now_add=True)
    updated_at   = models.DateTimeField(auto_now=True)

    class Meta:
        db_table       = "tasks_daily_report"
        unique_together = [("task", "day")]
        ordering       = ["day"]

    def __str__(self):
        return f"Dia {self.day} — {self.task.title}"

    @property
    def status_label(self):
        if self.accomplished is True:
            return "Realizado"
        if self.accomplished is False:
            return "Não realizado"
        return "Pendente"


class TaskDependency(models.Model):
    """Tarefa B só pode iniciar quando Tarefa A estiver concluída."""
    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task       = models.ForeignKey(Task, on_delete=models.CASCADE,
                                   related_name="dependencies",
                                   help_text="Tarefa que depende de outra")
    requires   = models.ForeignKey(Task, on_delete=models.CASCADE,
                                   related_name="required_by",
                                   help_text="Tarefa que precisa estar concluída antes")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ("task", "requires")
        db_table = "tasks_dependency"

    def __str__(self):
        return f"{self.requires.title} → {self.task.title}"
