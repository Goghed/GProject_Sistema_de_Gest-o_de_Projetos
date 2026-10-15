from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

app_name = "api"
urlpatterns = [
    # Auth
    path("auth/login/",                    views.login_view,                name="login"),
    path("auth/refresh/",                  TokenRefreshView.as_view(),      name="token_refresh"),
    path("auth/me/",                       views.me_view,                   name="me"),
    path("auth/profile/",                  views.update_profile,            name="profile"),
    path("auth/push-token/",               views.register_push_token,       name="push_token"),
    path("auth/photo/",                    views.upload_photo,              name="upload_photo"),
    path("auth/photo/remove/",             views.remove_photo,              name="remove_photo"),

    # Dashboard
    path("dashboard/",                     views.dashboard_view,            name="dashboard"),
    path("performance/",                   views.performance_view,          name="performance"),

    # Projects
    path("projects/",                      views.project_list,              name="project_list"),
    path("projects/create/",               views.project_create,            name="project_create"),
    path("projects/<uuid:pk>/",            views.project_detail,            name="project_detail"),
    path("projects/<uuid:pk>/update/",     views.project_update,            name="project_update"),
    path("projects/<uuid:pk>/documents/",  views.project_documents,         name="project_documents"),
    path("documents/<int:doc_id>/download/", views.api_download_document,   name="download_document"),

    # Kanban
    path("kanban/move/",                           views.kanban_move_task,  name="kanban_move"),
    path("kanban/<uuid:project_pk>/reorder/",      views.kanban_reorder,    name="kanban_reorder"),

    # Tasks
    path("tasks/",                         views.task_list,                 name="task_list"),
    path("tasks/create/",                  views.task_create,               name="task_create"),
    path("tasks/<uuid:pk>/",               views.task_detail_view,          name="task_detail"),
    path("tasks/<uuid:pk>/update/",        views.task_update,               name="task_update"),
    path("tasks/<uuid:pk>/advance/",       views.advance_status,            name="task_advance"),
    path("subtasks/<uuid:pk>/toggle/",     views.subtask_toggle,            name="subtask_toggle"),
    path("tasks/<uuid:task_pk>/comment/",  views.comment_add,               name="comment_add"),

    path("tasks/<uuid:pk>/report-issue/",              views.api_report_issue,        name="report_issue"),
    path("tasks/<uuid:pk>/pause/",                     views.api_pause_task,           name="task_pause"),
    path("tasks/<uuid:pk>/resume/",                    views.api_resume_task,          name="task_resume"),
    path("tasks/issue/<uuid:issue_pk>/edit/",          views.api_edit_issue,           name="edit_issue"),
    path("tasks/issue/<uuid:issue_pk>/resolve/",       views.api_resolve_issue,        name="resolve_issue"),
    path("tasks/issue/comment/<uuid:comment_pk>/edit/", views.api_issue_comment_edit,  name="issue_comment_edit"),
    path("tasks/<uuid:pk>/upload/",               views.api_upload_attachment, name="upload"),
    path("tasks/<uuid:pk>/attachments/<uuid:attachment_id>/delete/", views.api_delete_attachment, name="delete_attachment"),
    path("attachments/<uuid:attachment_id>/download/", views.api_download_attachment, name="download_attachment"),

    # Daily Reports
    path("tasks/<uuid:task_pk>/daily-reports/",                      views.daily_report_list,   name="daily_report_list"),
    path("tasks/<uuid:task_pk>/daily-reports/create/",               views.daily_report_create, name="daily_report_create"),
    path("tasks/<uuid:task_pk>/daily-reports/<uuid:report_pk>/",     views.daily_report_update, name="daily_report_update"),

    # Notifications
    path("notifications/",                 views.notification_list,         name="notif_list"),
    path("notifications/read-all/",        views.notifications_mark_all_read, name="notif_read_all"),
    path("notifications/<uuid:pk>/read/",  views.notification_mark_read,   name="notif_read"),

    # Team
    path("team/",                          views.team_list,                 name="team"),

    # Presence
    path("presence/heartbeat/",            views.presence_heartbeat,        name="presence_heartbeat"),
    path("presence/online/",               views.presence_online,           name="presence_online"),

    # Dependencies
    path("tasks/<uuid:pk>/dependencies/add/",                        views.task_dependency_add,    name="dep_add"),
    path("tasks/<uuid:pk>/dependencies/<uuid:dep_id>/remove/",       views.task_dependency_remove, name="dep_remove"),
]
