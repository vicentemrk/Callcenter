from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from online.models import Auditoria, Preguntas, Usuario
from online.forms import PreguntaAdminForm, UsuarioRolForm
from online.ia_utils import AsistenteIA
from datetime import timedelta
from django.db.models import Count, Min, Q
from django.utils import timezone
from django.views.decorators.http import require_POST
import logging

# Este logger usa la configuracion de la aplicacion "administracion".
logger = logging.getLogger(__name__)

def _formatear_duracion(duracion):
    segundos = duracion.total_seconds()
    if segundos >= 86400:
        valor, singular, plural = segundos / 86400, "día", "días"
    elif segundos >= 3600:
        valor, singular, plural = segundos / 3600, "hora", "horas"
    else:
        valor, singular, plural = max(1, round(segundos / 60)), "minuto", "minutos"
    valor = round(valor, 1)
    if valor == int(valor):
        valor = int(valor)
    unidad = singular if valor == 1 else plural
    return f"{valor} {unidad}"

@login_required
def IndexAdmin(request):
    """
    Vista principal de administración con métricas y categorías guardadas
    """
    if request.user.rol not in ('administrador', 'tecnico'):
        messages.error(request, "No tienes permisos para acceder a esta página.")
        return redirect('inicio', id=request.user.id)

    preguntas = (
        Preguntas.objects
        .select_related('Usuario')
        .annotate(num_respuestas=Count('respuesta'))
        .order_by('-Fecha_creacion')
    )
    estado = request.GET.get('estado')
    prioridad = request.GET.get('prioridad')
    categoria = request.GET.get('categoria')
    if estado:
        preguntas = preguntas.filter(estado=estado)
    if prioridad:
        preguntas = preguntas.filter(prioridad=prioridad)
    if categoria:
        preguntas = preguntas.filter(categoria=categoria)
    inicio_semana = timezone.now() - timedelta(days=7)
    metricas = Preguntas.objects.aggregate(
        total=Count('idPregunta', distinct=True),
        sin_respuesta=Count(
            'idPregunta',
            distinct=True,
            filter=Q(respuesta__isnull=True),
        ),
        de_la_semana=Count(
            'idPregunta',
            distinct=True,
            filter=Q(Fecha_creacion__gte=inicio_semana),
        ),
    )
    total_preguntas = metricas['total']
    preguntas_sin_respuesta = metricas['sin_respuesta']
    preguntas_semana = metricas['de_la_semana']
    porcentaje_resueltas = 0
    if total_preguntas:
        porcentaje_resueltas = (
            (total_preguntas - preguntas_sin_respuesta) / total_preguntas
        ) * 100

    estadisticas_ia = {
        'total_preguntas': total_preguntas,
        'preguntas_sin_respuesta': preguntas_sin_respuesta,
        'porcentaje_resueltas': porcentaje_resueltas,
        'tendencia_semanal': preguntas_semana
    }
    alertas_ia = []
    if preguntas_sin_respuesta > 5:
        alertas_ia.append({
            'tipo': 'warning',
            'mensaje': f'⚠️ Hay {preguntas_sin_respuesta} preguntas sin respuesta',
            'prioridad': 'alta'
        })
    if preguntas_semana > 20:
        alertas_ia.append({
            'tipo': 'info',
            'mensaje': '📈 Alta actividad esta semana',
            'prioridad': 'media'
        })

    preguntas_recientes = list(
        preguntas.filter(
            Fecha_creacion__gte=timezone.now() - timedelta(days=7)
        )[:10]
    )
    tendencias_ia = [
        {
            'id': pregunta.idPregunta,
            'titulo': pregunta.Titulo,
            'categoria': pregunta.categoria,
            'usuario': pregunta.Usuario.usuario,
            'fecha': pregunta.Fecha_creacion
        }
        for pregunta in preguntas_recientes
    ]

    return render(request, "indexAdmin.html", {
        "Preguntas": preguntas,
        "total_usuarios": Usuario.objects.count(),
        "tendencias_ia": tendencias_ia,
        "estadisticas_ia": estadisticas_ia,
        "alertas_ia": alertas_ia,
        "estados": Preguntas.ESTADOS,
        "prioridades": Preguntas.PRIORIDADES,
        "categorias": Preguntas._meta.get_field('categoria').choices,
        "filtros": {
            "estado": estado or "",
            "prioridad": prioridad or "",
            "categoria": categoria or "",
        },
    })

