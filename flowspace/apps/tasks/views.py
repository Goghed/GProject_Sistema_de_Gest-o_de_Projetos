import json
import os
from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from .models import Task, SubTask, Comment, TaskIssue, TaskAttachment, DailyReport, IssueComment, TaskDependency
from apps.projects.models import Project, Column
from apps.accounts.models import User
from apps.notifications.models import Notification
from apps.common.uploads import validate_generic_upload


# ── helpers ───────────────────────────────────────────────────────────────────

def _sync_column(task):
    col_map = {
        "todo":        "A Fazer",
        "in_progress": "Em Progresso",
        "review":      "Review",
        "done":        "Concluído",
    }
    target = col_map.get(task.status)
    if target:
        col = task.project.columns.filter(name__iexact=target).first()
        if col:
            task.column = col


def _notify(user, message, link):
    Notification.objects.create(user=user, message=message, link=link)


# ── Views ─────────────────────────────────────────────────────────────────────

@login_required
def task_create(request, project_pk):
    project = get_object_or_404(Project, pk=project_pk)
    if not project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Apenas o gestor pode criar tarefas."}, status=403)

    if request.method == "POST":
        col_id = request.POST.get("column") or None
        col    = Column.objects.filter(pk=col_id, project=project).first() if col_id else None
        task   = Task.objects.create(
            project       = project,
            column        = col,
            title         = request.POST["title"],
            description   = request.POST.get("description", ""),
            priority      = request.POST.get("priority", "medium"),
            status        = "backlog",
            due_date      = request.POST.get("due_date") or None,
            start_date    = request.POST.get("start_date") or None,
            duration_days = int(request.POST["duration_days"]) if request.POST.get("duration_days") else None,
            tags          = request.POST.get("tags", ""),
            needs_review  = bool(request.POST.get("needs_review")),
            work_saturday = bool(request.POST.get("work_saturday")),
            work_sunday   = bool(request.POST.get("work_sunday")),
            deadline_days = int(request.POST["deadline_days"]) if request.POST.get("deadline_days") else None,
            created_by    = request.user,
        )
        assignee_ids = request.POST.getlist("assignees")
        if assignee_ids:
            task.assignees.set(User.objects.filter(id__in=assignee_ids))
            task.status = "todo"
            todo_col = project.columns.filter(name__iexact="a fazer").first()
            if todo_col:
                task.column = todo_col
            task.save()
            for a in task.assignees.exclude(id=request.user.id):
                _notify(a, f"{request.user} atribuiu «{task.title}» a você", f"/tasks/{task.pk}/")
        else:
            # Sem responsáveis: coloca no Backlog
            if not task.column:
                backlog_col = project.columns.filter(name__iexact="backlog").first()
                if backlog_col:
                    task.column = backlog_col
            task.save()

        for i, st in enumerate(request.POST.get("subtasks", "").splitlines()):
            if st.strip():
                SubTask.objects.create(task=task, title=st.strip(), position=i)

        return JsonResponse({"ok": True, "task_id": str(task.id)})
    return JsonResponse({"ok": False}, status=400)


