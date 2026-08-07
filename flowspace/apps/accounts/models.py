import uuid
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ("owner",   "Proprietário"),
        ("admin",   "Administrador"),
        ("manager", "Gerente"),
        ("member",  "Membro"),
        ("guest",   "Convidado"),
    ]
    id             = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    role           = models.CharField(max_length=20, choices=ROLE_CHOICES, default="member")
    avatar_color   = models.CharField(max_length=7, default="#5b4cf5")
    bio            = models.TextField(blank=True)
    job_title      = models.CharField(max_length=100, blank=True)
    created_at     = models.DateTimeField(auto_now_add=True)
    photo           = models.ImageField(upload_to="avatars/", null=True, blank=True)
    # Token do Expo para notificações push
    expo_push_token = models.CharField(max_length=200, blank=True, default="")
    # Presença online (atualizado via heartbeat)
    last_seen       = models.DateTimeField(null=True, blank=True)
    # True após criação/reset de senha por um admin — força a troca no próximo acesso
    must_change_password = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_user"

    def __str__(self):
        return self.get_full_name() or self.username

    @property
    def initials(self):
        parts = self.get_full_name().split()
        if len(parts) >= 2:
            return (parts[0][0] + parts[-1][0]).upper()
        return self.username[:2].upper()

    @property
    def can_manage(self):
        return self.role in ("owner", "admin", "manager")
