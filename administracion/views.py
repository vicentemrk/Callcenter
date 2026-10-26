from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from online.models import Preguntas, Usuario

from administracion.servicios import analytics, panel, tickets, usuarios
from administracion.servicios.analytics import _formatear_duracion  # noqa: F401
from administracion.servicios.permisos import rol_requerido


def _ejecutar_ticket(request, accion, id_pregunta, mensaje_exito, mensaje_error):
    try:
        accion(id_pregunta, request.user)
    except Preguntas.DoesNotExist:
        messages.error(request, mensaje_error)
    else:
        messages.success(request, mensaje_exito)
    return redirect('administracion')


@login_required
@rol_requerido('administrador', 'tecnico', destino='inicio', mensaje="No tienes permisos para acceder a esta página.")
def IndexAdmin(request):
    """Vista principal de administración con métricas y categorías guardadas."""
    return render(request, "indexAdmin.html", panel.construir_contexto(request))


@login_required
@require_POST
@rol_requerido('administrador', destino='inicio', redirecciones={'tecnico': 'administracion'})
def BorrarPregunta(request, idUser, idPregunta):
    """Elimina una pregunta registrando la auditoría."""
    return _ejecutar_ticket(
        request, tickets.borrar, idPregunta, "Pregunta eliminada correctamente.",
        "La pregunta o usuario no existe.",
    )


@login_required
@rol_requerido('administrador', destino='inicio',
               mensaje="No tienes permisos de administrador.",
               redirecciones={'tecnico': 'administracion'})
def GestionUsuarios(request):
    """Listado filtrado de usuarios y actualización de rol/estado."""
    if request.method == "POST":
        ok, mensaje = usuarios.actualizar_desde_post(
            request.POST.get('Userid'), request.POST, request.user
        )
        (messages.success if ok else messages.error)(request, mensaje)
        return redirect('gestion_usuarios')
    return render(request, "GestionUsuarios.html", usuarios.construir_contexto(request))


@login_required
@require_POST
@rol_requerido('administrador', destino='gestion_usuarios', mensaje="No tienes permisos para realizar esta acción.")
def EliminarUsuario(request, idUser):
    """Elimina un usuario salvo que sea el último administrador activo."""
    ok, mensaje = usuarios.eliminar_por_id(idUser, request.user)
    (messages.success if ok else messages.error)(request, mensaje)
    return redirect('gestion_usuarios')


@login_required
@rol_requerido('administrador', 'tecnico', destino='inicio')
def ModificarPregunta(request, idPregunta):
    """Edita una pregunta; reclasifica con IA solo si cambió el texto."""
    datos = request.POST if request.method == 'POST' else None
    try:
        resultado = tickets.modificar(idPregunta, datos, request.user)
    except Preguntas.DoesNotExist:
        messages.error(request, "La pregunta no existe.")
        return redirect('administracion')
    if resultado['guardado']:
        messages.success(request, "Pregunta modificada correctamente.")
        return redirect('administracion')
    if resultado['datos_invalidos']:
        messages.error(request, "Error en el formulario. Verifica los datos.")
    return render(request, "ModificarPregunta.html", {"form": resultado['form'], "pregunta": resultado['pregunta']})


@login_required
@rol_requerido('administrador', destino='inicio', mensaje="No tienes permisos de administrador.")
def AnalyticsIA(request):
    """Análisis avanzado del período seleccionado."""
    datos = analytics.construir_contexto(request.GET.get('dias'))
    return render(request, "analytics_ia.html", {"analytics_data": datos})


@login_required
@require_POST
@rol_requerido('administrador', 'tecnico', destino='inicio')
def CerrarPregunta(request, idPregunta):
    """Cierra una pregunta."""
    return _ejecutar_ticket(
        request, tickets.cerrar, idPregunta,
        "Pregunta cerrada correctamente.", "La pregunta no existe.",
    )


@login_required
@require_POST
@rol_requerido('administrador', 'tecnico', destino='inicio')
def ReabrirPregunta(request, idPregunta):
    """Reabre una pregunta."""
    return _ejecutar_ticket(
        request, tickets.reabrir, idPregunta,
        "Pregunta reabierta correctamente.", "La pregunta no existe.",
    )
