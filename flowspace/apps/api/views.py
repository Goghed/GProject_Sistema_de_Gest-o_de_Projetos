import json
from django.core.exceptions import ValidationError
from django.utils import timezone
from django.contrib.auth import authenticate
from django.utils import timezone
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework_simplejwt.tokens import RefreshToken

from apps.common.uploads import validate_image_upload, validate_generic_upload
from apps.accounts.models import User
from apps.projects.models import Project, Column
from apps.tasks.models import Task, SubTask, Comment, TaskAttachment, DailyReport, TaskIssue, TaskDependency
from apps.notifications.models import Notification
from .serializers import (
    UserSerializer, ProjectListSerializer, ProjectDetailSerializer,
    TaskListSerializer, TaskDetailSerializer, CommentSerializer,
    TaskAttachmentSerializer,
)


def get_tokens(user, request=None):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
        "user": UserSerializer(user, context={"request": request}).data
    }


# ── AUTH ─────────────────────────────────────────
@api_view(["POST"])
@permission_classes([AllowAny])
def login_view(request):
    user = authenticate(
        request,
        username=request.data.get("username"),
        password=request.data.get("password")
    )

    if not user:
        return Response({"error": "Credenciais inválidas."}, status=401)

    return Response(get_tokens(user, request))


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def me_view(request):
    return Response(UserSerializer(request.user, context={"request": request}).data)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def update_profile(request):
    u = request.user

    for field in ("first_name","last_name","job_title","bio","avatar_color"):
        if field in request.data:
            setattr(u, field, request.data[field])

    u.save()
    return Response(UserSerializer(u, context={"request": request}).data)


# ── PHOTO ─────────────────────────────────────────
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def upload_photo(request):
    photo = request.FILES.get("photo")
    if not photo:
        return Response({"error": "Nenhuma foto enviada."}, status=400)
    try:
        validate_image_upload(photo)
    except ValidationError as e:
        return Response({"error": e.message}, status=400)
    u = request.user
    if u.photo:
        try:
            u.photo.delete(save=False)
        except Exception:
            pass
    u.photo = photo
    u.save()
    return Response(UserSerializer(u, context={"request": request}).data)


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def remove_photo(request):
    u = request.user
    if u.photo:
        try:
            u.photo.delete(save=False)
        except Exception:
            pass
        u.photo = None
        u.save()
    return Response(UserSerializer(u, context={"request": request}).data)


# ── DASHBOARD ─────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def dashboard_view(request):

    from datetime import timedelta

    user       = request.user
    today    = timezone.now().date()

    projects = Project.objects.filter(
        members=user,
        status__in=["active", "on_hold"]
    )

    # "Minhas Tarefas" e "Concluídas" = apenas tarefas atribuídas ao usuário
    my_scope   = Task.objects.filter(project__in=projects, assignees=user).exclude(status="archived")
    open_tasks = my_scope.exclude(status="done")
    done_tasks = my_scope.filter(status="done")

    # "Em Atraso" = role-aware, igual ao web (managers veem todo o projeto)
    is_manager = user.role in ("owner", "admin", "manager")
    if is_manager:
        overdue_scope = Task.objects.filter(project__in=projects).exclude(status__in=["done", "archived"])
    else:
        overdue_scope = open_tasks
    overdue = overdue_scope.filter(due_date__lt=today)

    # ── Performance (sempre baseada nas tarefas do próprio usuário) ────────────
    my_all  = Task.objects.filter(assignees=user)
    my_done = my_all.filter(status="done")

    # Tarefas concluídas por dia na semana atual (Seg→Dom)
    week_start      = today - timedelta(days=today.weekday())
    tasks_this_week = [
        my_done.filter(completed_at__date=week_start + timedelta(days=i)).count()
        for i in range(7)
    ]

    # Taxa de conclusão
    total_my        = my_all.count()
    done_count      = my_done.count()
    completion_rate = round(done_count / total_my * 100) if total_my else 0

    # Tempo médio de conclusão (started_at → completed_at)
    done_timed = list(my_done.filter(started_at__isnull=False, completed_at__isnull=False))
    if done_timed:
        deltas             = [(t.completed_at.date() - t.started_at).days for t in done_timed]
        avg_completion_days = round(sum(deltas) / len(deltas), 1)
    else:
        avg_completion_days = None

    # Taxa de entrega no prazo
    tasks_with_delta = [
        t for t in my_done.filter(started_at__isnull=False, deadline_days__isnull=False)
        if t.days_delta is not None
    ]
    on_time      = sum(1 for t in tasks_with_delta if t.days_delta <= 0)
    on_time_rate = round(on_time / len(tasks_with_delta) * 100) if tasks_with_delta else 0

    # Distribuição por status
    status_distribution = {
        "todo":        my_all.filter(status="todo").count(),
        "in_progress": my_all.filter(status="in_progress").count(),
        "review":      my_all.filter(status="review").count(),
        "done":        done_count,
        "paused":      my_all.filter(status="paused").count(),
    }

    return Response({
        "stats": {
            "projects":   projects.count(),
            "my_tasks":   open_tasks.count(),
            "done_tasks": done_tasks.count(),
            "overdue":    overdue.count(),
        },
        "performance": {
            "avg_completion_days": avg_completion_days,
            "completion_rate":     completion_rate,
            "on_time_rate":        on_time_rate,
            "tasks_this_week":     tasks_this_week,
            "status_distribution": status_distribution,
        },
        "projects": ProjectListSerializer(projects[:6], many=True).data,
        "my_tasks": TaskListSerializer(
            open_tasks.order_by("-updated_at")[:10], many=True
        ).data,
    })


