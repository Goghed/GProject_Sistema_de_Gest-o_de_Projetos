from django.urls import path
from . import views

app_name = "tasks"
urlpatterns = [
    path("my/",                                views.my_tasks_view,     name="my_tasks"),
    path("project/<uuid:project_pk>/create/",  views.task_create,       name="create"),
    path("<uuid:pk>/",                          views.task_detail,       name="detail"),
    path("<uuid:pk>/update/",                   views.task_update,       name="update"),
    path("<uuid:pk>/delete/",                   views.task_delete,       name="delete"),
    path("<uuid:pk>/advance/",                  views.advance_status,    name="advance"),
    path("<uuid:pk>/report-issue/",             views.report_issue,      name="report_issue"),
    path("<uuid:pk>/pause/",                    views.pause_task,        name="pause"),
    path("issue/<uuid:issue_pk>/edit/",         views.edit_issue,        name="edit_issue"),
    path("issue/<uuid:issue_pk>/resolve/",      views.resolve_issue,     name="resolve_issue"),
    path("issue/<uuid:issue_pk>/comment/",             views.issue_comment_add,  name="issue_comment"),
    path("issue/comment/<uuid:comment_pk>/edit/",      views.issue_comment_edit, name="issue_comment_edit"),
    path("<uuid:pk>/upload/",                   views.upload_attachment,  name="upload"),
    path("subtask/<uuid:pk>/toggle/",           views.subtask_toggle,    name="subtask_toggle"),
    path("<uuid:task_pk>/comment/",             views.comment_add,       name="comment_add"),
    path("<uuid:task_pk>/daily-report/",        views.daily_report_view, name="daily_report"),
    path("<uuid:pk>/dependencies/add/",        views.dependency_add,    name="dependency_add"),
    path("<uuid:pk>/dependencies/<uuid:dep_id>/remove/", views.dependency_remove, name="dependency_remove"),
]
