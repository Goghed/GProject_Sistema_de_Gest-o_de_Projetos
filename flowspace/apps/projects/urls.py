from django.urls import path
from . import views

app_name = "projects"
urlpatterns = [
    path("",                          views.dashboard,       name="dashboard"),
    path("projects/",                 views.project_list,    name="list"),
    path("projects/new/",             views.project_create,  name="create"),
    path("projects/<uuid:pk>/",       views.project_kanban,  name="kanban"),
    path("projects/<uuid:pk>/timeline/", views.project_timeline, name="timeline"),
    path("projects/<uuid:pk>/list/",  views.project_list_view, name="task_list"),
    path("projects/<uuid:pk>/settings/",      views.project_settings,   name="settings"),
    path("projects/<uuid:pk>/delete/",        views.project_delete,     name="delete"),
    path("projects/<uuid:pk>/pause/",         views.project_pause,      name="project_pause"),
    path("projects/<uuid:pk>/resume/",        views.project_resume,     name="project_resume"),
    path("projects/<uuid:pk>/color/",         views.project_update_color, name="project_update_color"),
    path("projects/<uuid:pk>/report/",        views.project_report,     name="report"),
    path("projects/<uuid:pk>/retrospective/", views.save_retrospective, name="retrospective"),
    path("projects/<uuid:pk>/flow/",          views.project_flow,       name="flow"),
    path("projects/<uuid:pk>/flow/add/",      views.flow_add_dependency, name="flow_add"),
    path("projects/<uuid:pk>/flow/remove/",   views.flow_remove_dependency, name="flow_remove"),
    path("projetos/<uuid:project_id>/escopo/", views.project_scope,     name="project_scope"),
    path("documentos/<int:doc_id>/download/",  views.project_document_download, name="document_download"),
    path("tasks/<uuid:task_pk>/move/",        views.move_task,          name="move_task"),
    path("insights/",                         views.insights,           name="insights"),
    path("equipes/",                          views.equipes_view,        name="equipes"),
    path("equipes/reorder/", views.equipe_reorder,      name="equipe_reorder"),
    path("equipes/<uuid:equipe_id>/slot/<int:posicao>/save/", views.equipe_save_slot, name="equipe_save_slot"),
    path("stats.json",                        views.dashboard_stats_json, name="stats_json"),
]
