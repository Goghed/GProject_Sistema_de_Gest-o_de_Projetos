from django.contrib import admin
from .models import Project, Column, EquipeTecnica, AtribuicaoEquipe


class ColumnInline(admin.TabularInline):
    model = Column
    extra = 0


@admin.register(Project)
class ProjectAdmin(admin.ModelAdmin):
    list_display = ["name", "status", "owner", "created_at"]
    list_filter  = ["status"]
    inlines      = [ColumnInline]
    filter_horizontal = ["members"]


class AtribuicaoEquipeInline(admin.TabularInline):
    model   = AtribuicaoEquipe
    extra   = 0
    fields  = ["posicao", "projeto", "tipo_instalacao", "varejo_projeto", "dias_execucao", "data_inicio", "data_termino"]
    ordering = ["posicao"]


@admin.register(EquipeTecnica)
class EquipeTecnicaAdmin(admin.ModelAdmin):
    list_display  = ["tecnico", "auxiliar", "veiculo", "is_active", "ordem"]
    list_filter   = ["is_active"]
    list_editable = ["ordem", "is_active"]
    inlines       = [AtribuicaoEquipeInline]


@admin.register(AtribuicaoEquipe)
class AtribuicaoEquipeAdmin(admin.ModelAdmin):
    list_display = ["equipe", "posicao", "projeto", "tipo_instalacao", "data_inicio", "data_termino"]
    list_filter  = ["posicao", "equipe"]
    autocomplete_fields = []
