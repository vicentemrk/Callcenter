"""Operaciones sobre tickets con auditoría y transacciones."""

from django.db import transaction

from online.forms import PreguntaAdminForm
from online.ia_utils import AsistenteIA
from online.models import Auditoria, Preguntas


def cerrar(id_pregunta, usuario):
    """Cierra una pregunta registrando la auditoría."""
    with transaction.atomic():
        pregunta = Preguntas.objects.select_for_update().get(
            idPregunta=id_pregunta
        )
        pregunta.estado = 'cerrado'
        pregunta.save(update_fields=['estado'])
        Auditoria.objects.create(
            usuario=usuario,
            pregunta=pregunta,
            accion='cambiar_estado',
            detalle='Estado cambiado a cerrado',
        )


def reabrir(id_pregunta, usuario):
    """Reabre una pregunta (estado en proceso) registrando la auditoría."""
    with transaction.atomic():
        pregunta = Preguntas.objects.select_for_update().get(
            idPregunta=id_pregunta
        )
        pregunta.estado = 'en_proceso'
        pregunta.save(update_fields=['estado'])
        Auditoria.objects.create(
            usuario=usuario,
            pregunta=pregunta,
            accion='cambiar_estado',
            detalle='Estado cambiado a en proceso',
        )


def borrar(id_pregunta, usuario):
    """Elimina una pregunta y deja el registro de auditoría."""
    with transaction.atomic():
        pregunta = Preguntas.objects.select_for_update().get(
            idPregunta=id_pregunta
        )
        pregunta.delete()
        Auditoria.objects.create(
            usuario=usuario,
            accion='eliminar_pregunta',
            detalle=f'Pregunta #{id_pregunta} eliminada',
        )


def modificar(id_pregunta, datos, usuario):
    """Valida y guarda los cambios de una pregunta.

    ``datos`` es ``request.POST`` o ``None`` para el formulario vacío.
    Devuelve el formulario, la pregunta y banderas de resultado.
    """
    if datos is None:
        pregunta = Preguntas.objects.get(idPregunta=id_pregunta)
        return {
            'form': PreguntaAdminForm(instance=pregunta),
            'pregunta': pregunta,
            'guardado': False,
            'datos_invalidos': False,
        }

    with transaction.atomic():
        pregunta = Preguntas.objects.select_for_update().get(
            idPregunta=id_pregunta
        )
        texto_anterior = pregunta.Pregunta
        usuario_original = pregunta.Usuario
        fecha_original = pregunta.Fecha_creacion

        form = PreguntaAdminForm(datos, instance=pregunta)
        if not form.is_valid():
            return {
                'form': form,
                'pregunta': pregunta,
                'guardado': False,
                'datos_invalidos': True,
            }

        actualizada = form.save(commit=False)
        actualizada.Usuario = usuario_original
        actualizada.Fecha_creacion = fecha_original
        if actualizada.Pregunta != texto_anterior:
            actualizada.categoria = AsistenteIA().clasificar_pregunta(
                actualizada.Pregunta
            )
        actualizada.save()
        Auditoria.objects.create(
            usuario=usuario,
            pregunta=actualizada,
            accion='modificar_pregunta',
            detalle=(
                f'Estado: {actualizada.estado}; '
                f'Prioridad: {actualizada.prioridad}'
            ),
        )
        return {
            'form': form,
            'pregunta': actualizada,
            'guardado': True,
            'datos_invalidos': False,
        }
