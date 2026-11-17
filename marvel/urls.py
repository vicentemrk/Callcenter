"""Rutas de la app marvel.

app_name marcado para evitar colisiones de nombres con otras apps
('marvel:catalogo', 'marvel:detalle').

- /marvel/           -> listado con busqueda, filtros y paginacion.
- /marvel/<int:pk>/  -> ficha de detalle del elemento.

Entry point solo consulta la base local (estrategia hibrida aprobada):
ningen HTTP se hace a MCU API durante la navegacion.
"""

from django.urls import path

from marvel import views

app_name = 'marvel'

urlpatterns = [
    path('', views.Catalogo, name='catalogo'),
    path('<int:pk>/', views.Detalle, name='detalle'),
]
