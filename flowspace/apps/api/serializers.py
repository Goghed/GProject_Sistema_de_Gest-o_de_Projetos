from rest_framework import serializers
from apps.accounts.models import User
from apps.projects.models import Project, Column, ProjectDocument
from apps.tasks.models import Task, SubTask, Comment, IssueComment, TaskDependency


class UserSerializer(serializers.ModelSerializer):
    initials     = serializers.ReadOnlyField()
    full_name    = serializers.SerializerMethodField()
    role_display = serializers.SerializerMethodField()
    photo_url    = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            "id", "username", "full_name", "first_name", "last_name",
            "email", "role", "role_display", "avatar_color", "job_title", "initials",
            "photo_url",
        ]

    def get_full_name(self, obj):    return obj.get_full_name() or obj.username
    def get_role_display(self, obj): return obj.get_role_display()

    def get_photo_url(self, obj):
        if not obj.photo:
            return None
        try:
            request = self.context.get("request")
            if request:
                return request.build_absolute_uri(obj.photo.url)
        except Exception:
            pass
        return obj.photo.url


class SubTaskSerializer(serializers.ModelSerializer):
    class Meta:
        model  = SubTask
        fields = ["id", "title", "done", "position"]


class CommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model  = Comment
        fields = ["id", "content", "author", "created_at"]



# Mapa de tipos de pausa: inclui tanto os tipos do mobile quanto os do web
PAUSE_TYPE_LABELS = {
    "material_request": "Requisição de Material",
    "incident":         "Ocorrência / Notif. ao Gerente",
    "obstacle":         "Obstáculo / Impedimento",
    "needs_info":       "Aguardando informação",
    "resource":         "Falta de recurso",
    "sick":             "Afastamento / Doença",
    "dependency":       "Dependência externa",
    "other":            "Outro",
}


class IssueCommentSerializer(serializers.ModelSerializer):
    author = UserSerializer(read_only=True)

    class Meta:
        model  = IssueComment
        fields = ["id", "content", "author", "created_at"]


class TaskIssueSerializer(serializers.ModelSerializer):
    reported_by  = UserSerializer(read_only=True)
    responded_by = UserSerializer(read_only=True)
    type_display = serializers.SerializerMethodField()
    comments     = IssueCommentSerializer(many=True, read_only=True)

    class Meta:
        from apps.tasks.models import TaskIssue
        model  = TaskIssue
        fields = ["id", "reason", "type_display", "description", "manager_response",
                  "reported_by", "responded_by", "responded_at", "resolved",
                  "created_at", "comments"]

    def get_type_display(self, obj):
        return PAUSE_TYPE_LABELS.get(obj.reason, obj.reason)


class TaskDependencySerializer(serializers.ModelSerializer):
    requires_id     = serializers.UUIDField(source="requires.id",     read_only=True)
    requires_title  = serializers.CharField(source="requires.title",  read_only=True)
    requires_status = serializers.CharField(source="requires.status", read_only=True)

    class Meta:
        model  = TaskDependency
        fields = ["id", "requires_id", "requires_title", "requires_status"]


class TaskAttachmentSerializer(serializers.ModelSerializer):
    uploaded_by = UserSerializer(read_only=True)
    url         = serializers.SerializerMethodField()

    class Meta:
        from apps.tasks.models import TaskAttachment
        model  = TaskAttachment
        fields = ["id","filename","url","is_image","file_size","uploaded_by","created_at"]

    def get_url(self, obj):
        # Não expõe o /media/ cru (sem checagem de permissão) — passa pela view
        # protegida que confere se o usuário é membro do projeto da tarefa.
        from django.urls import reverse
        path = reverse("api:download_attachment", kwargs={"attachment_id": obj.pk})
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class ProjectDocumentSerializer(serializers.ModelSerializer):
    uploaded_by = UserSerializer(read_only=True)
    url         = serializers.SerializerMethodField()

    class Meta:
        model  = ProjectDocument
        fields = ["id", "title", "description", "url", "uploaded_by", "created_at"]

    def get_url(self, obj):
        # Não expõe o /media/ cru (sem checagem de permissão) — passa pela view
        # protegida que confere se o usuário é membro do projeto ou responsável
        # por alguma tarefa dele.
        from django.urls import reverse
        path = reverse("api:download_document", kwargs={"doc_id": obj.pk})
        request = self.context.get("request")
        return request.build_absolute_uri(path) if request else path