@login_required
def task_detail(request, pk):
    task = get_object_or_404(
        Task.objects.select_related("project").prefetch_related(
                                      "assignees", "subtasks", "comments__author",
                                      "attachments__uploaded_by", "issues__reported_by",
                                      "issues__comments__author", "issues__comments__mentions"),
        pk=pk,
    )
    if request.user not in task.project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a esta tarefa.")
        return redirect("projects:dashboard")
    all_users    = User.objects.all().order_by("first_name")
    columns      = task.project.columns.all()
    can_create   = task.project.can_create_tasks(request.user)
    is_assignee  = request.user in task.assignees.all()
    open_issue   = task.issues.filter(resolved=False).first()
    proj_members = list(task.project.members.order_by("first_name"))

    # Check-in diário: "É possível executar hoje?"
    from datetime import date as _date
    _today = _date.today()
    today_report = None
    today_day_num = None
    if task.status == "in_progress" and is_assignee and task.start_date and task.duration_days:
        _day = (_today - task.start_date).days + 1
        if _day < 1:
            _day = 1
        if _day <= task.duration_days:
            today_day_num = _day
            today_report = task.daily_reports.filter(date=_today).first()

    blockers          = task.dependencies.select_related("requires").order_by("created_at")
    blocking          = task.required_by.select_related("task").order_by("created_at")
    proj_tasks        = task.project.tasks.exclude(pk=task.pk).only("id", "title", "status").order_by("title")
    has_pending_deps  = blockers.exclude(requires__status="done").exists()

    return render(request, "tasks/detail.html", {
        "task":           task,
        "all_users":      all_users,
        "columns":        columns,
        "can_create":     can_create,
        "is_assignee":    is_assignee,
        "open_issue":     open_issue,
        "proj_members":   proj_members,
        "today_report":   today_report,
        "today_day_num":  today_day_num,
        "blockers":          blockers,
        "blocking":          blocking,
        "proj_tasks":        proj_tasks,
        "has_pending_deps":  has_pending_deps,
    })


