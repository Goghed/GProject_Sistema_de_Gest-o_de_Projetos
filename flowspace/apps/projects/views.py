import json
from datetime import date, timedelta
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import JsonResponse
from django.views.decorators.http import require_POST
from django.utils import timezone
from django.db.models import Prefetch
from .models import Project, Column, ProjectDocument, ProjectMemberActivity, EquipeTecnica, AtribuicaoEquipe, ProjectPauseNote
from apps.tasks.models import Task, TaskDependency
from apps.accounts.models import User
from apps.common.uploads import validate_image_upload, validate_generic_upload
from .forms import ProjectDocumentForm


def _month_context():
    today = date.today()
    months = []
    for i in range(6):
        month_num = (today.month - 1 + i) % 12 + 1
        year_num  = today.year + ((today.month - 1 + i) // 12)
        months.append({
            "name": date(year_num, month_num, 1).strftime("%b"),
            "current": month_num == today.month and year_num == today.year,
        })
    return months


def _bar_position(proj, total_days=180):
    today = date.today()
    start = proj.start_date or today
    end   = proj.due_date   or (today + timedelta(days=30))
    left  = max(0, (start - today).days / total_days * 100)
    width = max(3, (end - start).days / total_days * 100)
    width = min(width, 100 - left)
    return round(left, 1), round(width, 1)


_GANTT_STATUS_LABEL = {
    "backlog": "Backlog", "todo": "A fazer", "in_progress": "Em progresso",
    "review": "Review", "done": "Concluído",
}
_GANTT_PRIORITY_LABEL = {"urgent": "Urgente", "high": "Alta", "medium": "Média", "low": "Baixa"}


def _build_gantt_rows(proj_list, today):
    """Monta as linhas do mini-Gantt 'Status dos Projetos' do dashboard.
    Compartilhado entre o render inicial (dashboard) e o polling ao vivo
    (dashboard_stats_json), pra nunca haver divergência entre os dois."""
    from apps.tasks.models import Task as _Task
    from django.db.models import Min as _Min

    _earliest = _Task.objects.filter(
        project__in=proj_list
    ).exclude(status="archived").aggregate(
        s=_Min("start_date"), d=_Min("due_date")
    )
    _candidates = [d for d in [_earliest["s"], _earliest["d"], today - timedelta(days=7)] if d]
    gantt_dash_start = min(_candidates) - timedelta(days=3)
    gantt_dash_end   = today + timedelta(days=83)
    gantt_rows       = []
    for p in proj_list:
        # Gantt mostra todas as tarefas do projeto para todos os usuários acompanharem
        gd_tasks_qs = list(
            _Task.objects
            .filter(project=p)
            .exclude(status="archived")
            .prefetch_related("assignees", "issues", "subtasks")
            .order_by("status", "position")
        )
        gd_tasks = []
        for t in gd_tasks_qs:
            t_start = t.start_date
            if not t_start and t.due_date and t.duration_days:
                t_start = t.due_date - timedelta(days=t.duration_days - 1)
            if not t_start:
                # Sem data inicial explícita: usa due_date como bloco de um dia
                t_start = t.due_date or today
            t_end = t.due_date or t_start
            if t.duration_days:
                t_end = max(t_end, t_start + timedelta(days=t.duration_days - 1))
            if t.status == "done":          c = p.color
            elif t.is_blocked:              c = "#fbbf24"
            elif t.status == "review":      c = "#a855f7"
            elif t.status == "in_progress":  c = "#0ea5e9"
            else:                           c = "#c7c7d4"   # backlog / todo
            issue_dates = [
                timezone.localtime(issue.created_at).date().isoformat()
                for issue in t.issues.all()
                if not issue.resolved
            ]
            all_subs  = list(t.subtasks.all())
            sub_total = len(all_subs)
            sub_done  = sum(1 for s in all_subs if s.done)
            gd_tasks.append({
                "id":             str(t.pk),
                "title":          t.title,
                "status":         "blocked" if t.is_blocked else t.status,
                "status_display": "Bloqueada" if t.is_blocked else _GANTT_STATUS_LABEL.get(t.status, t.status),
                "priority":       _GANTT_PRIORITY_LABEL.get(t.priority, t.priority),
                "start":          t_start.isoformat(),
                "end":            t_end.isoformat(),
                "color":          c,
                "url":            f"/tasks/{t.pk}/",
                "due":            t.due_date.strftime("%d/%m/%Y") if t.due_date else "—",
                "due_date_iso":   t.due_date.isoformat() if t.due_date else None,
                "assignees":      [{"initials": a.initials, "color": a.avatar_color}
                                   for a in t.assignees.all()[:3]],
                "issue_dates":    issue_dates,
                "work_saturday":  t.work_saturday,
                "work_sunday":    t.work_sunday,
                "subtask_total":  sub_total,
                "subtask_done":   sub_done,
                "is_blocked":     t.is_blocked,
            })
        gantt_rows.append({
            "name":     p.name,
            "proj_url": f"/dashboard/projects/{p.pk}/",
            "color":    p.color,
            "tasks":    gd_tasks,
        })
    return gantt_rows, gantt_dash_start, gantt_dash_end


def _get_equipes(cidade_filter):
    equipes_qs = EquipeTecnica.objects.filter(status="ativa").select_related("tecnico_user", "auxiliar_user")
    if cidade_filter:
        equipes_qs = equipes_qs.filter(cidade=cidade_filter)
    return list(
        equipes_qs.prefetch_related(
            Prefetch(
                "atribuicoes",
                queryset=AtribuicaoEquipe.objects.select_related("projeto").order_by("posicao"),
            )
        )
    )


@login_required
def dashboard(request):
    import json as _json
    today     = date.today()
    user      = request.user
    cidade_filter = request.GET.get("cidade", "").strip().lower()
    if cidade_filter not in ("londrina", "itu"):
        cidade_filter = ""

    projects  = Project.objects.all().prefetch_related("tasks","members")
    if cidade_filter:
        projects = projects.filter(cidade=cidade_filter)
    active       = projects.filter(status__in=["active","on_hold"])
    non_archived = projects.exclude(status="archived")
    all_tasks = Task.objects.filter(project__in=active).exclude(status="archived")
    stats = {
        "projects":           active.count(),
        "projects_completed": projects.filter(status="completed").count(),
        "open_tasks":         all_tasks.exclude(status__in=["done","archived"]).count(),
        "done_tasks":         Task.objects.filter(project__in=non_archived, status="done").count(),
        "overdue":            all_tasks.filter(due_date__lt=today).exclude(status__in=["done","archived"]).count(),
    }
    recent_tasks = all_tasks.exclude(status__in=["done","archived"]).order_by("-updated_at")[:8]
    proj_list = list(active.distinct())

    # ── Status por projeto (todos os status, sem filtro de data) ─────────────
    _STATUS_ORDER = {"backlog": 0, "todo": 1, "in_progress": 2, "review": 3, "done": 4}
    _STATUS_LABEL = {
        "backlog": "Backlog", "todo": "A fazer", "in_progress": "Em progresso",
        "review": "Review", "done": "Concluído",
    }

    timeline_rows = []
    for p in proj_list:
        tasks_qs = list(p.tasks.exclude(status="archived"))
        tasks_qs.sort(key=lambda t: (_STATUS_ORDER.get(t.status, 9), t.title))
        task_dots = []
        for t in tasks_qs:
            if t.status == "done":
                color = p.color
            elif t.is_blocked:
                color = "#fbbf24"
            elif t.status == "review":
                color = "#a855f7"
            elif t.status == "in_progress":
                color = "#0ea5e9"
            else:
                color = "#c7c7d4"   # backlog / a fazer
            due_label = t.due_date.strftime("%d/%m/%Y") if t.due_date else ""
            status_label = _STATUS_LABEL.get(t.status, t.status)
            task_dots.append({
                "title":   t.title,
                "color":   color,
                "url":     f"/tasks/{t.pk}/",
                "tooltip": f"{t.title} · {status_label}{' · ' + due_label if due_label else ''}",
            })
        timeline_rows.append({
            "name":      p.name,
            "proj_url":  f"/dashboard/projects/{p.pk}/",
            "task_dots": task_dots,
        })

    # Calendário: 1º dia do mês anterior, alinhado à segunda-feira anterior
    from django.db.models import Q as _Q
    _wm = today.month - 1 or 12
    _wy = today.year if today.month > 1 else today.year - 1
    _first = date(_wy, _wm, 1)
    window_start = _first - timedelta(days=_first.weekday())  # recua até segunda
    window_end   = window_start + timedelta(weeks=18)

    from apps.tasks.models import TaskIssue as _TaskIssue
    cal_tasks_qs = (
        Task.objects
        .filter(_Q(start_date__isnull=False) | _Q(due_date__isnull=False))
        .exclude(status="archived")
        .select_related("project")
        .prefetch_related("issues")
    )

    cal_tasks_data = []
    for t in cal_tasks_qs:
        # Determina start e duração
        if t.start_date:
            t_start = t.start_date
            if t.duration_days:
                duration = t.duration_days
            elif t.due_date and t.due_date >= t.start_date:
                duration = (t.due_date - t.start_date).days + 1
            else:
                duration = 1
        else:
            # Sem start_date: usa data de criação como início
            created = timezone.localtime(t.created_at).date() if t.created_at else t.due_date
            t_start = created
            if t.due_date >= created:
                duration = (t.due_date - created).days + 1
            else:
                duration = 1
        t_end = t_start + timedelta(days=duration - 1)
        # Inclui se tiver qualquer sobreposição com a janela
        if t_end >= window_start and t_start <= window_end:
            # Dias pausados: data de cada issue não resolvida
            pause_dates = []
            for issue in t.issues.all():
                issue_day = timezone.localtime(issue.created_at).date()
                pause_dates.append({
                    "date":     issue_day.isoformat(),
                    "resolved": issue.resolved,
                    "reason":   issue.get_reason_display() if hasattr(issue, 'get_reason_display') else "",
                })
            cal_tasks_data.append({
                "id":          str(t.id),
                "title":       t.title,
                "start":       t_start.isoformat(),
                "duration":    duration,
                "color":       t.project.color,
                "project":     t.project.name,
                "status":      t.status,
                "url":         f"/tasks/{t.id}/",
                "pause_dates": pause_dates,
            })

    # ── Mini Gantt e Equipes Técnicas — compartilhados com o polling ao vivo ──
    gantt_rows, gantt_dash_start, gantt_dash_end = _build_gantt_rows(proj_list, today)
    equipes = _get_equipes(cidade_filter)

    return render(request, "projects/dashboard.html", {
        "projects":         proj_list,
        "stats":            stats,
        "recent_tasks":     recent_tasks,
        "equipes":          equipes,
        "months":           _month_context(),
        "today":            today,
        "today_plus3":      today + timedelta(days=3),
        "cal_tasks_json":   _json.dumps(cal_tasks_data),
        "cal_start":        window_start.isoformat(),
        "cal_weeks":        16,
        "timeline_rows":    timeline_rows,
        "gantt_rows_json":  _json.dumps(gantt_rows,      ensure_ascii=False),
        "gantt_dash_start": gantt_dash_start.isoformat(),
        "gantt_dash_end":   gantt_dash_end.isoformat(),
        "cidade_filter":    cidade_filter,
    })


@login_required
def equipes_view(request):
    import json as _json

    CARD_COLORS = ["#5b4cf5","#0ea5e9","#34d399","#f59e0b","#ff6b6b","#a855f7","#ec4899","#14b8a6"]
    CITY_COLORS = {"itu": "#ca8a04", "londrina": "#dc2626"}  # amarelo / vermelho

    if request.method == "POST":
        if not request.user.can_manage:
            messages.error(request, "Sem permissão.")
            return redirect("projects:equipes")

        action = request.POST.get("action", "")

        def _resolve_user(uid):
            return User.objects.filter(pk=uid).first() if uid else None

        if action == "add_equipe":
            t_user = _resolve_user(request.POST.get("tecnico_user_id"))
            a_user = _resolve_user(request.POST.get("auxiliar_user_id"))
            tecnico_nome  = request.POST.get("tecnico", "").strip() or (t_user.get_full_name() if t_user else "")
            auxiliar_nome = request.POST.get("auxiliar", "").strip() or (a_user.get_full_name() if a_user else "")
            _eq_cidade = request.POST.get("cidade", "").strip()
            if _eq_cidade not in ("londrina", "itu"):
                _eq_cidade = ""
            equipe = EquipeTecnica.objects.create(
                tecnico       = tecnico_nome,
                tecnico_user  = t_user,
                auxiliar      = auxiliar_nome,
                auxiliar_user = a_user,
                veiculo       = request.POST.get("veiculo", "").strip(),
                placa         = request.POST.get("placa", "").strip().upper(),
                cidade        = _eq_cidade,
                ordem         = int(request.POST.get("ordem") or 0),
            )
            for field_name, file_key in (("foto", "foto"), ("foto_auxiliar", "foto_auxiliar")):
                if request.FILES.get(file_key):
                    try:
                        validate_image_upload(request.FILES[file_key])
                    except ValidationError as e:
                        equipe.delete()
                        messages.error(request, e.message)
                        return redirect("projects:equipes")
                    setattr(equipe, field_name, request.FILES[file_key])
            equipe.save()
            messages.success(request, "Equipe criada com sucesso.")

        elif action == "edit_equipe":
            equipe = get_object_or_404(EquipeTecnica, pk=request.POST.get("equipe_id"))
            t_user = _resolve_user(request.POST.get("tecnico_user_id"))
            a_user = _resolve_user(request.POST.get("auxiliar_user_id"))
            _eq_cidade = request.POST.get("cidade", "").strip()
            equipe.tecnico       = request.POST.get("tecnico", "").strip() or (t_user.get_full_name() if t_user else equipe.tecnico)
            equipe.tecnico_user  = t_user
            equipe.auxiliar      = request.POST.get("auxiliar", "").strip() or (a_user.get_full_name() if a_user else "")
            equipe.auxiliar_user = a_user
            equipe.veiculo       = request.POST.get("veiculo", "").strip()
            equipe.placa         = request.POST.get("placa", "").strip().upper()
            equipe.cidade        = _eq_cidade if _eq_cidade in ("londrina", "itu") else ""
            equipe.ordem         = int(request.POST.get("ordem") or 0)
            _status = request.POST.get("status", "ativa")
            equipe.status        = _status if _status in dict(EquipeTecnica.STATUS_CHOICES) else "ativa"
            for field_name, file_key in (("foto", "foto"), ("foto_auxiliar", "foto_auxiliar")):
                if request.FILES.get(file_key):
                    try:
                        validate_image_upload(request.FILES[file_key])
                    except ValidationError as e:
                        messages.error(request, e.message)
                        return redirect("projects:equipes")
                    setattr(equipe, field_name, request.FILES[file_key])
            equipe.save()
            messages.success(request, "Equipe atualizada.")

        elif action == "delete_equipe":
            EquipeTecnica.objects.filter(pk=request.POST.get("equipe_id")).delete()
            messages.success(request, "Equipe excluída.")

        elif action == "save_fila":
            equipe = get_object_or_404(
                EquipeTecnica.objects.select_related("tecnico_user", "auxiliar_user"),
                pk=request.POST.get("equipe_id"),
            )
            membros_equipe = equipe.membros_sistema()
            for pos in range(4):
                projeto_id = request.POST.get(f"s{pos}_projeto") or None
                tipo   = request.POST.get(f"s{pos}_tipo",    "").strip()
                varejo = request.POST.get(f"s{pos}_varejo",  "").strip()
                dias   = request.POST.get(f"s{pos}_dias",    "").strip()
                d_ini  = request.POST.get(f"s{pos}_inicio")  or None
                d_fim  = request.POST.get(f"s{pos}_termino") or None
                projeto = Project.objects.filter(pk=projeto_id).first() if projeto_id else None
                if any([projeto, tipo, varejo, dias, d_ini, d_fim]):
                    AtribuicaoEquipe.objects.update_or_create(
                        equipe=equipe, posicao=pos,
                        defaults=dict(projeto=projeto, tipo_instalacao=tipo,
                                      varejo_projeto=varejo, dias_execucao=dias,
                                      data_inicio=d_ini, data_termino=d_fim),
                    )
                    # Auto-adiciona membros da equipe ao projeto
                    if projeto and membros_equipe:
                        projeto.members.add(*membros_equipe)
                else:
                    AtribuicaoEquipe.objects.filter(equipe=equipe, posicao=pos).delete()
            messages.success(request, "Fila atualizada. Membros da equipe adicionados aos projetos.")

        _cf = request.POST.get("cidade_filter", "").strip().lower()
        if _cf not in ("londrina", "itu"):
            _cf = ""
        from django.urls import reverse as _rev
        _rurl = _rev("projects:equipes") + (f"?cidade={_cf}" if _cf else "")
        return redirect(_rurl)

    cidade_filter = request.GET.get("cidade", "").strip().lower()
    if cidade_filter not in ("londrina", "itu"):
        cidade_filter = ""
    status_filter = request.GET.get("status", "").strip().lower()
    if status_filter not in dict(EquipeTecnica.STATUS_CHOICES):
        status_filter = ""

    eq_qs = EquipeTecnica.objects.select_related("tecnico_user", "auxiliar_user").prefetch_related(
        Prefetch("atribuicoes", queryset=AtribuicaoEquipe.objects.select_related("projeto").prefetch_related("projeto__pause_notes").order_by("posicao"))
    ).order_by("ordem", "tecnico")
    if cidade_filter:
        eq_qs = eq_qs.filter(cidade=cidade_filter)
    if status_filter:
        eq_qs = eq_qs.filter(status=status_filter)
    raw = list(eq_qs)

    equipes = []
    for i, e in enumerate(raw):
        atribs   = list(e.atribuicoes.all())
        slot_map = {a.posicao: a for a in atribs}
        slots_js = {}
        for pos, a in slot_map.items():
            slots_js[pos] = {
                "projeto_id": str(a.projeto_id) if a.projeto_id else "",
                "tipo":    a.tipo_instalacao,
                "varejo":  a.varejo_projeto,
                "dias":    a.dias_execucao,
                "inicio":  a.data_inicio.strftime("%Y-%m-%d")  if a.data_inicio  else "",
                "termino": a.data_termino.strftime("%Y-%m-%d") if a.data_termino else "",
            }
        equipes.append({
            "obj":             e,
            "color":           CITY_COLORS.get(e.cidade, CARD_COLORS[i % len(CARD_COLORS)]),
            "slot_atual":      slot_map.get(0),
            "slot_fila1":      slot_map.get(1),
            "slot_fila2":      slot_map.get(2),
            "slot_fila3":      slot_map.get(3),
            "slots_json":      _json.dumps(slots_js),
            "tecnico_user_id": str(e.tecnico_user_id) if e.tecnico_user_id else "",
            "auxiliar_user_id":str(e.auxiliar_user_id) if e.auxiliar_user_id else "",
        })

    em_campo_count = sum(1 for e in equipes if e["slot_atual"])
    all_projects = list(Project.objects.filter(status__in=["active","on_hold"]).order_by("name"))
    all_users    = list(User.objects.filter(is_active=True).order_by("first_name", "last_name"))

    _count_base = EquipeTecnica.objects.all()
    if cidade_filter:
        _count_base = _count_base.filter(cidade=cidade_filter)
    status_counts = {
        "total":   _count_base.count(),
        "ativa":   _count_base.filter(status="ativa").count(),
        "inativa": _count_base.filter(status="inativa").count(),
        "ferias":  _count_base.filter(status="ferias").count(),
    }

    return render(request, "projects/equipes.html", {
        "equipes":        equipes,
        "em_campo_count": em_campo_count,
        "all_projects":   all_projects,
        "all_users":      all_users,
        "cidade_filter":  cidade_filter,
        "status_filter":  status_filter,
        "status_counts":  status_counts,
    })


@login_required
@require_POST
def equipe_reorder(request, equipe_id):
    """Arrastar-e-soltar: troca o projeto (e todos os dados do slot) entre
    duas posições da fila de uma equipe — usado tanto pelo card quanto pelo
    modal 'Gerenciar Fila'."""
    if not request.user.can_manage:
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    try:
        data = json.loads(request.body)
        from_pos = int(data.get("from_posicao"))
        to_pos   = int(data.get("to_posicao"))
    except (TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"ok": False, "error": "Dados inválidos."}, status=400)
    if from_pos == to_pos or from_pos not in range(4) or to_pos not in range(4):
        return JsonResponse({"ok": False, "error": "Posições inválidas."}, status=400)

    equipe = get_object_or_404(EquipeTecnica, pk=equipe_id)
    FIELDS = ["projeto", "tipo_instalacao", "varejo_projeto", "dias_execucao", "data_inicio", "data_termino"]
    a_from = AtribuicaoEquipe.objects.filter(equipe=equipe, posicao=from_pos).first()
    a_to   = AtribuicaoEquipe.objects.filter(equipe=equipe, posicao=to_pos).first()
    vals_from = {f: getattr(a_from, f) for f in FIELDS} if a_from else None
    vals_to   = {f: getattr(a_to, f) for f in FIELDS} if a_to else None

    def _apply(pos, vals):
        if vals is None:
            AtribuicaoEquipe.objects.filter(equipe=equipe, posicao=pos).delete()
        else:
            AtribuicaoEquipe.objects.update_or_create(equipe=equipe, posicao=pos, defaults=vals)

    _apply(from_pos, vals_to)
    _apply(to_pos, vals_from)

    # Mesmo comportamento do save_fila: quem assume o slot "Atualmente" tem
    # a equipe auto-adicionada como membro do projeto.
    if from_pos == 0 or to_pos == 0:
        atual = AtribuicaoEquipe.objects.filter(equipe=equipe, posicao=0, projeto__isnull=False).select_related("projeto").first()
        if atual:
            atual.projeto.members.add(*equipe.membros_sistema())

    return JsonResponse({"ok": True})


