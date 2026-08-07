from django.urls import path
from . import views

app_name = "accounts"
urlpatterns = [
    path("login/",   views.login_view,   name="login"),
    path("logout/",  views.logout_view,  name="logout"),
    path("profile/", views.profile_view, name="profile"),
    path("team/",    views.team_view,    name="team"),
    path("trocar-senha/", views.force_password_change_view, name="force_password_change"),
]