@login_required
@require_POST
def task_update(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if not task.project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    data = json.loads(request.body)
    for field in ("title", "description", "priority", "status", "tags", "progress",
                  "work_saturday", "work_sunday"):
        if field in data:
            setattr(task, field, data[field])
    if "due_date" in data:
        task.due_date = data["due_date"] or None
    if "start_date" in data:
        task.start_date = data["start_date"] or None
    if "duration_days" in data:
        task.duration_days = data["duration_days"] or None
    if "column_id" in data:
        col = Column.objects.filter(pk=data["column_id"], project=task.project).first()
        task.column = col
        if col and col.is_done_column:
            task.status       = "done"
            task.completed_at = timezone.now()

    if "assignees" in data:
        old_ids = set(task.assignees.values_list("id", flat=True))
        new_ids = set(str(i) for i in data["assignees"])
        task.assignees.set(User.objects.filter(id__in=new_ids))
        added = new_ids - {str(i) for i in old_ids}
        if added:
            if task.status == "backlog":
                task.status = "todo"
                col = task.project.columns.filter(name__iexact="a fazer").first()
                if col:
                    task.column = col
            for a in task.assignees.filter(id__in=added).exclude(id=request.user.id):
                _notify(a, f"{request.user} atribuiu «{task.title}» a você", f"/tasks/{task.pk}/")

    task.save()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def advance_status(request, pk):
    task = get_object_or_404(Task, pk=pk)

    # Tarefa bloqueada não pode avançar
    if task.is_blocked:
        return JsonResponse({"ok": False, "error": "Tarefa bloqueada por problema em aberto. Aguarde a resolução do gestor."}, status=400)

    if task.status == "backlog":
        # Qualquer membro do projeto pode assumir uma tarefa do backlog
        if not task.project.members.filter(pk=request.user.pk).exists():
            return JsonResponse({"ok": False, "error": "Você não é membro deste projeto."}, status=403)
        task.assignees.add(request.user)
        task.status = "todo"

    elif task.status == "todo":
        if request.user not in task.assignees.all():
            return JsonResponse({"ok": False, "error": "Você não é responsável por esta tarefa."}, status=403)
        pending_deps = task.dependencies.exclude(requires__status="done").select_related("requires")
        if pending_deps.exists():
            titles = " • ".join(d.requires.title for d in pending_deps[:3])
            return JsonResponse({"ok": False, "error": f"Aguardando conclusão de: {titles}"}, status=400)
        task.status     = "in_progress"
        task.started_at = timezone.now()

    elif task.status == "in_progress":
        if request.user not in task.assignees.all():
            return JsonResponse({"ok": False, "error": "Você não é responsável por esta tarefa."}, status=403)
        task.status = "review" if task.needs_review else "done"
        if task.status == "done":
            task.completed_at = timezone.now()

    elif task.status == "review":
        if not task.project.can_create_tasks(request.user):
            return JsonResponse({"ok": False, "error": "Apenas o gestor pode aprovar."}, status=403)
        task.status       = "done"
        task.completed_at = timezone.now()

    else:
        return JsonResponse({"ok": False, "error": "Status não pode avançar."}, status=400)

    _sync_column(task)
    task.save()

    labels = {
        "todo":        "assumiu",
        "in_progress": "iniciou",
        "review":      "enviou para revisão",
        "done":        "concluiu",
    }
    msg = f"{request.user} {labels.get(task.status, 'atualizou')} a tarefa «{task.title}»"
    for m in task.project.members.exclude(id=request.user.id):
        _notify(m, msg, f"/tasks/{task.pk}/")

    return JsonResponse({"ok": True, "new_status": task.status})


@login_required
@require_POST
def report_issue(request, pk):
    """Responsável reporta um problema — bloqueia a tarefa e notifica o gestor."""
    task = get_object_or_404(Task, pk=pk)

    if request.user not in task.assignees.all():
        return JsonResponse({"ok": False, "error": "Apenas o responsável pode reportar problemas."}, status=403)

    if task.is_blocked:
        return JsonResponse({"ok": False, "error": "Já existe um problema em aberto nesta tarefa."}, status=400)

    description = request.POST.get("description", "").strip()
    reason      = request.POST.get("reason", "other")
    if not description:
        return JsonResponse({"ok": False, "error": "Descreva o problema."}, status=400)

    issue = TaskIssue.objects.create(
        task        = task,
        reported_by = request.user,
        reason      = reason,
        description = description,
    )

    # Bloqueia a tarefa
    task.is_blocked = True
    task.save(update_fields=["is_blocked"])

    # Notifica o gestor do projeto
    manager = task.project.manager
    reason_label = dict(TaskIssue.REASON_CHOICES).get(reason, reason)
    if manager:
        _notify(
            manager,
            f"🚨 {request.user} pausou «{task.title}» [{reason_label}]: {description[:80]}",
            f"/tasks/{task.pk}/",
        )
    # Notifica também admins/owners
    for m in task.project.members.filter(role__in=["owner","admin"]).exclude(id=request.user.id):
        _notify(m, f"🚨 Problema reportado em «{task.title}» por {request.user}", f"/tasks/{task.pk}/")

    return JsonResponse({
        "ok":          True,
        "issue_id":    str(issue.id),
        "description": issue.description,
        "created_at":  issue.created_at.strftime("%d/%m/%Y %H:%M"),
    })


@login_required
@require_POST
def pause_task(request, pk):
    """Endpoint para o app mobile pausar uma tarefa (alias de report_issue aceitando JSON)."""
    task = get_object_or_404(Task, pk=pk)

    if request.user not in task.assignees.all():
        return JsonResponse({"ok": False, "error": "Apenas o responsável pode pausar a tarefa."}, status=403)

    if task.is_blocked:
        return JsonResponse({"ok": False, "error": "Já existe um problema em aberto nesta tarefa."}, status=400)

    # Aceita JSON (mobile) ou form data (web)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        data = request.POST

    description = data.get("description", "").strip()
    # mobile envia "type", web envia "reason"
    reason = data.get("reason") or data.get("type") or "other"

    if not description:
        return JsonResponse({"ok": False, "error": "Descreva o problema."}, status=400)

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
        _notify(
            manager,
            f"🚨 {request.user} pausou «{task.title}» [{reason_label}]: {description[:80]}",
            f"/tasks/{task.pk}/",
        )
    for m in task.project.members.filter(role__in=["owner","admin"]).exclude(id=request.user.id):
        _notify(m, f"🚨 Problema reportado em «{task.title}» por {request.user}", f"/tasks/{task.pk}/")

    return JsonResponse({
        "ok":          True,
        "issue_id":    str(issue.id),
        "description": issue.description,
        "created_at":  issue.created_at.strftime("%d/%m/%Y %H:%M"),
    })


@login_required
@require_POST
def edit_issue(request, issue_pk):
    """Responsável edita a descrição do problema antes de ser resolvido."""
    from apps.tasks.models import TaskIssue
    import json
    issue = get_object_or_404(TaskIssue, pk=issue_pk)

    if request.user != issue.reported_by:
        return JsonResponse({"ok": False, "error": "Apenas quem reportou pode editar."}, status=403)

    if issue.resolved:
        return JsonResponse({"ok": False, "error": "Este problema já foi resolvido."}, status=400)

    data = json.loads(request.body)
    description = data.get("description", "").strip()
    if not description:
        return JsonResponse({"ok": False, "error": "Descrição não pode ser vazia."}, status=400)

    issue.description = description
    issue.save(update_fields=["description"])

    # Notifica o gestor sobre a edição
    manager = issue.task.project.manager
    if manager:
        _notify(
            manager,
            f"✏ {request.user} editou o problema em «{issue.task.title}»",
            f"/tasks/{issue.task.pk}/",
        )

    return JsonResponse({"ok": True, "description": issue.description})

@login_required
@require_POST
def resolve_issue(request, issue_pk):
    """Gestor responde ao problema, opcionalmente cria tarefa de suporte e desbloqueia."""
    issue = get_object_or_404(TaskIssue, pk=issue_pk)

    if not issue.task.project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Apenas o gestor pode resolver problemas."}, status=403)

    data     = json.loads(request.body)
    response = data.get("response", "").strip()
    if not response:
        return JsonResponse({"ok": False, "error": "Informe uma resposta."}, status=400)

    issue.manager_response = response
    issue.responded_by     = request.user
    issue.responded_at     = timezone.now()
    issue.resolved         = True

    # Criar tarefa de suporte se informado
    support_task = None
    support_title      = data.get("support_title", "").strip()
    support_assignee_id = data.get("support_assignee")

    if support_title:
        assignee = User.objects.filter(id=support_assignee_id).first() if support_assignee_id else None
        backlog_col = issue.task.project.columns.filter(name__iexact="backlog").first()
        support_task = Task.objects.create(
            project    = issue.task.project,
            column     = backlog_col,
            title      = support_title,
            description = f"Tarefa criada a partir do problema em «{issue.task.title}»:\n\n{issue.description}",
            priority   = "high",
            status     = "backlog",
            created_by = request.user,
        )
        if assignee:
            support_task.assignees.add(assignee)
            support_task.status = "todo"
            todo_col = issue.task.project.columns.filter(name__iexact="a fazer").first()
            if todo_col:
                support_task.column = todo_col
            support_task.save()
            _notify(
                assignee,
                f"{request.user} criou uma tarefa de suporte para você: «{support_title}»",
                f"/tasks/{support_task.pk}/",
            )

        issue.support_task = support_task

    issue.save()

    # Desbloqueia a tarefa original
    issue.task.is_blocked = False
    issue.task.save(update_fields=["is_blocked"])

    # Notifica o responsável que reportou
    if issue.reported_by:
        _notify(
            issue.reported_by,
            f"✅ {request.user} respondeu ao seu problema em «{issue.task.title}»",
            f"/tasks/{issue.task.pk}/",
        )

    return JsonResponse({
        "ok":                True,
        "response":          issue.manager_response,
        "support_task_id":   str(support_task.pk) if support_task else None,
        "support_task_title": support_task.title if support_task else None,
    })


@login_required
@require_POST
def issue_comment_edit(request, comment_pk):
    """Edita o conteúdo de um comentário. Apenas o autor pode editar."""
    import re
    from django.utils.html import escape
    from .models import IssueComment as _IC
    comment = get_object_or_404(_IC, pk=comment_pk)
    if comment.author != request.user:
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    try:
        data = json.loads(request.body)
    except (json.JSONDecodeError, ValueError):
        data = request.POST
    content = data.get("content", "").strip()
    if not content:
        return JsonResponse({"ok": False, "error": "Comentário vazio."}, status=400)
    comment.content = content
    comment.save(update_fields=["content"])
    def highlight(text):
        return re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', escape(text))
    return JsonResponse({"ok": True, "content": content, "content_html": highlight(content)})


@login_required
@require_POST
def issue_comment_add(request, issue_pk):
    """Adiciona comentário na conversa de resolução de uma issue, com suporte a @menções."""
    import re
    from django.utils.html import escape
    issue = get_object_or_404(TaskIssue, pk=issue_pk)

    # Apenas membros do projeto podem comentar
    if not issue.task.project.members.filter(pk=request.user.pk).exists():
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    content = request.POST.get("content", "").strip()
    if not content:
        return JsonResponse({"ok": False, "error": "Comentário vazio."}, status=400)

    comment = IssueComment.objects.create(issue=issue, author=request.user, content=content)

    # Detecta @menções pelo primeiro nome ou username dos membros do projeto
    mentioned_names = re.findall(r'@(\w+)', content)
    members = issue.task.project.members.all()
    notified = set()
    for name in mentioned_names:
        for m in members:
            if (m.first_name.lower() == name.lower() or
                    m.username.lower() == name.lower() or
                    m.get_full_name().lower().startswith(name.lower())):
                if m.pk not in notified:
                    comment.mentions.add(m)
                    if m != request.user:
                        _notify(
                            m,
                            f"💬 {request.user} mencionou você na resolução de «{issue.task.title}»",
                            f"/tasks/{issue.task.pk}/",
                        )
                    notified.add(m.pk)

    # Notifica o reporter e gestor se quem comentou não for nenhum deles
    for recipient in [issue.reported_by, issue.task.project.manager]:
        if recipient and recipient != request.user and recipient.pk not in notified:
            _notify(
                recipient,
                f"💬 {request.user} comentou na resolução de «{issue.task.title}»",
                f"/tasks/{issue.task.pk}/",
            )
            notified.add(recipient.pk)

    # Renderiza o conteúdo com @menções destacadas (escapado para evitar XSS)
    def highlight(text):
        return re.sub(r'@(\w+)', r'<span class="mention">@\1</span>', escape(text))

    return JsonResponse({
        "ok":        True,
        "id":        str(comment.id),
        "author":    request.user.get_full_name() or request.user.username,
        "initials":  request.user.initials,
        "color":     request.user.avatar_color,
        "content":   content,
        "content_html": highlight(content),
        "created_at": comment.created_at.strftime("%d/%m/%Y %H:%M"),
    })


@login_required
@require_POST
def upload_attachment(request, pk):
    """Upload de arquivo ou foto para a tarefa."""
    task = get_object_or_404(Task, pk=pk)

    # Qualquer membro do projeto pode fazer upload
    if request.user not in task.project.members.all():
        return JsonResponse({"ok": False, "error": "Sem acesso."}, status=403)

    f = request.FILES.get("file")
    if not f:
        return JsonResponse({"ok": False, "error": "Nenhum arquivo enviado."}, status=400)

    try:
        validate_generic_upload(f, max_size=10 * 1024 * 1024)
    except ValidationError as e:
        return JsonResponse({"ok": False, "error": e.message}, status=400)

    img_extensions = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".heic"}
    ext      = os.path.splitext(f.name)[1].lower()
    is_image = ext in img_extensions

    attachment = TaskAttachment.objects.create(
        task        = task,
        uploaded_by = request.user,
        file        = f,
        filename    = f.name,
        file_size   = f.size,
        is_image    = is_image,
    )

    from django.urls import reverse
    return JsonResponse({
        "ok":       True,
        "id":       str(attachment.id),
        "filename": attachment.filename,
        "url":      reverse("api:download_attachment", kwargs={"attachment_id": attachment.id}),
        "is_image": attachment.is_image,
        "size":     attachment.file_size,
        "uploaded_by": str(attachment.uploaded_by),
        "created_at":  attachment.created_at.strftime("%d/%m/%Y %H:%M"),
    })