@login_required
@require_POST
def project_pause(request, pk):
    """Pausa o projeto (status vira 'on_hold' em todo o sistema) e registra o
    motivo — aparece como sirene no card da equipe que está nele."""
    if not request.user.can_manage:
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    project = get_object_or_404(Project, pk=pk)
    note = request.POST.get("note", "").strip()
    if not note:
        return JsonResponse({"ok": False, "error": "Descreva o motivo da pausa."}, status=400)
    project.status = "on_hold"
    project.save(update_fields=["status"])
    ProjectPauseNote.objects.create(project=project, note=note, created_by=request.user)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def project_resume(request, pk):
    """Retoma um projeto pausado (volta para 'active')."""
    if not request.user.can_manage:
        return JsonResponse({"ok": False, "error": "Sem permissão."}, status=403)
    project = get_object_or_404(Project, pk=pk)
    project.status = "active"
    project.save(update_fields=["status"])
    return JsonResponse({"ok": True})


@login_required
def project_list(request):
    cidade_filter = request.GET.get("cidade", "").strip().lower()
    if cidade_filter not in ("londrina", "itu"):
        cidade_filter = ""
    status_filter = request.GET.get("status", "").strip().lower()
    if status_filter not in ("active", "completed"):
        status_filter = ""
    projects = Project.objects.order_by("-updated_at")
    if cidade_filter:
        projects = projects.filter(cidade=cidade_filter)
    if status_filter == "active":
        projects = projects.filter(status__in=["active", "on_hold"])
    elif status_filter == "completed":
        projects = projects.filter(status="completed")
    return render(request, "projects/list.html", {
        "projects": projects, "cidade_filter": cidade_filter, "status_filter": status_filter,
    })


