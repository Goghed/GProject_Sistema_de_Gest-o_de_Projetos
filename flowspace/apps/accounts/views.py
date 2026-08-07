# ── views.py ──────────────────────────────────────────────────────────────────
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.shortcuts import render, redirect
from django.contrib import messages
from django.utils.http import url_has_allowed_host_and_scheme
from apps.common.uploads import validate_image_upload
from .models import User

_LOGIN_MAX_ATTEMPTS = 10
_LOGIN_WINDOW_SECONDS = 300


def _safe_next(request, default="/dashboard/"):
    """Only follow `next` when it points to this same site — blocks open-redirect phishing."""
    next_url = request.GET.get("next") or request.POST.get("next")
    if next_url and url_has_allowed_host_and_scheme(
        next_url, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return next_url
    return default


def login_view(request):
    if request.user.is_authenticated:
        return redirect("/dashboard/")
    error = None
    if request.method == "POST":
        ip = request.META.get("REMOTE_ADDR", "unknown")
        throttle_key = f"login-attempts:{ip}"
        attempts = cache.get(throttle_key, 0)
        if attempts >= _LOGIN_MAX_ATTEMPTS:
            error = "Muitas tentativas de login. Tente novamente em alguns minutos."
            return render(request, "accounts/login.html", {"error": error})

        user = authenticate(request,
            username=request.POST.get("username"),
            password=request.POST.get("password"))
        if user:
            cache.delete(throttle_key)
            login(request, user)
            if user.must_change_password:
                return redirect("accounts:force_password_change")
            return redirect(_safe_next(request))
        cache.set(throttle_key, attempts + 1, _LOGIN_WINDOW_SECONDS)
        error = "Usuário ou senha inválidos."
    return render(request, "accounts/login.html", {"error": error})


def logout_view(request):
    logout(request)
    return redirect("/accounts/login/")


@login_required
def profile_view(request):
    if request.method == "POST":
        u = request.user
        u.first_name   = request.POST.get("first_name",   u.first_name)
        u.last_name    = request.POST.get("last_name",    u.last_name)
        u.job_title    = request.POST.get("job_title",    u.job_title)
        u.bio          = request.POST.get("bio",          u.bio)
        u.avatar_color = request.POST.get("avatar_color", u.avatar_color)

        photo = request.FILES.get("photo")
        if photo:
            try:
                validate_image_upload(photo)
            except ValidationError as e:
                messages.error(request, e.message)
                colors = ["#5b4cf5","#0ea5e9","#34d399","#fbbf24","#ff6b6b","#a855f7","#ec4899","#14b8a6"]
                return render(request, "accounts/profile.html", {"colors": colors})
            # Remove foto antiga se existir
            if u.photo:
                try:
                    u.photo.delete(save=False)
                except Exception:
                    pass
            u.photo = photo
        elif request.POST.get("remove_photo"):
            if u.photo:
                try:
                    u.photo.delete(save=False)
                except Exception:
                    pass
            u.photo = None

        u.save()
        messages.success(request, "Perfil atualizado!")
    colors = ["#5b4cf5","#0ea5e9","#34d399","#fbbf24","#ff6b6b","#a855f7","#ec4899","#14b8a6"]
    return render(request, "accounts/profile.html", {"colors": colors})


@login_required
def force_password_change_view(request):
    """Exibida quando must_change_password=True (conta nova ou senha resetada por um admin).
    Bloqueada pelo ForcePasswordChangeMiddleware até o usuário definir uma senha própria."""
    error = None
    if request.method == "POST":
        new_password = request.POST.get("new_password", "")
        confirm      = request.POST.get("confirm_password", "")
        if new_password != confirm:
            error = "As senhas não coincidem."
        else:
            try:
                validate_password(new_password, user=request.user)
            except ValidationError as e:
                error = " ".join(e.messages)
            else:
                request.user.set_password(new_password)
                request.user.must_change_password = False
                request.user.save(update_fields=["password", "must_change_password"])
                update_session_auth_hash(request, request.user)  # mantém a sessão logada
                messages.success(request, "Senha definida com sucesso!")
                return redirect("/dashboard/")
    return render(request, "accounts/force_password_change.html", {"error": error})


@login_required
def team_view(request):
    if not request.user.can_manage:
        messages.error(request, "Sem permissão.")
        return redirect("/dashboard/")
    if request.method == "POST":
        action = request.POST.get("action")
        if action == "invite":
            username   = request.POST.get("username")
            email      = request.POST.get("email")
            role       = request.POST.get("role", "member")
            first_name = request.POST.get("first_name", "")
            last_name  = request.POST.get("last_name", "")
            job_title  = request.POST.get("job_title", "")
            if not User.objects.filter(username=username).exists():
                pwd  = User.objects.make_random_password()
                user = User.objects.create_user(
                    username=username, email=email, role=role, password=pwd,
                    first_name=first_name, last_name=last_name,
                )
                user.job_title = job_title
                user.must_change_password = True
                user.save(update_fields=["job_title", "must_change_password"])
                messages.success(request, f"Usuário {username} criado! Senha temporária: {pwd} (será exigida a troca no primeiro acesso)")
            else:
                messages.error(request, "Username já existe.")
        elif action == "change_role":
            uid    = request.POST.get("user_id")
            role   = request.POST.get("role")
            target = User.objects.filter(id=uid).first()
            valid_roles = dict(User.ROLE_CHOICES)
            if not target:
                messages.error(request, "Usuário não encontrado.")
            elif role not in valid_roles:
                messages.error(request, "Função inválida.")
            elif str(target.id) == str(request.user.id):
                messages.error(request, "Você não pode alterar sua própria função.")
            elif role == "owner" and request.user.role != "owner":
                messages.error(request, "Apenas o proprietário pode conceder a função de Proprietário.")
            elif target.role == "owner" and request.user.role != "owner":
                messages.error(request, "Apenas o proprietário pode alterar a função de outro proprietário.")
            else:
                target.role = role
                target.save(update_fields=["role"])
                messages.success(request, "Função atualizada.")
        elif action == "delete_member":
            uid    = request.POST.get("user_id")
            target = User.objects.filter(id=uid).first()
            if request.user.role not in ("owner", "admin"):
                messages.error(request, "Apenas o proprietário ou administradores podem excluir membros.")
            elif not target:
                messages.error(request, "Usuário não encontrado.")
            elif str(target.id) == str(request.user.id):
                messages.error(request, "Você não pode excluir sua própria conta.")
            elif target.role == "owner" and request.user.role != "owner":
                messages.error(request, "Apenas o proprietário pode excluir outro proprietário.")
            elif target.role == "owner" and User.objects.filter(role="owner").count() <= 1:
                messages.error(request, "Não é possível excluir o único proprietário do sistema.")
            else:
                name = target.get_full_name() or target.username
                target.delete()
                messages.success(request, f"Usuário {name} excluído. Projetos e tarefas dele foram preservados (sem responsável).")
        elif action == "reset_password":
            uid    = request.POST.get("user_id")
            target = User.objects.filter(id=uid).first()
            if request.user.role not in ("owner", "admin"):
                messages.error(request, "Apenas o proprietário ou administradores podem resetar senhas.")
            elif not target:
                messages.error(request, "Usuário não encontrado.")
            elif str(target.id) == str(request.user.id):
                messages.error(request, "Para trocar sua própria senha, use a página de Perfil.")
            elif target.role == "owner" and request.user.role != "owner":
                messages.error(request, "Apenas o proprietário pode resetar a senha de outro proprietário.")
            else:
                new_pwd = User.objects.make_random_password()
                target.set_password(new_pwd)
                target.must_change_password = True
                target.save(update_fields=["password", "must_change_password"])
                name = target.get_full_name() or target.username
                messages.success(request, f"Senha de {name} resetada! Nova senha temporária: {new_pwd} (será exigida a troca no próximo acesso).")
        elif action == "edit_member":
            uid        = request.POST.get("user_id")
            first_name = request.POST.get("first_name", "").strip()
            last_name  = request.POST.get("last_name", "").strip()
            email      = request.POST.get("email", "").strip()
            job_title  = request.POST.get("job_title", "").strip()
            is_active  = request.POST.get("is_active") == "1"
            try:
                member = User.objects.get(id=uid)
                member.first_name = first_name
                member.last_name  = last_name
                member.email      = email
                member.job_title  = job_title
                member.is_active  = is_active
                member.save(update_fields=["first_name", "last_name", "email", "job_title", "is_active"])
                messages.success(request, f"Dados de {member.get_full_name() or member.username} atualizados.")
            except User.DoesNotExist:
                messages.error(request, "Usuário não encontrado.")
    users = User.objects.all().order_by("role", "first_name")
    return render(request, "accounts/team.html", {"team_users": users})