@login_required
@require_POST
def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if not task.project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    project_pk = str(task.project.pk)
    task.delete()
    return JsonResponse({"ok": True, "redirect": f"/dashboard/projects/{project_pk}/"})


@login_required
@require_POST
def subtask_toggle(request, pk):
    st = get_object_or_404(SubTask.objects.select_related("task__project"), pk=pk)
    if request.user not in st.task.project.members.all() and not request.user.is_superuser:
        return JsonResponse({"ok": False, "error": "Sem acesso."}, status=403)
    st.done = not st.done
    st.save(update_fields=["done"])
    task  = st.task
    total = task.subtasks.count()
    done  = task.subtasks.filter(done=True).count()
    task.progress = int(done / total * 100) if total else 0
    task.save(update_fields=["progress"])
    return JsonResponse({"ok": True, "done": st.done, "progress": task.progress})


@login_required
def my_tasks_view(request):
    """Visão unificada de tarefas do usuário com filtros."""
    scope  = request.GET.get("scope", "mine")   # mine | all
    status = request.GET.get("status", "")       # done | overdue | blocked | ''
    priority = request.GET.get("priority", "")

    if scope == "all" and request.user.can_manage:
        qs = Task.objects.filter(project__members=request.user).exclude(status="archived")
    else:
        qs = Task.objects.filter(assignees=request.user).exclude(status="archived")

    if status == "done":
        qs = qs.filter(status="done")
    elif status == "overdue":
        qs = qs.exclude(status__in=["done", "archived"]).filter(due_date__lt=date.today())
    elif status == "blocked":
        qs = qs.filter(is_blocked=True)
    elif status == "in_progress":
        qs = qs.filter(status="in_progress")
    elif status == "review":
        qs = qs.filter(status="review")

    if priority:
        qs = qs.filter(priority=priority)

    qs = qs.select_related("project", "column").prefetch_related("assignees").order_by("-updated_at")

    counts = {
        "mine_active":  Task.objects.filter(assignees=request.user).exclude(status__in=["done","archived"]).count(),
        "overdue":      Task.objects.filter(assignees=request.user).exclude(status__in=["done","archived"]).filter(due_date__lt=date.today()).count(),
        "blocked":      Task.objects.filter(assignees=request.user, is_blocked=True).count(),
        "done":         Task.objects.filter(assignees=request.user, status="done").count(),
    }

    return render(request, "tasks/my_tasks.html", {
        "tasks":    qs,
        "scope":    scope,
        "status":   status,
        "priority": priority,
        "counts":   counts,
        "today":    date.today(),
    })