@login_required
def project_create(request):
    colors = [("#5b4cf5","Violeta"),("#0ea5e9","Azul"),("#34d399","Verde"),("#fbbf24","Âmbar"),("#ff6b6b","Coral"),("#a855f7","Roxo"),("#ec4899","Rosa"),("#14b8a6","Teal")]
    eligible_managers = User.objects.filter(role__in=["owner","admin","manager"]).order_by("first_name")
    all_users = User.objects.all().order_by("first_name")

    if request.method == "POST":
        # Campos básicos
        cover = request.FILES.get("cover_image")
        if cover:
            try:
                validate_image_upload(cover, max_size=8 * 1024 * 1024)
            except ValidationError as e:
                messages.error(request, e.message)
                return render(request, "projects/create.html", {"colors": colors, "eligible_managers": eligible_managers, "all_users": all_users})

        _cidade = request.POST.get("cidade", "").strip()
        if _cidade not in ("londrina", "itu"):
            _cidade = ""
        p = Project.objects.create(
            name        = request.POST["name"],
            description = request.POST.get("description", ""),
            scope       = request.POST.get("scope", ""),
            color       = request.POST.get("color", "#5b4cf5"),
            cidade      = _cidade,
            start_date  = request.POST.get("start_date") or None,
            due_date    = request.POST.get("due_date") or None,
            owner       = request.user,
            cover_image = cover or None,
        )

        # Gestor
        manager_id = request.POST.get("manager")
        if manager_id:
            manager = User.objects.filter(id=manager_id).first()
            if manager:
                p.manager = manager
                p.save(update_fields=["manager"])

        # Membros + atividades
        member_ids    = request.POST.getlist("members")
        activities    = request.POST.getlist("member_activities")  # mesma ordem que member_ids
        member_ids_set = set(member_ids)
        member_ids_set.add(str(request.user.id))
        if manager_id:
            member_ids_set.add(manager_id)

        p.members.set(User.objects.filter(id__in=member_ids_set))

        for uid, activity in zip(member_ids, activities):
            if uid:
                user_obj = User.objects.filter(id=uid).first()
                if user_obj:
                    ProjectMemberActivity.objects.create(
                        project=p, user=user_obj, activity=activity.strip()
                    )

        # Arquivos e documentos
        titles = request.POST.getlist("doc_titles")
        descs  = request.POST.getlist("doc_descs")
        files  = request.FILES.getlist("doc_files")
        for f, title, desc in zip(files, titles, descs):
            try:
                validate_generic_upload(f, max_size=20 * 1024 * 1024)
            except ValidationError:
                continue  # pula arquivos inválidos ou grandes demais silenciosamente
            ProjectDocument.objects.create(
                project     = p,
                title       = title.strip() or f.name,
                file        = f,
                description = desc.strip(),
                uploaded_by = request.user,
            )

        # Colunas padrão
        for name, color, done, pos in [("Backlog","#8888aa",False,0),("A Fazer","#5b4cf5",False,1),("Em Progresso","#0ea5e9",False,2),("Review","#fbbf24",False,3),("Concluído","#34d399",True,4)]:
            Column.objects.create(project=p, name=name, color=color, is_done_column=done, position=pos)

        messages.success(request, f"Projeto '{p.name}' criado!")
        return redirect("projects:kanban", pk=p.pk)

    return render(request, "projects/create.html", {
        "colors":            colors,
        "eligible_managers": eligible_managers,
        "all_users":         all_users,
    })


