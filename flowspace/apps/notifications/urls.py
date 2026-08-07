from django.urls import path
from . import views

app_name = "notifications"
urlpatterns = [
    path("",                       views.notifications_list, name="list"),
    path("<uuid:pk>/read/",        views.mark_read,          name="mark_read"),
    path("read-all/",              views.mark_all_read,      name="mark_all_read"),
    path("clear-all/",             views.clear_all,          name="clear_all"),
]