@login_required
def daily_report_view(request, task_pk):
    """Relatório diário de uma tarefa. GET=página, POST=salvar dia."""
    task = get_object_or_404(
        Task.objects.select_related("project").prefetch_related("assignees"),
        pk=task_pk,
    )

    # Apenas membros do projeto podem ver
    if request.user not in task.project.members.all():
        return redirect("/dashboard/")

    if request.method == "POST":
        data         = json.loads(request.body)
        day_num      = int(data.get("day", 0))
        accomplished = data.get("accomplished")  # true/false/null
        notes        = data.get("notes", "").strip()

        if not day_num or not task.start_date or not task.duration_days:
            return JsonResponse({"ok": False, "error": "Tarefa sem datas configuradas."}, status=400)

        if day_num < 1 or day_num > task.duration_days:
            return JsonResponse({"ok": False, "error": "Dia inválido."}, status=400)

        day_date = task.start_date + timedelta(days=day_num - 1)

        report, _ = DailyReport.objects.update_or_create(
            task=task,
            day=day_num,
            defaults={
                "date":         day_date,
                "accomplished": accomplished,
                "notes":        notes,
                "created_by":   request.user,
            },
        )

        return JsonResponse({
            "ok":          True,
            "id":          str(report.id),
            "day":         report.day,
            "accomplished": report.accomplished,
            "notes":        report.notes,
            "status_label": report.status_label,
        })

    # GET — monta os slots de dias
    day_slots = []
    if task.start_date and task.duration_days:
        existing = {r.day: r for r in task.daily_reports.all()}
        for i in range(1, task.duration_days + 1):
            d   = task.start_date + timedelta(days=i - 1)
            rep = existing.get(i)
            day_slots.append({
                "day":         i,
                "date":        d,
                "report":      rep,
                "accomplished": rep.accomplished if rep else None,
                "notes":        rep.notes if rep else "",
            })

    accomplished_count     = sum(1 for s in day_slots if s["accomplished"] is True)
    not_accomplished_count = sum(1 for s in day_slots if s["accomplished"] is False)
    pending_count          = sum(1 for s in day_slots if s["accomplished"] is None)

    return render(request, "tasks/daily_report.html", {
        "task":                  task,
        "day_slots":             day_slots,
        "accomplished_count":    accomplished_count,
        "not_accomplished_count": not_accomplished_count,
        "pending_count":         pending_count,
    })