@login_required
def project_kanban(request, pk):
    from django.db.models import Exists, OuterRef, Prefetch
    project = get_object_or_404(
        Project.objects.prefetch_related("members"),
        pk=pk,
    )
    if request.user not in project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a este projeto.")
        return redirect("projects:dashboard")
    today = date.today()
    can_report = project.can_create_tasks(request.user)

    pending_dep_subq = TaskDependency.objects.filter(
        task_id=OuterRef("pk")
    ).exclude(requires__status="done")

    task_qs = Task.objects.prefetch_related(
        "assignees", "subtasks", "daily_reports"
    ).annotate(has_pending_deps=Exists(pending_dep_subq))

    return render(request, "projects/kanban.html", {
        "project":     project,
        "columns":     project.columns.prefetch_related(
            Prefetch("tasks", queryset=task_qs)
        ),
        "all_users":   User.objects.all().order_by("first_name"),
        "today":       today,
        "today_plus3": today + timedelta(days=3),
        "can_report":  can_report,
    })


@login_required
def project_timeline(request, pk):
    import json as _json
    project = get_object_or_404(Project, pk=pk)
    if request.user not in project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a este projeto.")
        return redirect("projects:dashboard")
    tasks   = list(
        project.tasks.exclude(status="archived")
        .prefetch_related("assignees")
        .order_by("due_date", "position")
    )
    today = date.today()

    # ── Calcula o intervalo de datas do Gantt ─────────────────────────────────
    all_dates = [today]  # sempre inclui hoje
    if project.start_date: all_dates.append(project.start_date)
    if project.due_date:   all_dates.append(project.due_date)
    for t in tasks:
        all_dates.append(t.created_at.date())       # sempre tem created_at
        if t.start_date:    all_dates.append(t.start_date)
        if t.due_date:      all_dates.append(t.due_date)

    g_start = min(all_dates) - timedelta(days=3)
    g_end   = max(all_dates) + timedelta(days=7)

    # ── Serializa as tarefas para o JS ────────────────────────────────────────
    tasks_data = []
    for t in tasks:
        # Calcula start: start_date > due_date-duration > created_at
        t_start = t.start_date
        if not t_start and t.due_date and t.duration_days:
            t_start = t.due_date - timedelta(days=t.duration_days - 1)
        if not t_start:
            t_start = t.created_at.date()  # fallback: data de criação

        # Calcula end: due_date > hoje
        t_end = t.due_date or today

        tasks_data.append({
            "id":         str(t.pk),
            "title":      t.title,
            "status":     t.status,
            "priority":   t.priority,
            "is_blocked": t.is_blocked,
            "start":      str(t_start),
            "end":        str(t_end),
            "url":        f"/tasks/{t.pk}/",
            "assignees":  [a.initials for a in t.assignees.all()[:3]],
            "av_colors":  [a.avatar_color for a in t.assignees.all()[:3]],
        })

    return render(request, "projects/timeline.html", {
        "project":     project,
        "tasks":       tasks,
        "tasks_json":  _json.dumps(tasks_data, ensure_ascii=False),
        "gantt_start": str(g_start),
        "gantt_end":   str(g_end),
        "today":       today,
        "months":      _month_context(),
    })


