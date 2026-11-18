"""Rutas de la app marvel.

app_name marcado para evitar colisiones de nombres con otras apps
('marvel:catalogo', 'marvel:detalle').

- /marvel/           -> landing Universo Marvel (Bloque 4C): reemplaza la
  redireccion temporal del 4A. El nombre 'raiz' se conserva para que
  reverse() y cualquier referencia previa sigan resolviendo.
- /marvel/catalogo/  -> listado con busqueda, filtros y paginacion.
- /marvel/<int:pk>/  -> ficha de detalle del elemento (GET publico,
  POST publica reseñas desde el Bloque 5C).
- /marvel/<int:pk>/resenas/<int:resena_id>/ocultar/ y .../restaurar/
  -> moderacion SOLO admin (POST) desde el Bloque 5D. La accion vive
  en la RUTA (no en un parametro libre del cliente).

Entry points solo consultan la base local (estrategia hibrida aprobada):
ningun HTTP se hace a MCU API durante la navegacion.
"""

from django.urls import path

from marvel import views

app_name = 'marvel'

urlpatterns = [
    path('', views.LandingUniverso, name='raiz'),
    path('catalogo/', views.Catalogo, name='catalogo'),
    path('<int:pk>/', views.Detalle, name='detalle'),
    path(
        '<int:pk>/resenas/<int:resena_id>/ocultar/',
        views.ModerarResena,
        {'accion': 'ocultar'},
        name='ocultar_resena',
    ),
    path(
        '<int:pk>/resenas/<int:resena_id>/restaurar/',
        views.ModerarResena,
        {'accion': 'restaurar'},
        name='restaurar_resena',
    ),
]