class TaskListSerializer(serializers.ModelSerializer):
    assignees        = UserSerializer(many=True, read_only=True)
    priority_display = serializers.SerializerMethodField()
    status_display   = serializers.SerializerMethodField()
    status           = serializers.SerializerMethodField()
    project_name     = serializers.CharField(source="project.name",  read_only=True)
    project_color    = serializers.CharField(source="project.color", read_only=True)
    tag_list         = serializers.ReadOnlyField()
    done_subtasks    = serializers.SerializerMethodField()
    total_subtasks   = serializers.SerializerMethodField()
    days_delta       = serializers.ReadOnlyField()
    days_delta_label = serializers.ReadOnlyField()
    pause_reason     = serializers.SerializerMethodField()
    has_pending_deps = serializers.SerializerMethodField()

    class Meta:
        model  = Task
        fields = [
            "id", "title", "description", "status", "status_display",
            "priority", "priority_display", "due_date", "progress",
            "tags", "tag_list", "assignees", "project", "project_name",
            "project_color", "column", "done_subtasks", "total_subtasks",
            "needs_review", "deadline_days", "started_at", "is_blocked",
            "days_delta", "days_delta_label", "pause_reason", "has_pending_deps",
            "start_date", "duration_days", "work_saturday", "work_sunday",
            "created_at", "updated_at",
        ]

    def get_priority_display(self, obj): return obj.get_priority_display()
    def get_done_subtasks(self, obj):    return obj.subtasks.filter(done=True).count()
    def get_total_subtasks(self, obj):   return obj.subtasks.count()

    def get_status(self, obj):
        """Retorna 'paused' quando bloqueado para que o mobile reconheça o estado."""
        return "paused" if obj.is_blocked else obj.status

    def get_status_display(self, obj):
        return "Pausada" if obj.is_blocked else obj.get_status_display()

    def get_has_pending_deps(self, obj):
        return obj.dependencies.exclude(requires__status="done").exists()

    def get_pause_reason(self, obj):
        """Retorna dados do problema aberto no formato que o mobile espera."""
        if not obj.is_blocked:
            return None
        issue = obj.issues.filter(resolved=False).first()
        if not issue:
            return None
        return {
            "id":           str(issue.id),
            "type":         issue.reason,
            "type_display": PAUSE_TYPE_LABELS.get(issue.reason, issue.reason),
            "description":  issue.description,
            "reported_by":  issue.reported_by.get_full_name() if issue.reported_by else None,
            "created_at":   issue.created_at.strftime("%d/%m/%Y %H:%M"),
        }


class TaskDetailSerializer(TaskListSerializer):
    subtasks              = SubTaskSerializer(many=True, read_only=True)
    comments              = CommentSerializer(many=True, read_only=True)
    issues                = TaskIssueSerializer(many=True, read_only=True)
    attachments           = TaskAttachmentSerializer(many=True, read_only=True)
    open_issue            = serializers.SerializerMethodField()
    today_report          = serializers.SerializerMethodField()
    dependencies          = TaskDependencySerializer(many=True, read_only=True)
    viewer_can_manage_deps = serializers.SerializerMethodField()

    class Meta(TaskListSerializer.Meta):
        fields = TaskListSerializer.Meta.fields + [
            "subtasks", "comments", "completed_at",
            "issues", "attachments", "open_issue", "today_report", "dependencies",
            "viewer_can_manage_deps",
        ]

    def get_viewer_can_manage_deps(self, obj):
        request = self.context.get("request")
        if not request or not request.user.is_authenticated:
            return False
        return obj.project.can_create_tasks(request.user)

    def get_open_issue(self, obj):
        if not obj.is_blocked:
            return None
        issue = obj.issues.filter(resolved=False).first()
        if not issue:
            return None
        return TaskIssueSerializer(issue, context=self.context).data

    def get_today_report(self, obj):
        from datetime import date
        today = date.today()
        report = obj.daily_reports.filter(date=today).first()
        if not report:
            return None
        return {"accomplished": report.accomplished, "notes": report.notes}


class ColumnSerializer(serializers.ModelSerializer):
    tasks = TaskListSerializer(many=True, read_only=True)

    class Meta:
        model  = Column
        fields = ["id", "name", "color", "position", "is_done_column", "tasks"]


class ProjectListSerializer(serializers.ModelSerializer):
    task_count      = serializers.ReadOnlyField()
    completed_count = serializers.ReadOnlyField()
    progress        = serializers.ReadOnlyField()
    owner           = UserSerializer(read_only=True)
    members         = UserSerializer(many=True, read_only=True)
    status_display  = serializers.SerializerMethodField()

    class Meta:
        model  = Project
        fields = [
            "id", "name", "description", "scope", "color", "status", "status_display",
            "start_date", "due_date", "task_count", "completed_count",
            "progress", "owner", "members", "created_at", "updated_at",
        ]

    def get_status_display(self, obj): return obj.get_status_display()


class ProjectDetailSerializer(ProjectListSerializer):
    columns = ColumnSerializer(many=True, read_only=True)

    class Meta(ProjectListSerializer.Meta):
        fields = ProjectListSerializer.Meta.fields + ["columns"]
