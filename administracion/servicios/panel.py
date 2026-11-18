"""Contexto del panel de administración: métricas, tendencias y listado."""

from datetime import timedelta

from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.utils import timezone

from online.models import Preguntas, Usuario

PREGUNTAS_POR_PAGINA = 20
DIAS_TENDENCIAS = 7


def _metricas(inicio_semana):
    """Métricas globales (no dependen de los filtros del listado)."""
    datos = Preguntas.objects.aggregate(
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
    total = datos['total']
    sin_respuesta = datos['sin_respuesta']
    porcentaje = 0
    if total:
        porcentaje = ((total - sin_respuesta) / total) * 100
    return {
        'total_preguntas': total,
        'preguntas_sin_respuesta': sin_respuesta,
        'porcentaje_resueltas': porcentaje,
        'tendencia_semanal': datos['de_la_semana'],
    }


def _alertas(estadisticas):
    """Alertas derivadas de las métricas globales."""
    alertas = []
    if estadisticas['preguntas_sin_respuesta'] > 5:
        alertas.append({
            'tipo': 'warning',
            'mensaje': (
                f"⚠️ Hay {estadisticas['preguntas_sin_respuesta']} "
                'preguntas sin respuesta'
            ),
            'prioridad': 'alta',
        })
    if estadisticas['tendencia_semanal'] > 20:
        alertas.append({
            'tipo': 'info',
            'mensaje': '📈 Alta actividad esta semana',
            'prioridad': 'media',
        })
    return alertas


def _tendencias(inicio_semana):
    """Últimas preguntas de la semana para el bloque de tendencias."""
    recientes = (
        Preguntas.objects.select_related('Usuario')
        .filter(Fecha_creacion__gte=inicio_semana)
        .order_by('-Fecha_creacion', '-idPregunta')[:10]
    )
    return [
        {
            'id': pregunta.idPregunta,
            'titulo': pregunta.Titulo,
            'categoria': pregunta.categoria,
            'usuario': pregunta.Usuario.usuario,
            'fecha': pregunta.Fecha_creacion,
        }
        for pregunta in recientes
    ]


def construir_contexto(request):
    """Arma el contexto completo de ``indexAdmin.html``."""
    q = request.GET.get('q', '').strip()[:100]
    estado = request.GET.get('estado')
    prioridad = request.GET.get('prioridad')
    categoria = request.GET.get('categoria')
    # Filtro por tecnico asignado (Bloque 6B): 'sin_asignar', el id de
    # un tecnico o vacio. Los valores invalidos se ignoran (patron del
    # preseleccionado de elemento en Inicio), nunca generan consultas
    # inseguras.
    tecnico = request.GET.get('tecnico', '') or ''
    if tecnico and tecnico != 'sin_asignar' and not tecnico.isdigit():
        tecnico = ''

    tecnicos_disponibles = (
        Usuario.objects.filter(rol='tecnico', activo=True).order_by('usuario')
    )

    preguntas = (
        Preguntas.objects
        .select_related('Usuario', 'tecnico_asignado')
        .annotate(num_respuestas=Count('respuesta'))
    )
    if estado:
        preguntas = preguntas.filter(estado=estado)
    if prioridad:
        preguntas = preguntas.filter(prioridad=prioridad)
    if categoria:
        preguntas = preguntas.filter(categoria=categoria)
    if tecnico == 'sin_asignar':
        preguntas = preguntas.filter(tecnico_asignado__isnull=True)
    elif tecnico:
        preguntas = preguntas.filter(tecnico_asignado_id=int(tecnico))
    if q:
        preguntas = preguntas.filter(
            Q(Titulo__icontains=q)
            | Q(Pregunta__icontains=q)
            | Q(Usuario__usuario__icontains=q)
        )
    preguntas = preguntas.order_by('-Fecha_creacion', '-idPregunta')

    inicio_semana = timezone.now() - timedelta(days=DIAS_TENDENCIAS)
    estadisticas = _metricas(inicio_semana)

    paginador = Paginator(preguntas, PREGUNTAS_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get('page'))

    return {
        'Preguntas': pagina,
        'page_obj': pagina,
        'is_paginated': pagina.has_other_pages(),
        'paginator': paginador,
        'total_filtrado': paginador.count,
        'q': q,
        'total_usuarios': Usuario.objects.count(),
        'tendencias_ia': _tendencias(inicio_semana),
        'estadisticas_ia': estadisticas,
        'alertas_ia': _alertas(estadisticas),
        'estados': Preguntas.ESTADOS,
        'prioridades': Preguntas.PRIORIDADES,
        'categorias': Preguntas._meta.get_field('categoria').choices,
        'tecnicos_disponibles': tecnicos_disponibles,
        'filtros': {
            'estado': estado or '',
            'prioridad': prioridad or '',
            'categoria': categoria or '',
            'tecnico': tecnico,
        },
    }
