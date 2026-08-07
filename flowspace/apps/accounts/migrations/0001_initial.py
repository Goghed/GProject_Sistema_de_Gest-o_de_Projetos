import django.contrib.auth.models
import django.contrib.auth.validators
import django.utils.timezone
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("auth","0012_alter_user_first_name_max_length")]
    operations = [
        migrations.CreateModel(
            name="User",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True)),
                ("password", models.CharField(max_length=128)),
                ("last_login", models.DateTimeField(blank=True, null=True)),
                ("is_superuser", models.BooleanField(default=False)),
                ("username", models.CharField(max_length=150, unique=True,
                    validators=[django.contrib.auth.validators.UnicodeUsernameValidator()])),
                ("first_name", models.CharField(blank=True, max_length=150)),
                ("last_name", models.CharField(blank=True, max_length=150)),
                ("email", models.EmailField(blank=True, max_length=254)),
                ("is_staff", models.BooleanField(default=False)),
                ("is_active", models.BooleanField(default=True)),
                ("date_joined", models.DateTimeField(default=django.utils.timezone.now)),
                ("role", models.CharField(choices=[("owner","Proprietário"),("admin","Administrador"),("manager","Gerente"),("member","Membro"),("guest","Convidado")], default="member", max_length=20)),
                ("avatar_color", models.CharField(default="#5b4cf5", max_length=7)),
                ("bio", models.TextField(blank=True)),
                ("job_title", models.CharField(blank=True, max_length=100)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("groups", models.ManyToManyField(blank=True, related_name="accounts_user_groups", to="auth.group")),
                ("user_permissions", models.ManyToManyField(blank=True, related_name="accounts_user_permissions", to="auth.permission")),
            ],
            options={"db_table": "accounts_user"},
            managers=[("objects", django.contrib.auth.models.UserManager())],
        ),
    ]