@login_required
@require_POST
def dependency_add(request, pk):
    """Gestor adiciona dependência: tarefa pk só inicia após 'requires' estar concluída."""
    task = get_object_or_404(Task, pk=pk)
    if not task.project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    data        = json.loads(request.body)
    requires_id = data.get("requires")
    if not requires_id:
        return JsonResponse({"ok": False, "error": "Informe a tarefa bloqueadora."}, status=400)

    requires = Task.objects.filter(pk=requires_id, project=task.project).first()
    if not requires:
        return JsonResponse({"ok": False, "error": "Tarefa não encontrada no projeto."}, status=404)
    if requires.pk == task.pk:
        return JsonResponse({"ok": False, "error": "Uma tarefa não pode depender de si mesma."}, status=400)

    # Detecta ciclo
    if _dep_has_cycle(requires, task):
        return JsonResponse({"ok": False, "error": "Dependência circular detectada."}, status=400)

    dep, _ = TaskDependency.objects.get_or_create(task=task, requires=requires)
    return JsonResponse({
        "ok":             True,
        "dep_id":         str(dep.id),
        "requires_id":    str(requires.id),
        "requires_title": requires.title,
        "requires_status": requires.status,
    })


def _dep_has_cycle(start_task, target_task):
    """Retorna True se adicionar target_task como bloqueador de start_task cria ciclo."""
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


