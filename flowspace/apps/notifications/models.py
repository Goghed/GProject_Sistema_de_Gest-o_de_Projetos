import uuid
from django.db import models
from django.conf import settings

class Notification(models.Model):
    id        = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user      = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    message   = models.CharField(max_length=300)
    link      = models.CharField(max_length=300, blank=True)
    read      = models.BooleanField(default=False)
    created_at= models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ["-created_at"]
