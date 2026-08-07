def sidebar(request):
    """Injeta projetos na sidebar em todas as páginas."""
    if not request.user.is_authenticated:
        return {"sidebar_projects": []}
    projects = request.user.projects.filter(
        status__in=["active", "on_hold"]
    ).order_by("-updated_at")[:8]
    return {"sidebar_projects": projects}