@login_required
@require_POST
def BorrarPregunta(request, idUser, idPregunta):
    """
    Vista para borrar preguntas
    """
    if request.user.rol != 'administrador':
        if request.user.rol == 'tecnico':
            return redirect('administracion')
        return redirect('inicio', id=request.user.id)

    try:
        pregunta = Preguntas.objects.get(idPregunta=idPregunta)
    except Preguntas.DoesNotExist:
        messages.error(request, "La pregunta o usuario no existe.")
        return redirect('administracion')
    pregunta.delete()
    Auditoria.objects.create(
        usuario=request.user,
        accion='eliminar_pregunta',
        detalle=f'Pregunta #{idPregunta} eliminada',
    )
    messages.success(request, "Pregunta eliminada correctamente.")
    return redirect('administracion')

@login_required
def GestionUsuarios(request):
    """
    Vista de gestión de usuarios
    """
    if request.user.rol != 'administrador':
        messages.error(request, "No tienes permisos de administrador.")
        return redirect('inicio', id=request.user.id)

    usuarios = Usuario.objects.all()

    if request.method == "POST":
        user_id = request.POST.get('Userid')
        try:
            userchange = Usuario.objects.get(id=user_id)

            if userchange.id == request.user.id:
                messages.error(
                    request,
                    "No puedes modificar tus propios permisos ni desactivar tu cuenta."
                )
                return redirect('gestion_usuarios')

            form = UsuarioRolForm(request.POST, instance=userchange)
            if 'rol' not in request.POST:
                legacy_role = (
                    'administrador'
                    if request.POST.get('admin') == 'on'
                    else 'tecnico'
                    if request.POST.get('tecnico') == 'on'
                    else 'cliente'
                )
                form = UsuarioRolForm(
                    {'rol': legacy_role, 'activo': request.POST.get('activo') == 'on'},
                    instance=userchange,
                )
            if not form.is_valid():
                messages.error(request, "Los datos del usuario no son válidos.")
                return redirect('gestion_usuarios')
            form.save()
            Auditoria.objects.create(
                usuario=request.user,
                accion='modificar_usuario',
                detalle=f'Usuario {userchange.usuario}: rol {userchange.rol}',
            )

            messages.success(request, f"Usuario {userchange.usuario} actualizado correctamente.")
            return redirect('gestion_usuarios')

        except Usuario.DoesNotExist:
            messages.error(request, "El usuario no existe.")

    return render(request, "GestionUsuarios.html", {
        "Usuarios": usuarios
    })

@login_required
@require_POST
def EliminarUsuario(request, idUser):
    """
    Vista para eliminar usuarios
    """
    if request.user.rol == 'administrador':
        try:
            usuario = Usuario.objects.get(id=idUser)
            if usuario.id == request.user.id:
                messages.error(request, "No puedes eliminar tu propia cuenta.")
                return redirect('gestion_usuarios')

            usuario_eliminado = usuario.usuario
            usuario.delete()
            Auditoria.objects.create(
                usuario=request.user,
                accion='eliminar_usuario',
                detalle=f'Usuario {usuario_eliminado} eliminado',
            )
            messages.success(request, f"Usuario {usuario_eliminado} eliminado correctamente.")

        except Usuario.DoesNotExist:
            messages.error(request, "El usuario no existe.")
    else:
        messages.error(request, "No tienes permisos para realizar esta acción.")

    return redirect('gestion_usuarios')

@login_required
def ModificarPregunta(request, idPregunta):
    """
    Vista para modificar preguntas
    """
    if request.user.rol not in ('administrador', 'tecnico'):
        messages.error(request, "No tienes permisos para modificar tickets.")
        return redirect('inicio', id=request.user.id)

    try:
        pregunta = Preguntas.objects.get(idPregunta=idPregunta)
        texto_anterior = pregunta.Pregunta
        form = PreguntaAdminForm(instance=pregunta)

        if request.method == 'POST':
            form = PreguntaAdminForm(request.POST, instance=pregunta)
            if form.is_valid():
                pregunta_actualizada = form.save(commit=False)
                pregunta_actualizada.Usuario = pregunta.Usuario
                pregunta_actualizada.Fecha_creacion = pregunta.Fecha_creacion
                if pregunta_actualizada.Pregunta != texto_anterior:
                    pregunta_actualizada.categoria = (
                        AsistenteIA().clasificar_pregunta(
                            pregunta_actualizada.Pregunta
                        )
                    )
                pregunta_actualizada.save()
                Auditoria.objects.create(
                    usuario=request.user,
                    pregunta=pregunta_actualizada,
                    accion='modificar_pregunta',
                    detalle=(
                        f'Estado: {pregunta_actualizada.estado}; '
                        f'Prioridad: {pregunta_actualizada.prioridad}'
                    ),
                )
                messages.success(request, "Pregunta modificada correctamente.")
                return redirect('administracion')
            else:
                messages.error(request, "Error en el formulario. Verifica los datos.")

        return render(request, "ModificarPregunta.html", {
            "form": form,
            "pregunta": pregunta
        })

    except Preguntas.DoesNotExist:
        messages.error(request, "La pregunta no existe.")
        return redirect('administracion')

