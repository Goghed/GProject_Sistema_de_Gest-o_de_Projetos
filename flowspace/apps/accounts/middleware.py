from django.shortcuts import redirect
from django.urls import reverse

# Caminhos acessíveis mesmo com uma troca de senha pendente — sem isso o usuário
# ficaria preso sem conseguir nem sair da conta. /api/ fica de fora porque um
# redirect HTML quebraria as chamadas fetch/AJAX do próprio app (a troca já é
# forçada no login antes de qualquer tela carregar, então cobre o essencial).
_ALLOWED_PREFIXES = ("/static/", "/media/", "/api/")


class ForcePasswordChangeMiddleware:
    """Redireciona qualquer request de um usuário com must_change_password=True
    para a tela de troca de senha, até ele definir uma senha própria."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and getattr(user, "must_change_password", False)
        ):
            change_url = reverse("accounts:force_password_change")
            logout_url = reverse("accounts:logout")
            if request.path not in (change_url, logout_url) and not request.path.startswith(_ALLOWED_PREFIXES):
                return redirect(change_url)
        return self.get_response(request)