@login_required
def project_list_view(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.user not in project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a este projeto.")
        return redirect("projects:dashboard")
    return render(request, "projects/task_list.html", {
        "project": project,
        "tasks": project.tasks.prefetch_related("assignees","subtasks").order_by("status","position"),
        "today": date.today(),
    })


def _advance_equipe_queue(projeto):
    """Quando um projeto é concluído, tira ele do slot 'Atualmente' de cada
    equipe técnica atribuída a ele e promove a fila (1→0, 2→1, 3→2)."""
    slots_atuais = AtribuicaoEquipe.objects.filter(projeto=projeto, posicao=0).select_related("equipe")
    for slot in slots_atuais:
        equipe = slot.equipe
        slot.delete()
        fila = list(AtribuicaoEquipe.objects.filter(equipe=equipe, posicao__gt=0).order_by("posicao"))
        for atrib in fila:
            atrib.posicao -= 1
            atrib.save(update_fields=["posicao"])


@login_required
def project_settings(request, pk):
    project = get_object_or_404(Project, pk=pk)
    if request.user != project.owner and not request.user.is_superuser:
        messages.error(request, "Apenas o dono pode editar configurações.")
        return redirect("projects:kanban", pk=pk)
    if request.method == "POST":
        old_status = project.status
        project.name = request.POST.get("name", project.name)
        project.description = request.POST.get("description", project.description)
        project.color = request.POST.get("color", project.color)
        project.status = request.POST.get("status", project.status)
        project.start_date = request.POST.get("start_date") or None
        project.due_date = request.POST.get("due_date") or None
        _cidade = request.POST.get("cidade", "").strip()
        project.cidade = _cidade if _cidade in ("londrina", "itu") else ""
        project.save()
        if old_status != "completed" and project.status == "completed":
            _advance_equipe_queue(project)
        project.members.set(User.objects.filter(id__in=request.POST.getlist("members")))
        project.members.add(request.user)
        messages.success(request, "Projeto atualizado!")
        return redirect("projects:kanban", pk=pk)
    return render(request, "projects/settings.html", {
        "project": project, "all_users": User.objects.all().order_by("first_name"),
    })


@login_required
def dashboard_stats_json(request):
    from django.utils import timezone as _tz
    today = date.today()
    cidade_filter = request.GET.get("cidade", "").strip().lower()
    if cidade_filter not in ("londrina", "itu"):
        cidade_filter = ""
    active = Project.objects.filter(status__in=["active", "on_hold"])
    if cidade_filter:
        active = active.filter(cidade=cidade_filter)
    non_archived = Project.objects.exclude(status="archived")
    if cidade_filter:
        non_archived = non_archived.filter(cidade=cidade_filter)
    completed = Project.objects.filter(status="completed")
    if cidade_filter:
        completed = completed.filter(cidade=cidade_filter)
    all_tasks = Task.objects.filter(project__in=active).exclude(status="archived")
    recent = (
        all_tasks.exclude(status__in=["done", "archived"])
        .select_related("project")
        .prefetch_related("assignees")
        .order_by("-updated_at")[:8]
    )
    _STATUS_LABEL = {
        "backlog": "Backlog", "todo": "A fazer", "in_progress": "Em progresso",
        "review": "Review", "done": "Concluído",
    }
    tasks_data = []
    for t in recent:
        tasks_data.append({
            "title":   t.title,
            "project": t.project.name,
            "color":   t.project.color,
            "status":  _STATUS_LABEL.get(t.status, t.status),
            "overdue": bool(t.due_date and t.due_date < today),
            "url":     f"/tasks/{t.pk}/",
        })

    # ── Mesmos helpers do render inicial — Gantt e Equipes ficam ao vivo tbm ──
    from django.template.loader import render_to_string
    proj_list = list(active.distinct())
    gantt_rows, gantt_dash_start, gantt_dash_end = _build_gantt_rows(proj_list, today)
    equipes = _get_equipes(cidade_filter)
    equipes_html = render_to_string("projects/_equipes_cards.html", {"equipes": equipes}, request=request)

    resp = JsonResponse({
        "projects":           active.count(),
        "projects_completed": completed.count(),
        "open_tasks":         all_tasks.exclude(status__in=["done", "archived"]).count(),
        "done_tasks":         Task.objects.filter(project__in=non_archived, status="done").count(),
        "overdue":            all_tasks.filter(due_date__lt=today).exclude(status__in=["done", "archived"]).count(),
        "tasks":              tasks_data,
        "gantt_rows":         gantt_rows,
        "gantt_dash_start":   gantt_dash_start.isoformat(),
        "gantt_dash_end":     gantt_dash_end.isoformat(),
        "equipes_html":       equipes_html,
    })
    resp["Cache-Control"] = "no-store, no-cache, must-revalidate"
    return resp


@login_required
@require_POST
def project_delete(request, pk):
    project = get_object_or_404(Project, pk=pk)
    can_delete = (
        request.user == project.owner
        or request.user.role in ("owner", "admin")
        or request.user.is_superuser
    )
    if not can_delete:
        messages.error(request, "Sem permissão para excluir este projeto.")
        return redirect("projects:kanban", pk=pk)
    name = project.name
    project.delete()
    messages.success(request, f'Projeto "{name}" excluído com sucesso.')
    return redirect("projects:list")


@login_required
@require_POST
def move_task(request, task_pk):
    data = json.loads(request.body)
    task = get_object_or_404(Task, pk=task_pk)
    if request.user not in task.project.members.all() and not request.user.is_superuser:
        return JsonResponse({"ok": False, "error": "Sem acesso a este projeto."}, status=403)
    col = get_object_or_404(Column, pk=data.get("column_id"), project=task.project)
    task.column = col
    task.position = data.get("position", 0)
    if col.is_done_column:
        task.status = "done"
        if not task.completed_at:
            task.completed_at = timezone.now()
    task.save(update_fields=["column","position","status","completed_at"])
    return JsonResponse({"ok": True})


@login_required
def insights(request):
    from datetime import timedelta
    from django.db.models import Avg, Count, Q

    user     = request.user
    projects = Project.objects.filter(members=user).prefetch_related("tasks", "members")

    # Filtro por projeto
    # Quando um projeto específico é selecionado → todas as tarefas do projeto (visão completa)
    # Quando "todos" → apenas tarefas atribuídas ao usuário logado
    selected_pk = request.GET.get("project", "all")
    if selected_pk != "all":
        scope_tasks    = Task.objects.filter(project__pk=selected_pk, project__members=user).exclude(status="archived")
        scope_projects = projects.filter(pk=selected_pk)
    else:
        scope_tasks    = Task.objects.filter(assignees=user).exclude(status="archived")
        scope_projects = projects.filter(tasks__assignees=user).distinct()

    # ── Métricas gerais ───────────────────────────────────────────────────────
    total_tasks = scope_tasks.count()
    done_tasks  = scope_tasks.filter(status="done")
    done_count  = done_tasks.count()
    blocked     = scope_tasks.filter(is_blocked=True).count()
    overdue     = scope_tasks.filter(
        due_date__lt=date.today()
    ).exclude(status__in=["done","archived"]).count()

    completion_rate = round(done_count / total_tasks * 100) if total_tasks else 0

    # ── Tempo médio de execução (started_at → completed_at) ───────────────────
    timed_tasks = [
        t for t in done_tasks.filter(started_at__isnull=False)
        if t.completed_at and t.started_at
    ]
    avg_exec_days = round(
        sum((t.completed_at.date() - t.started_at.date()).days for t in timed_tasks)
        / len(timed_tasks), 1
    ) if timed_tasks else None

    # ── Desempenho de prazo ───────────────────────────────────────────────────
    delta_tasks = [t for t in done_tasks.filter(deadline_days__isnull=False, started_at__isnull=False) if t.days_delta is not None]
    on_time_pct = round(sum(1 for t in delta_tasks if t.days_delta <= 0) / len(delta_tasks) * 100) if delta_tasks else None
    avg_delta   = round(sum(t.days_delta for t in delta_tasks) / len(delta_tasks), 1) if delta_tasks else None

    # ── Tarefas por status ────────────────────────────────────────────────────
    status_data = [
        {"label": "Backlog",      "value": scope_tasks.filter(status="backlog").count(),     "color": "#8888aa"},
        {"label": "A Fazer",      "value": scope_tasks.filter(status="todo").count(),        "color": "#5b4cf5"},
        {"label": "Em Progresso", "value": scope_tasks.filter(status="in_progress").count(), "color": "#0ea5e9"},
        {"label": "Review",       "value": scope_tasks.filter(status="review").count(),      "color": "#fbbf24"},
        {"label": "Concluído",    "value": done_count,                                        "color": "#34d399"},
    ]

    # ── Entregas por semana (últimas 8) ───────────────────────────────────────
    weekly = []
    today_d = date.today()
    for i in range(7, -1, -1):
        ws = today_d - timedelta(days=today_d.weekday() + 7 * i)
        we = ws + timedelta(days=6)
        cnt = done_tasks.filter(completed_at__date__gte=ws, completed_at__date__lte=we).count()
        weekly.append({"week": ws.strftime("%d/%m"), "count": cnt})

    # ── Por prioridade ────────────────────────────────────────────────────────
    priority_data = [
        {"label": "Urgente", "total": scope_tasks.filter(priority="urgent").count(), "done": done_tasks.filter(priority="urgent").count(), "color": "#dc2626"},
        {"label": "Alta",    "total": scope_tasks.filter(priority="high").count(),   "done": done_tasks.filter(priority="high").count(),   "color": "#f59e0b"},
        {"label": "Média",   "total": scope_tasks.filter(priority="medium").count(), "done": done_tasks.filter(priority="medium").count(), "color": "#5b4cf5"},
        {"label": "Baixa",   "total": scope_tasks.filter(priority="low").count(),    "done": done_tasks.filter(priority="low").count(),    "color": "#34d399"},
    ]

    # ── Comparação de projetos ────────────────────────────────────────────────
    # No modo "all" mostra apenas tarefas do usuário; no modo projeto mostra todas as tarefas
    project_comparison = []
    for proj in scope_projects.order_by("-updated_at")[:10]:
        proj_tasks = proj.tasks.exclude(status="archived") if selected_pk != "all" else proj.tasks.filter(assignees=user).exclude(status="archived")
        ptasks   = proj_tasks.count()
        pdone    = proj_tasks.filter(status="done").count()
        pblocked = proj_tasks.filter(is_blocked=True).count()
        ptimed   = [t for t in proj_tasks.filter(status="done", started_at__isnull=False, deadline_days__isnull=False) if t.days_delta is not None]
        pavg     = round(sum(t.days_delta for t in ptimed) / len(ptimed), 1) if ptimed else None
        pontime  = round(sum(1 for t in ptimed if t.days_delta <= 0) / len(ptimed) * 100) if ptimed else None

        exec_times = [t for t in proj_tasks.filter(status="done", started_at__isnull=False) if t.completed_at and t.started_at]
        pavg_exec  = round(sum((t.completed_at.date() - t.started_at.date()).days for t in exec_times) / len(exec_times), 1) if exec_times else None

        project_comparison.append({
            "pk":        str(proj.pk),
            "name":      proj.name,
            "color":     proj.color,
            "total":     ptasks,
            "done":      pdone,
            "blocked":   pblocked,
            "progress":  round(pdone / ptasks * 100) if ptasks else 0,
            "avg_delta": pavg,
            "on_time_pct": pontime,
            "avg_exec_days": pavg_exec,
            "status":    proj.get_status_display(),
        })

    # ── Top responsáveis ──────────────────────────────────────────────────────
    top_members = []
    members_qs = User.objects.filter(projects__in=scope_projects).distinct()
    for m in members_qs[:10]:
        mdone    = done_tasks.filter(assignees=m).count()
        moverdue = scope_tasks.filter(assignees=m, due_date__lt=today_d).exclude(status__in=["done","archived"]).count()
        top_members.append({"user": m, "done": mdone, "overdue": moverdue})
    top_members.sort(key=lambda x: x["done"], reverse=True)

    return render(request, "projects/insights.html", {
        "projects":           projects,
        "selected_pk":        selected_pk,
        "total_tasks":        total_tasks,
        "done_count":         done_count,
        "blocked":            blocked,
        "overdue":            overdue,
        "completion_rate":    completion_rate,
        "avg_exec_days":      avg_exec_days,
        "on_time_pct":        on_time_pct,
        "avg_delta":          avg_delta,
        "delta_tasks_count":  len(delta_tasks),
        "status_data":        status_data,
        "weekly":             weekly,
        "priority_data":      priority_data,
        "project_comparison": project_comparison,
        "top_members":        top_members,
    })


@login_required
def project_scope(request, project_id):

    project = get_object_or_404(Project, id=project_id)
    if request.user not in project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a este projeto.")
        return redirect("projects:dashboard")

    documents = ProjectDocument.objects.filter(
        project=project
    ).order_by("-created_at")

    form = ProjectDocumentForm()

    if request.method == "POST":

        form = ProjectDocumentForm(
            request.POST,
            request.FILES
        )

        if form.is_valid():
            doc = form.save(commit=False)
            doc.project = project
            doc.uploaded_by = request.user
            doc.save()

            return redirect(
                "projects:project_scope",
                project_id=project.id
            )   

    context = {
        "project": project,
        "documents": documents,
        "form": form
    }

    return render(
        request,
        "projects/project_scope.html",
        context
    )


@login_required
def project_document_download(request, doc_id):
    """Serve o documento só para membros do projeto — o /media/ cru não tem
    nenhuma checagem de permissão, então não pode virar um link direto."""
    from django.http import FileResponse, Http404

    doc = ProjectDocument.objects.select_related("project").filter(pk=doc_id).first()
    if not doc or not doc.file:
        raise Http404
    if request.user not in doc.project.members.all() and not request.user.is_superuser:
        raise Http404

    return FileResponse(doc.file.open("rb"), filename=doc.file.name.split("/")[-1], as_attachment=False)


@login_required
def project_report(request, pk):
    """Relatório final do projeto com resumo de dias produtivos/improdutivos e retrospectiva."""
    project = get_object_or_404(
        Project.objects.prefetch_related(
            "tasks__assignees",
            "tasks__daily_reports",
            "tasks__issues",
            "members",
        ),
        pk=pk,
    )
    if request.user not in project.members.all() and not request.user.is_superuser:
        messages.error(request, "Sem acesso a este projeto.")
        return redirect("projects:dashboard")

    tasks = project.tasks.exclude(status="archived").prefetch_related(
        "assignees", "daily_reports", "issues"
    )

    # Estatísticas gerais
    total      = tasks.count()
    done       = tasks.filter(status="done").count()
    progress   = round(done / total * 100) if total else 0
    blocked    = tasks.filter(is_blocked=True).count()
    with_days  = [t for t in tasks if t.duration_days]

    total_planned_days     = sum(t.duration_days for t in with_days)
    total_accomplished     = sum(t.daily_summary["accomplished"]     for t in with_days)
    total_not_accomplished = sum(t.daily_summary["not_accomplished"] for t in with_days)
    total_pending          = sum(t.daily_summary["pending"]          for t in with_days)

    return render(request, "projects/report.html", {
        "project":               project,
        "tasks":                 tasks,
        "total":                 total,
        "done":                  done,
        "progress":              progress,
        "blocked":               blocked,
        "with_days":             with_days,
        "total_planned_days":    total_planned_days,
        "total_accomplished":    total_accomplished,
        "total_not_accomplished": total_not_accomplished,
        "total_pending":         total_pending,
        "today":                 date.today(),
    })


@login_required
@require_POST
def save_retrospective(request, pk):
    """Salva os campos de retrospectiva do projeto (AJAX)."""
    project = get_object_or_404(Project, pk=pk)
    if not project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Apenas o gestor pode editar a retrospectiva."}, status=403)
    data = json.loads(request.body)
    if "went_well" in data:
        project.went_well = data["went_well"]
    if "went_wrong" in data:
        project.went_wrong = data["went_wrong"]
    project.save(update_fields=["went_well", "went_wrong"])
    return JsonResponse({"ok": True})


# ─────────────────────────── FLUXOGRAMA DE DEPENDÊNCIAS ───────────────────────

@login_required
def project_flow(request, pk):
    """Página de fluxograma de dependências de tarefas do projeto."""
    project = get_object_or_404(Project, pk=pk, members=request.user)
    tasks = list(project.tasks.exclude(status="archived").prefetch_related(
        "dependencies", "required_by", "assignees"
    ))

    # Serializa tarefas e dependências para o JS
    tasks_data = []
    for t in tasks:
        tasks_data.append({
            "id":       str(t.pk),
            "title":    t.title,
            "status":   t.status,
            "priority": t.priority,
            "color":    _status_color(t),
            "blocked":  t.is_blocked,
            "assignees": [{"name": str(a), "color": a.avatar_color, "initials": a.initials}
                          for a in t.assignees.all()],
            "url":      f"/tasks/{t.pk}/",
        })

    deps_data = []
    for dep in TaskDependency.objects.filter(task__project=project).select_related("task", "requires"):
        # Verifica se ambas as tarefas ainda existem no projeto (não arquivadas)
        t_ids = {str(t.pk) for t in tasks}
        if str(dep.task_id) in t_ids and str(dep.requires_id) in t_ids:
            deps_data.append({
                "id":      str(dep.pk),
                "from":    str(dep.requires_id),   # seta sai de "requires"
                "to":      str(dep.task_id),        # e entra em "task"
            })

    can_edit = project.can_create_tasks(request.user)
    return render(request, "projects/flow.html", {
        "project":    project,
        "tasks_json": json.dumps(tasks_data, ensure_ascii=False),
        "deps_json":  json.dumps(deps_data,  ensure_ascii=False),
        "can_edit":   can_edit,
        "all_tasks":  tasks,
    })


def _status_color(t):
    if t.status == "done":     return "#34d399"
    if t.is_blocked:           return "#fbbf24"
    if t.status == "review":   return "#a855f7"
    if t.status == "in_progress": return "#0ea5e9"
    if t.status == "todo":     return "#64748b"
    return "#94a3b8"   # backlog


@login_required
@require_POST
def flow_add_dependency(request, pk):
    """AJAX: adiciona dependência entre duas tarefas."""
    project = get_object_or_404(Project, pk=pk, members=request.user)
    if not project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão"}, status=403)
    data = json.loads(request.body)
    from_id = data.get("from")   # requires (precisa estar pronta antes)
    to_id   = data.get("to")     # task (depende de from)
    if from_id == to_id:
        return JsonResponse({"ok": False, "error": "Uma tarefa não pode depender de si mesma."})
    requires = get_object_or_404(Task, pk=from_id, project=project)
    task     = get_object_or_404(Task, pk=to_id,   project=project)
    # Checa ciclo simples: "from" não pode já depender de "to"
    if _would_create_cycle(task, requires):
        return JsonResponse({"ok": False, "error": "Isso criaria um ciclo de dependências."})
    dep, created = TaskDependency.objects.get_or_create(task=task, requires=requires)
    return JsonResponse({"ok": True, "id": str(dep.pk), "created": created})


@login_required
@require_POST
def flow_remove_dependency(request, pk):
    """AJAX: remove dependência."""
    project = get_object_or_404(Project, pk=pk, members=request.user)
    if not project.can_create_tasks(request.user):
        return JsonResponse({"ok": False, "error": "Sem permissão"}, status=403)
    data = json.loads(request.body)
    dep_id = data.get("dep_id")
    TaskDependency.objects.filter(pk=dep_id, task__project=project).delete()
    return JsonResponse({"ok": True})


def _would_create_cycle(start, target):
    """Verifica se adicionar start→target criaria ciclo (BFS)."""
    visited = set()
    queue = [target]
    while queue:
        node = queue.pop()
        if str(node.pk) == str(start.pk):
            return True
        if node.pk in visited:
            continue
        visited.add(node.pk)
        for dep in node.required_by.select_related("task"):
            queue.append(dep.task)
    return False