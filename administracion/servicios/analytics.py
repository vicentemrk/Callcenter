"""Cálculo de analytics del período seleccionado."""

import logging
from datetime import timedelta

from django.db.models import Count, Min, Q
from django.utils import timezone

from online.models import Preguntas, Respuesta, Usuario

logger = logging.getLogger(__name__)

DIAS_VALIDOS = (7, 30, 90)
DIAS_POR_DEFECTO = 30


def _formatear_duracion(duracion):
    """Devuelve una duración legible en días, horas o minutos."""
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


def _normalizar_dias(dias):
    """Valida el período solicitado contra las opciones permitidas."""
    try:
        dias = int(dias)
    except (TypeError, ValueError):
        return DIAS_POR_DEFECTO
    return dias if dias in DIAS_VALIDOS else DIAS_POR_DEFECTO


def _tiempo_promedio_respuesta(preguntas_periodo):
    """Promedio de la primera respuesta de staff en el período."""
    respuestas_staff = (
        preguntas_periodo
        .annotate(
            primera_respuesta=Min(
                'respuesta__FechaHora',
                filter=Q(respuesta__Usuario__rol__in=['administrador', 'tecnico']),
            )
        )
        .filter(primera_respuesta__isnull=False)
        .values_list('Fecha_creacion', 'primera_respuesta')
    )
    tiempos = [
        primera - creada
        for creada, primera in respuestas_staff
        if primera >= creada
    ]
    if not tiempos:
        return "Sin datos"
    promedio = sum(tiempos, timedelta()) / len(tiempos)
    return _formatear_duracion(promedio)


def construir_contexto(dias=None):
    """Devuelve los datos de ``analytics_ia.html`` para el período."""
    try:
        dias = _normalizar_dias(dias)
        inicio = timezone.now() - timedelta(days=dias)
        preguntas_periodo = Preguntas.objects.filter(Fecha_creacion__gte=inicio)
        total_preguntas = preguntas_periodo.count()

        conteo_categorias = list(
            preguntas_periodo
            .values('categoria')
            .annotate(cantidad=Count('idPregunta'))
            .order_by('-cantidad', 'categoria')
        )
        etiquetas = dict(Preguntas._meta.get_field('categoria').choices)

        resueltas = (
            preguntas_periodo
            .filter(respuesta__isnull=False)
            .distinct()
            .count()
        )
        porcentaje_resueltas = 0.0
        if total_preguntas:
            porcentaje_resueltas = round(resueltas / total_preguntas * 100, 1)

        usuarios_activos = Usuario.objects.annotate(
            num_preguntas=Count('preguntas')
        ).order_by('-num_preguntas')[:10]

        return {
            'total_preguntas_mes': total_preguntas,
            'categorias_tendencia': {
                item['categoria']: item['cantidad']
                for item in conteo_categorias[:5]
            },
            'categorias_lista': [
                {
                    'categoria': item['categoria'],
                    'etiqueta': etiquetas.get(item['categoria'], item['categoria']),
                    'cantidad': item['cantidad'],
                    'porcentaje': (
                        round(item['cantidad'] / total_preguntas * 100, 1)
                        if total_preguntas
                        else 0.0
                    ),
                }
                for item in conteo_categorias
            ],
            'usuarios_activos': usuarios_activos,
            'preguntas_sin_respuesta': Preguntas.objects.filter(
                respuesta__isnull=True
            ).count(),
            'tiempo_promedio_respuesta': _tiempo_promedio_respuesta(
                preguntas_periodo
            ),
            'porcentaje_resueltas': porcentaje_resueltas,
            'total_respuestas': Respuesta.objects.filter(
                FechaHora__gte=inicio
            ).count(),
            'periodo': {
                'dias': dias,
                'etiqueta': f'Últimos {dias} días',
            },
        }
    except Exception:
        logger.exception("Error al cargar Analytics IA")
        return {'error': 'No se pudieron cargar los analytics'}
