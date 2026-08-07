from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as Base
from .models import User

@admin.register(User)
class UserAdmin(Base):
    list_display  = ["username","get_full_name","email","role","is_active"]
    list_filter   = ["role","is_active"]
    fieldsets     = Base.fieldsets + (("FlowSpace", {"fields": ("role","avatar_color","bio","job_title")}),)