# ── PROJECTS ─────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def project_list(request):

    qs = Project.objects.filter(
        members=request.user
    ).order_by("-updated_at")

    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])

    return Response(ProjectListSerializer(qs, many=True).data)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def project_detail(request, pk):

    proj = Project.objects.filter(
        pk=pk,
        members=request.user
    ).first()

    if not proj:
        return Response({"error": "Não encontrado."}, status=404)

    return Response(ProjectDetailSerializer(proj).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def project_create(request):

    proj = Project.objects.create(
        name=request.data.get("name"),
        description=request.data.get("description", ""),
        color=request.data.get("color", "#5b4cf5"),
        start_date=request.data.get("start_date") or None,
        due_date=request.data.get("due_date") or None,
        owner=request.user,
    )

    proj.members.add(request.user)

    default_columns = [
        ("Backlog", "#8888aa", False, 0),
        ("A Fazer", "#5b4cf5", False, 1),
        ("Em Progresso", "#0ea5e9", False, 2),
        ("Review", "#fbbf24", False, 3),
        ("Concluído", "#34d399", True, 4),
    ]

    for name, color, done, pos in default_columns:
        Column.objects.create(
            project=proj,
            name=name,
            color=color,
            is_done_column=done,
            position=pos
        )

    return Response(ProjectDetailSerializer(proj).data, status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def project_update(request, pk):

    proj = Project.objects.filter(
        pk=pk,
        members=request.user
    ).first()

    if not proj:
        return Response({"error": "Projeto não encontrado."}, status=404)

    if not (request.user == proj.owner or proj.can_create_tasks(request.user) or request.user.is_superuser):
        return Response({"error": "Sem permissão para editar este projeto."}, status=403)

    for field in ("name", "description", "color", "status"):
        if field in request.data:
            setattr(proj, field, request.data[field])

    if "start_date" in request.data:
        proj.start_date = request.data["start_date"] or None

    if "due_date" in request.data:
        proj.due_date = request.data["due_date"] or None

    proj.save()

    return Response(ProjectDetailSerializer(proj).data)


# ── TASKS ────────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_list(request):

    qs = Task.objects.filter(
        project__members=request.user
    ).exclude(status="archived")

    if request.query_params.get("project"):
        qs = qs.filter(project_id=request.query_params["project"])

    if request.query_params.get("status"):
        qs = qs.filter(status=request.query_params["status"])

    if request.query_params.get("mine") == "1":
        qs = qs.filter(assignees=request.user)

    return Response(
        TaskListSerializer(
            qs.order_by("-updated_at")[:50],
            many=True
        ).data
    )


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def task_update(request, pk):

    task = Task.objects.select_related("project").filter(
        pk=pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Não encontrado."}, status=404)

    if not task.project.can_create_tasks(request.user):
        return Response({"error": "Sem permissão."}, status=403)

    for field in ("title","description","priority","status","tags","progress"):
        if field in request.data:
            setattr(task, field, request.data[field])

    if "due_date" in request.data:
        task.due_date = request.data["due_date"] or None

    if "column_id" in request.data:

        col = Column.objects.filter(
            pk=request.data["column_id"],
            project=task.project,
        ).first()

        if col:
            task.column = col

    task.save()

    return Response(TaskDetailSerializer(task).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_create(request):

    project_id = request.data.get("project")
    column_id = request.data.get("column")

    project = Project.objects.filter(
        id=project_id,
        members=request.user
    ).first()

    if not project:
        return Response({"error": "Projeto não encontrado."}, status=404)

    column = Column.objects.filter(
        id=column_id,
        project=project
    ).first()

    if not column:
        return Response({"error": "Coluna inválida."}, status=404)

    status_val = request.data.get("status", "backlog")
    valid_statuses = {"backlog", "todo", "in_progress", "review", "done"}
    if status_val not in valid_statuses:
        status_val = "backlog"

    task = Task.objects.create(
        project=project,
        column=column,
        title=request.data.get("title"),
        description=request.data.get("description", ""),
        priority=request.data.get("priority", "medium"),
        status=status_val,
        due_date=request.data.get("due_date") or None,
        start_date=request.data.get("start_date") or None,
        duration_days=request.data.get("duration_days") or None,
        tags=request.data.get("tags", ""),
        needs_review=bool(request.data.get("needs_review", False)),
        created_by=request.user
    )

    assignee_ids = request.data.get("assignees", [])
    if assignee_ids:
        from apps.accounts.models import User as UserModel
        assignees = UserModel.objects.filter(id__in=assignee_ids, projects=project)
        task.assignees.set(assignees)

    return Response(TaskDetailSerializer(task).data, status=201)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def task_detail_view(request, pk):

    task = Task.objects.select_related(
        "project", "column", "created_by"
    ).prefetch_related(
        "assignees", "subtasks", "comments__author",
        "attachments__uploaded_by",
        "issues__reported_by", "issues__responded_by",
        "issues__comments__author",
    ).filter(
        pk=pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Task não encontrada."}, status=404)

    return Response(TaskDetailSerializer(task, context={"request": request}).data)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def advance_status(request, pk):
    """Avança o status da tarefa seguindo o fluxo correto com verificação de permissões."""
    from apps.tasks.views import _sync_column, _notify

    task = Task.objects.select_related("project", "column").filter(
        pk=pk, project__members=request.user
    ).first()
    if not task:
        return Response({"ok": False, "error": "Tarefa não encontrada."}, status=404)

    if task.is_blocked:
        return Response({"ok": False, "error": "Tarefa bloqueada. Aguarde a resolução do gestor."}, status=400)

    if task.status == "backlog":
        if not task.project.members.filter(pk=request.user.pk).exists():
            return Response({"ok": False, "error": "Você não é membro deste projeto."}, status=403)
        task.assignees.add(request.user)
        task.status = "todo"

    elif task.status == "todo":
        if request.user not in task.assignees.all():
            return Response({"ok": False, "error": "Você não é responsável por esta tarefa."}, status=403)
        pending_deps = task.dependencies.exclude(requires__status="done").select_related("requires")
        if pending_deps.exists():
            titles = " • ".join(d.requires.title for d in pending_deps[:3])
            return Response({"ok": False, "error": f"Aguardando conclusão de: {titles}"}, status=400)
        task.status     = "in_progress"
        task.started_at = timezone.now()

    elif task.status == "in_progress":
        if request.user not in task.assignees.all():
            return Response({"ok": False, "error": "Você não é responsável por esta tarefa."}, status=403)
        task.status = "review" if task.needs_review else "done"
        if task.status == "done":
            task.completed_at = timezone.now()

    elif task.status == "review":
        if not task.project.can_create_tasks(request.user):
            return Response({"ok": False, "error": "Apenas o gestor pode aprovar."}, status=403)
        task.status       = "done"
        task.completed_at = timezone.now()

    else:
        return Response({"ok": False, "error": "Status não pode avançar."}, status=400)

    _sync_column(task)
    task.save()

    labels = {"todo": "assumiu", "in_progress": "iniciou", "review": "enviou para revisão", "done": "concluiu"}
    msg = f"{request.user} {labels.get(task.status, 'atualizou')} a tarefa «{task.title}»"
    for m in task.project.members.exclude(id=request.user.id):
        _notify(m, msg, f"/tasks/{task.pk}/")

    return Response({"ok": True, "status": task.status})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def subtask_toggle(request, pk):

    subtask = SubTask.objects.select_related(
        "task",
        "task__project"
    ).filter(
        pk=pk,
        task__project__members=request.user
    ).first()

    if not subtask:
        return Response({"error": "Subtask não encontrada."}, status=404)

    subtask.done = not subtask.done
    subtask.save(update_fields=["done"])

    task  = subtask.task
    total = task.subtasks.count()
    done  = task.subtasks.filter(done=True).count()
    task.progress = int(done / total * 100) if total else 0
    task.save(update_fields=["progress"])

    return Response({
        "id":       str(subtask.id),
        "done":     subtask.done,
        "progress": task.progress,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def comment_add(request, task_pk):

    task = Task.objects.select_related("project").filter(
        pk=task_pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Task não encontrada."}, status=404)

    text = (request.data.get("text") or request.data.get("content") or "").strip()

    if not text:
        return Response({"error": "Comentário vazio."}, status=400)

    comment = Comment.objects.create(
        task=task,
        author=request.user,
        content=text
    )

    return Response(CommentSerializer(comment).data, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_report_issue(request, pk):

    task = Task.objects.select_related("project").filter(
        pk=pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Task não encontrada."}, status=404)

    reason      = request.data.get("reason", "other")
    description = request.data.get("description", "").strip()

    if not description:
        return Response({"error": "Descrição do problema é obrigatória."}, status=400)

    if task.is_blocked:
        open_issue = task.issues.filter(resolved=False).first()
        return Response({
            "error": "Já existe um problema em aberto nesta tarefa.",
            "issue_id": str(open_issue.id) if open_issue else None,
        }, status=400)

    issue = TaskIssue.objects.create(
        task        = task,
        reported_by = request.user,
        reason      = reason,
        description = description,
    )

    task.is_blocked = True
    task.save(update_fields=["is_blocked"])

    # Notifica o gestor
    manager = task.project.manager
    reason_label = dict(TaskIssue.REASON_CHOICES).get(reason, reason)
    if manager:
        Notification.objects.create(
            user    = manager,
            message = f"🚨 {request.user} pausou «{task.title}» [{reason_label}]: {description[:80]}",
            link    = f"/tasks/{task.pk}/",
        )

    return Response({
        "message":    "Problema reportado com sucesso.",
        "id":         str(issue.id),
        "reason":     issue.reason,
        "description": issue.description,
    }, status=201)


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_pause_task(request, pk):
    """Alias de report-issue para o app mobile — aceita 'type' no lugar de 'reason'."""
    task = Task.objects.select_related("project").filter(
        pk=pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Task não encontrada."}, status=404)

    if request.user not in task.assignees.all():
        return Response({"error": "Apenas o responsável pode pausar a tarefa."}, status=403)

    if task.is_blocked:
        open_issue = task.issues.filter(resolved=False).first()
        return Response({
            "error": "Já existe um problema em aberto nesta tarefa.",
            "issue_id": str(open_issue.id) if open_issue else None,
        }, status=400)

    description = request.data.get("description", "").strip()
    # mobile envia "type", web envia "reason"
    reason = request.data.get("reason") or request.data.get("type") or "other"

    if not description:
        return Response({"error": "Descrição do problema é obrigatória."}, status=400)

    issue = TaskIssue.objects.create(
        task        = task,
        reported_by = request.user,
        reason      = reason,
        description = description,
    )
    task.is_blocked = True
    task.save(update_fields=["is_blocked"])

    manager = task.project.manager
    reason_label = dict(TaskIssue.REASON_CHOICES).get(reason, reason)
    if manager:
        Notification.objects.create(
            user    = manager,
            message = f"🚨 {request.user} pausou «{task.title}» [{reason_label}]: {description[:80]}",
            link    = f"/tasks/{task.pk}/",
        )
    for m in task.project.members.filter(role__in=["owner","admin"]).exclude(id=request.user.id):
        Notification.objects.create(
            user    = m,
            message = f"🚨 Problema reportado em «{task.title}» por {request.user}",
            link    = f"/tasks/{task.pk}/",
        )

    return Response({
        "ok":          True,
        "message":     "Tarefa pausada com sucesso.",
        "id":          str(issue.id),
        "reason":      issue.reason,
        "description": issue.description,
    }, status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def api_edit_issue(request, issue_pk):

    issue = TaskIssue.objects.select_related(
        "task", "task__project"
    ).filter(
        pk=issue_pk,
        task__project__members=request.user
    ).first()

    if not issue:
        return Response({"error": "Issue não encontrada."}, status=404)

    if issue.resolved:
        return Response({"error": "Este problema já foi resolvido."}, status=400)

    if "reason" in request.data:
        issue.reason = request.data["reason"]

    if "description" in request.data:
        issue.description = request.data["description"]

    issue.save()

    return Response({
        "message":     "Issue atualizada com sucesso.",
        "id":          str(issue.id),
        "reason":      issue.reason,
        "description": issue.description,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_resolve_issue(request, issue_pk):

    issue = TaskIssue.objects.select_related(
        "task", "task__project"
    ).filter(
        pk=issue_pk,
        task__project__members=request.user
    ).first()

    if not issue:
        return Response({"error": "Issue não encontrada."}, status=404)

    manager_response = request.data.get("response", "").strip()

    issue.resolved       = True
    issue.responded_by   = request.user
    issue.responded_at   = timezone.now()
    if manager_response:
        issue.manager_response = manager_response
    issue.save()

    # Desbloqueia a tarefa
    issue.task.is_blocked = False
    issue.task.save(update_fields=["is_blocked"])

    # Notifica quem reportou
    if issue.reported_by:
        Notification.objects.create(
            user    = issue.reported_by,
            message = f"✅ {request.user} resolveu o problema em «{issue.task.title}»",
            link    = f"/tasks/{issue.task.pk}/",
        )

    return Response({
        "message":         "Issue resolvida com sucesso.",
        "issue_id":        str(issue.id),
        "resolved":        True,
        "manager_response": issue.manager_response,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_resume_task(request, pk):
    """Retoma uma tarefa pausada (is_blocked). Apenas assignees podem retomar."""
    task = Task.objects.prefetch_related("assignees", "issues").filter(
        pk=pk, project__members=request.user
    ).first()
    if not task:
        return Response({"error": "Tarefa não encontrada."}, status=404)
    if not task.assignees.filter(pk=request.user.pk).exists():
        return Response({"error": "Apenas responsáveis podem retomar a tarefa."}, status=403)
    if not task.is_blocked:
        return Response({"error": "Tarefa não está pausada."}, status=400)
    # Resolve o issue em aberto
    open_issue = task.issues.filter(resolved=False).first()
    if open_issue:
        open_issue.resolved     = True
        open_issue.responded_by = request.user
        open_issue.responded_at = timezone.now()
        open_issue.save(update_fields=["resolved", "responded_by", "responded_at"])
    task.is_blocked = False
    task.status     = "in_progress"
    task.save(update_fields=["is_blocked", "status"])
    return Response({"ok": True, "status": "in_progress", "status_display": "Em Progresso"})


@api_view(["POST", "PUT", "PATCH"])
@permission_classes([IsAuthenticated])
def api_issue_comment_edit(request, comment_pk):
    """Edita um comentário de issue. Apenas o autor pode editar."""
    import re
    from django.utils.html import escape
    from apps.tasks.models import IssueComment
    comment = IssueComment.objects.select_related("author", "issue__task__project").filter(
        pk=comment_pk,
        issue__task__project__members=request.user
    ).first()
    if not comment:
        return Response({"error": "Comentário não encontrado."}, status=404)
    if comment.author != request.user:
        return Response({"error": "Sem permissão. Apenas o autor pode editar."}, status=403)
    content = request.data.get("content", "").strip()
    if not content:
        return Response({"error": "Conteúdo vazio."}, status=400)
    comment.content = content
    comment.save(update_fields=["content"])
    def highlight(text):
        return re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', escape(text))
    return Response({
        "ok": True,
        "id": str(comment.id),
        "content": content,
        "content_html": highlight(content),
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def api_upload_attachment(request, pk):

    task = Task.objects.select_related("project").filter(
        pk=pk,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Task não encontrada."}, status=404)

    file = request.FILES.get("file")

    if not file:
        return Response({"error": "Nenhum arquivo enviado."}, status=400)

    try:
        validate_generic_upload(file, max_size=10 * 1024 * 1024)
    except ValidationError as e:
        return Response({"error": e.message}, status=400)

    import os
    img_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
    ext = os.path.splitext(file.name)[1].lower()

    attachment = TaskAttachment.objects.create(
        task=task,
        uploaded_by=request.user,
        file=file,
        filename=file.name,
        file_size=file.size,
        is_image=ext in img_extensions,
    )

    return Response(
        TaskAttachmentSerializer(attachment, context={"request": request}).data,
        status=201,
    )


@api_view(["DELETE"])
@permission_classes([IsAuthenticated])
def api_delete_attachment(request, pk, attachment_id):

    attachment = TaskAttachment.objects.select_related("task__project").filter(
        pk=attachment_id,
        task_id=pk,
        task__project__members=request.user,
    ).first()

    if not attachment:
        return Response({"error": "Anexo não encontrado."}, status=404)

    if attachment.uploaded_by_id != request.user.id and not attachment.task.project.can_create_tasks(request.user):
        return Response({"error": "Apenas quem enviou o arquivo ou o gestor pode remover."}, status=403)

    attachment.file.delete(save=False)
    attachment.delete()

    return Response(status=204)


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def api_download_attachment(request, attachment_id):
    """Serve o arquivo somente para membros do projeto da tarefa — o /media/ cru
    não tem checagem nenhuma de permissão, então isso não pode virar um link direto."""
    from django.http import FileResponse, Http404

    attachment = TaskAttachment.objects.select_related("task__project").filter(
        pk=attachment_id,
        task__project__members=request.user,
    ).first()

    if not attachment or not attachment.file:
        raise Http404

    return FileResponse(
        attachment.file.open("rb"),
        filename=attachment.filename or attachment.file.name,
        as_attachment=False,
    )


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notifications_mark_all_read(request):

    notifications = Notification.objects.filter(
        user=request.user,
        read=False
    )

    count = notifications.count()

    notifications.update(read=True)

    return Response({
        "message": "Notificações marcadas como lidas.",
        "updated": count
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def notification_mark_read(request, pk):

    notification = Notification.objects.filter(
        pk=pk,
        user=request.user
    ).first()

    if not notification:
        return Response({"error": "Notificação não encontrada."}, status=404)

    notification.read = True
    notification.read_at = timezone.now()
    notification.save()

    return Response({
        "message": "Notificação marcada como lida.",
        "notification_id": notification.id,
        "read": True
    })


# ── KANBAN ───────────────────────────────────────
@api_view(["POST"])
@permission_classes([IsAuthenticated])
def kanban_move_task(request):

    task_id = request.data.get("task_id")
    column_id = request.data.get("column_id")

    task = Task.objects.filter(
        pk=task_id,
        project__members=request.user
    ).first()

    if not task:
        return Response({"error": "Tarefa não encontrada."}, status=404)

    column = Column.objects.filter(
        pk=column_id,
        project=task.project
    ).first()

    if not column:
        return Response({"error": "Coluna não encontrada."}, status=404)

    task.column = column

    if column.is_done_column:
        task.status = "done"
        task.completed_at = timezone.now()

    task.save()

    return Response({"success": True})


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def kanban_reorder(request, project_pk):

    order = request.data.get("order", [])

    if not isinstance(order, list):
        return Response({"error": "Formato inválido."}, status=400)

    tasks = Task.objects.filter(
        id__in=order,
        project_id=project_pk,
        project__members=request.user
    )

    task_map = {str(t.id): t for t in tasks}

    for index, task_id in enumerate(order):

        task = task_map.get(str(task_id))

        if task:
            task.position = index
            task.save(update_fields=["position"])

    return Response({"success": True})


# ── NOTIFICATIONS ─────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def notification_list(request):

    notifs = request.user.notifications.all()[:30]

    return Response([
        {
            "id": str(n.id),
            "message": n.message,
            "link": n.link,
            "read": n.read,
            "created_at": n.created_at.isoformat()
        }
        for n in notifs
    ])


# ── TEAM ─────────────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def team_list(request):

    return Response(
        UserSerializer(
            User.objects.filter(is_active=True).order_by("first_name"),
            many=True
        ).data
    )

# ── Helpers ───────────────────────────────────────────────────────────────────
def _notify_assignees(task, actor):
    for a in task.assignees.exclude(id=actor.id):
        Notification.objects.create(user=a, message=f"{actor} te atribuiu '{task.title}'", link=f"/tasks/{task.pk}/")


def _notify_task_members(task, actor, message):
    members = set(task.assignees.all())
    if task.created_by:
        members.add(task.created_by)
    for m in members:
        if m != actor:
            Notification.objects.create(user=m, message=message, link=f"/tasks/{task.pk}/")
# ── DAILY REPORTS ─────────────────────────────────
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def daily_report_list(request, task_pk):
    task = Task.objects.filter(pk=task_pk, project__members=request.user).first()
    if not task:
        return Response({"error": "Tarefa não encontrada."}, status=404)
    reports = task.daily_reports.all()
    return Response([
        {
            "id":           str(r.id),
            "day":          r.day,
            "date":         str(r.date),
            "accomplished": r.accomplished,
            "report":       r.notes,
            "status_label": r.status_label,
        }
        for r in reports
    ])


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def daily_report_create(request, task_pk):
    from datetime import date as date_cls, timedelta
    task = Task.objects.filter(pk=task_pk, project__members=request.user).first()
    if not task:
        return Response({"error": "Tarefa não encontrada."}, status=404)

    day_num      = request.data.get("day")
    accomplished = request.data.get("accomplished")
    notes        = request.data.get("report", "")
    date_str     = request.data.get("date")

    if not day_num:
        return Response({"error": "Campo 'day' é obrigatório."}, status=400)

    if date_str:
        from datetime import date as date_cls
        try:
            day_date = date_cls.fromisoformat(date_str)
        except ValueError:
            day_date = task.start_date + timedelta(days=int(day_num) - 1) if task.start_date else date_cls.today()
    elif task.start_date:
        day_date = task.start_date + timedelta(days=int(day_num) - 1)
    else:
        day_date = date_cls.today()

    report, _ = DailyReport.objects.update_or_create(
        task=task, day=int(day_num),
        defaults={
            "date":         day_date,
            "accomplished": accomplished,
            "notes":        notes,
            "created_by":   request.user,
        },
    )
    return Response({
        "id":           str(report.id),
        "day":          report.day,
        "date":         str(report.date),
        "accomplished": report.accomplished,
        "report":       report.notes,
        "status_label": report.status_label,
    }, status=201)


@api_view(["PATCH"])
@permission_classes([IsAuthenticated])
def daily_report_update(request, task_pk, report_pk):
    task = Task.objects.filter(pk=task_pk, project__members=request.user).first()
    if not task:
        return Response({"error": "Tarefa não encontrada."}, status=404)

    report = DailyReport.objects.filter(pk=report_pk, task=task).first()
    if not report:
        return Response({"error": "Relatório não encontrado."}, status=404)

    if "accomplished" in request.data:
        report.accomplished = request.data["accomplished"]
    if "report" in request.data:
        report.notes = request.data["report"]
    report.save()

    return Response({
        "id":           str(report.id),
        "day":          report.day,
        "date":         str(report.date),
        "accomplished": report.accomplished,
        "report":       report.notes,
        "status_label": report.status_label,
    })


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def register_push_token(request):
    token = request.data.get("token", "").strip()
    if not token:
        return Response({"error": "Token vazio."}, status=400)
    request.user.expo_push_token = token
    request.user.save(update_fields=["expo_push_token"])
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def performance_view(request):
    from django.db.models import Q
    from datetime import timedelta
    user = request.user
    is_manager = user.role in ("owner", "admin", "manager")
    my_tasks = Task.objects.filter(assignees=user)
    my_done  = my_tasks.filter(status="done")
    status_counts = {
        "todo":        my_tasks.filter(status="todo").count(),
        "in_progress": my_tasks.filter(status="in_progress").count(),
        "review":      my_tasks.filter(status="review").count(),
        "done":        my_done.count(),
        "backlog":     my_tasks.filter(status="backlog").count(),
    }
    today  = timezone.now().date()
    weekly = []
    for i in range(7, -1, -1):
        ws = today - timedelta(days=today.weekday() + 7 * i)
        we = ws + timedelta(days=6)
        weekly.append({"week": ws.strftime("%d/%m"), "count": my_done.filter(completed_at__date__gte=ws, completed_at__date__lte=we).count()})
    tasks_with_delta = [t for t in my_done.filter(started_at__isnull=False, deadline_days__isnull=False) if t.days_delta is not None]
    on_time   = sum(1 for t in tasks_with_delta if t.days_delta <= 0)
    avg_delta = round(sum(t.days_delta for t in tasks_with_delta) / len(tasks_with_delta), 1) if tasks_with_delta else None
    on_time_pct = round(on_time / len(tasks_with_delta) * 100) if tasks_with_delta else None
    personal = {"total_tasks": my_tasks.count(), "done_tasks": my_done.count(), "status_counts": status_counts, "weekly_done": weekly, "on_time_pct": on_time_pct, "avg_delta_days": avg_delta, "on_time_count": on_time, "measured_tasks": len(tasks_with_delta)}
    result = {"personal": personal, "team": None}
    if is_manager:
        managed = Project.objects.filter(Q(manager=user) | Q(owner=user)).distinct()
        ranking = []
        for proj in managed[:8]:
            ranking.append({"id": str(proj.pk), "name": proj.name, "color": proj.color, "total": proj.tasks.count(), "done": proj.tasks.filter(status="done").count(), "progress": proj.progress})
        ranking.sort(key=lambda x: x["done"], reverse=True)
        all_done = Task.objects.filter(project__in=managed, status="done")
        td = [t for t in all_done.filter(started_at__isnull=False, deadline_days__isnull=False) if t.days_delta is not None]
        result["team"] = {"project_ranking": ranking, "team_on_time_pct": round(sum(1 for t in td if t.days_delta <= 0) / len(td) * 100) if td else None, "team_avg_delta": round(sum(t.days_delta for t in td) / len(td), 1) if td else None, "total_tasks": Task.objects.filter(project__in=managed).count(), "done_tasks": all_done.count()}
    return Response(result)


# ── PRESENCE ────────────────────────────────────────────────────────────────

@api_view(["POST"])
@permission_classes([IsAuthenticated])
def presence_heartbeat(request):
    """Atualiza last_seen do usuário autenticado."""
    User.objects.filter(pk=request.user.pk).update(last_seen=timezone.now())
    return Response({"ok": True})


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def presence_online(request):
    """Retorna IDs dos usuários online nos últimos 35 segundos."""
    from datetime import timedelta
    cutoff = timezone.now() - timedelta(seconds=35)
    online_ids = list(
        User.objects.filter(last_seen__gte=cutoff).values_list("id", flat=True)
    )
    return Response({"online": [str(uid) for uid in online_ids]})


# ── DEPENDENCIES ──────────────────────────────────────────────────────────────

def _dep_has_cycle(start_task, target_task):
    """Retorna True se adicionar target como bloqueador de start cria dependência circular."""
    visited = set()
    queue = [target_task]
    while queue:
        current = queue.pop(0)
        for dep in current.dependencies.select_related("requires"):
            if str(dep.requires.pk) == str(start_task.pk):
                return True
            if dep.requires.pk not in visited:
                visited.add(dep.requires.pk)
                queue.append(dep.requires)
    return False


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def task_dependency_add(request, pk):
    """Adiciona dependência: tarefa pk só pode iniciar após 'requires' estar concluída."""
    task = Task.objects.filter(pk=pk, project__members=request.user).select_related("project").first()
    if not task:
        return Response({"ok": False, "error": "Tarefa não encontrada."}, status=404)
    if not task.project.can_create_tasks(request.user):
        return Response({"ok": False, "error": "Sem permissão."}, status=403)

    requires_id = request.data.get("requires")
    if not requires_id:
        return Response({"ok": False, "error": "Informe a tarefa bloqueadora."}, status=400)

    requires = Task.objects.filter(pk=requires_id, project=task.project).first()
    if not requires:
        return Response({"ok": False, "error": "Tarefa bloqueadora não encontrada no projeto."}, status=404)
    if str(requires.pk) == str(task.pk):
        return Response({"ok": False, "error": "Uma tarefa não pode depender de si mesma."}, status=400)
    if _dep_has_cycle(requires, task):
        return Response({"ok": False, "error": "Dependência circular detectada."}, status=400)

    dep, _ = TaskDependency.objects.get_or_create(task=task, requires=requires)
    return Response({
        "ok":              True,
        "dep_id":          str(dep.id),
        "requires_id":     str(requires.id),
        "requires_title":  requires.title,
        "requires_status": requires.status,
    })


@api_view(["DELETE", "POST"])
@permission_classes([IsAuthenticated])
def task_dependency_remove(request, pk, dep_id):
    """Remove uma dependência de tarefa."""
    task = Task.objects.filter(pk=pk, project__members=request.user).select_related("project").first()
    if not task:
        return Response({"ok": False, "error": "Tarefa não encontrada."}, status=404)
    if not task.project.can_create_tasks(request.user):
        return Response({"ok": False, "error": "Sem permissão."}, status=403)

    dep = TaskDependency.objects.filter(pk=dep_id, task=task).first()
    if not dep:
        return Response({"ok": False, "error": "Dependência não encontrada."}, status=404)

    dep.delete()
    return Response({"ok": True})