@login_required
def AnalyticsIA(request):
    """
    Vista exclusiva para análisis avanzados con categorías guardadas
    """
    if request.user.rol != 'administrador':
        messages.error(request, "No tienes permisos de administrador.")
        return redirect('inicio', id=request.user.id)

    try:
        ahora = timezone.now()
        # Tendencias por categoría de los últimos 30 días
        preguntas_ultimo_mes = Preguntas.objects.filter(
            Fecha_creacion__gte=ahora - timedelta(days=30)
        )

        conteo_categorias = (
            preguntas_ultimo_mes
            .values('categoria')
            .annotate(cantidad=Count('idPregunta'))
            .order_by('-cantidad')[:5]
        )

        # Tiempo promedio de primera respuesta de staff (admin o técnico)
        respuestas_staff = (
            preguntas_ultimo_mes
            .annotate(
                primera_respuesta=Min(
                    'respuesta__FechaHora',
                    filter=Q(respuesta__Usuario__rol__in=['administrador', 'tecnico']),
                )
            )
            .filter(primera_respuesta__isnull=False)
            .values_list('Fecha_creacion', 'primera_respuesta')
        )
        tiempos_respuesta = [
            primera - creada
            for creada, primera in respuestas_staff
            if primera >= creada
        ]
        if tiempos_respuesta:
            promedio_respuesta = (
                sum(tiempos_respuesta, timedelta()) / len(tiempos_respuesta)
            )
            tiempo_promedio = _formatear_duracion(promedio_respuesta)
        else:
            tiempo_promedio = "Sin datos"

        # Usuarios más activos
        usuarios_activos = Usuario.objects.annotate(
            num_preguntas=Count('preguntas')
        ).order_by('-num_preguntas')[:10]

        analytics_data = {
            'total_preguntas_mes': preguntas_ultimo_mes.count(),
            'categorias_tendencia': {
                item['categoria']: item['cantidad']
                for item in conteo_categorias
            },
            'usuarios_activos': usuarios_activos,
            'preguntas_sin_respuesta': Preguntas.objects.filter(respuesta__isnull=True).count(),
            'tiempo_promedio_respuesta': tiempo_promedio
        }

    except Exception:
        logger.exception("Error al cargar Analytics IA")
        analytics_data = {'error': 'No se pudieron cargar los analytics'}

    return render(request, "analytics_ia.html", {
        "analytics_data": analytics_data
    })

@login_required
@require_POST
def CerrarPregunta(request, idPregunta):
    if request.user.rol not in ('administrador', 'tecnico'):
        return redirect('inicio', id=request.user.id)
    try:
        pregunta = Preguntas.objects.get(idPregunta=idPregunta)
    except Preguntas.DoesNotExist:
        messages.error(request, "La pregunta no existe.")
        return redirect('administracion')
    pregunta.estado = 'cerrado'
    pregunta.save(update_fields=['estado'])
    Auditoria.objects.create(
        usuario=request.user,
        pregunta=pregunta,
        accion='cambiar_estado',
        detalle='Estado cambiado a cerrado',
    )
    messages.success(request, "Pregunta cerrada correctamente.")
    return redirect('administracion')

@login_required
@require_POST
def ReabrirPregunta(request, idPregunta):
    if request.user.rol not in ('administrador', 'tecnico'):
        return redirect('inicio', id=request.user.id)
    try:
        pregunta = Preguntas.objects.get(idPregunta=idPregunta)
    except Preguntas.DoesNotExist:
        messages.error(request, "La pregunta no existe.")
        return redirect('administracion')
    pregunta.estado = 'en_proceso'
    pregunta.save(update_fields=['estado'])
    Auditoria.objects.create(
        usuario=request.user,
        pregunta=pregunta,
        accion='cambiar_estado',
        detalle='Estado cambiado a en proceso',
    )
    messages.success(request, "Pregunta reabierta correctamente.")
    return redirect('administracion')