@login_required
@require_POST
def dependency_remove(request, pk, dep_id):
    """Gestor remove uma dependência."""
    task = get_object_or_404(Task, pk=pk)
    if not task.project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)

    dep = get_object_or_404(TaskDependency, pk=dep_id, task=task)
    dep.delete()
    return JsonResponse({"ok": True})


@login_required
@require_POST
def comment_add(request, task_pk):
    task = get_object_or_404(Task.objects.select_related("project"), pk=task_pk)
    if request.user not in task.project.members.all() and not request.user.is_superuser:
        return JsonResponse({"ok": False, "error": "Sem acesso."}, status=403)
    content = request.POST.get("content", "").strip()
    if content:
        c = Comment.objects.create(task=task, author=request.user, content=content)
        members = set(task.assignees.all())
        if task.created_by:
            members.add(task.created_by)
        for m in members:
            if m != request.user:
                _notify(m, f"{request.user} comentou em «{task.title}»", f"/tasks/{task.pk}/")
        return JsonResponse({
            "ok": True, "id": str(c.id), "content": c.content,
            "author": str(c.author),
            "initials": c.author.initials if c.author else "?",
            "color": c.author.avatar_color if c.author else "#888",
            "created_at": c.created_at.strftime("%d/%m/%Y %H:%M"),
        })
    return JsonResponse({"ok": False}, status=400)
