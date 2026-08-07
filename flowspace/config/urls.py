from django.contrib import admin
from django.urls import path, re_path, include
from django.conf import settings
from django.conf.urls.static import static
from django.shortcuts import redirect
from django.views.static import serve as static_serve

urlpatterns = [
    path("admin/",          admin.site.urls),
    path("",                lambda r: redirect("/dashboard/"), name="home"),
    path("accounts/",       include("apps.accounts.urls",       namespace="accounts")),
    path("dashboard/",      include("apps.projects.urls",       namespace="projects")),
    path("tasks/",          include("apps.tasks.urls",          namespace="tasks")),
    path("notifications/",  include("apps.notifications.urls",  namespace="notifications")),
    path("api/",            include("apps.api.urls",            namespace="api")),
]

# ── Mídia ─────────────────────────────────────────────────────────────────────
# Documentos de projeto e anexos de tarefa NUNCA são servidos aqui — passam
# pelas views protegidas (project_document_download / api_download_attachment)
# que checam se o usuário é membro do projeto. As pastas abaixo são conteúdo já
# visível a qualquer usuário logado dentro do próprio app (avatares, fotos de
# equipe, capa de projeto), então servi-las diretamente não expõe nada novo —
# e ao contrário do static() padrão do Django, isso funciona mesmo com DEBUG=False.
_PUBLIC_MEDIA_PREFIXES = ("avatars", "equipes", "projects/covers")
for _prefix in _PUBLIC_MEDIA_PREFIXES:
    urlpatterns.append(
        re_path(
            rf"^media/{_prefix}/(?P<path>.*)$",
            static_serve,
            {"document_root": str(settings.MEDIA_ROOT / _prefix)},
        )
    )

# Em desenvolvimento (DEBUG=True) o restante do /media/ continua acessível como
# antes, para conveniência local — só não conta com nenhuma checagem de permissão.
urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
