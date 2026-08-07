from django.contrib import admin
from .models import Task, SubTask, Comment

class SubTaskInline(admin.TabularInline):
    model = SubTask
    extra = 0

@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display  = ["title","project","status","priority","due_date"]
    list_filter   = ["status","priority","project"]
    inlines       = [SubTaskInline]
