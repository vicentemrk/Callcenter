from django.contrib import admin

from marvel.models import ElementoCatalogo


@admin.register(ElementoCatalogo)
class ElementoCatalogoAdmin(admin.ModelAdmin):
    list_display = (
        'id',
        'nombre',
        'tipo',
        'activo',
        'fase',
        'sincronizado_en',
    )
    list_filter = ('tipo', 'activo', 'fase')
    search_fields = ('nombre', 'mcu_id')
    ordering = ('tipo', 'nombre')
