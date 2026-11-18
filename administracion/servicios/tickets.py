"""Operaciones sobre tickets con auditoría y transacciones."""

from django.db import transaction

from online.forms import PreguntaAdminForm
from online.ia_utils import AsistenteIA
from online.models import Auditoria, Preguntas, Usuario


def asignar(id_pregunta, usuario, tecnico_id=None):
    """Asigna, reasigna o desasigna el técnico de una pregunta (Bloque 6B).

    Reglas aprobadas por el propietario (6A):

    - administrador: asigna/reasigna a cualquier técnico activo y puede
      desasignar (tecnico_id vacío o None).
    - tecnico: SOLO puede autoasignarse tickets sin técnico (o reafirmar
      su propia asignación, sin registro de auditoria duplicado); nunca
      asigna a otros, se apropia de ajenos ni desasigna.
    - cliente/visitante: no pueden (la vista también lo bloquea; el
      servicio lo re-verifica de forma independiente).
    - tickets cerrados: sin cambios hasta que se reabra la pregunta.
    - el técnico destino debe existir, tener rol tecnico y estar activo
      (limit_choices_to del modelo no protege en el servidor).
    - sin cambio efectivo: no se toca el ticket ni se audita.

    El identificador del técnico que envía un POST de un técnico se
    descarta SIEMPRE: el destino es request.user (obtenido en la vista),
    nunca un campo manipulable.

    Devuelve ``(ok, mensaje)``. Lanza ``Preguntas.DoesNotExist`` si el
    ticket no existe (la vista lo captura, como en cerrar/reabrir).
    """
    if getattr(usuario, 'rol', None) not in ('administrador', 'tecnico'):
        return False, 'No tienes permisos para cambiar la asignación.'

    with transaction.atomic():
        pregunta = (
            Preguntas.objects
            .select_for_update()
            .select_related('tecnico_asignado')
            .get(idPregunta=id_pregunta)
        )

        if pregunta.estado == 'cerrado':
            return False, (
                'El ticket está cerrado: reabre la pregunta antes de '
                'cambiar el técnico.'
            )

        if usuario.rol == 'tecnico':
            if tecnico_id is not None and str(tecnico_id) != str(usuario.id):
                # Blindaje en el servicio: el técnico solo apunta a sí
                # mismo, sin importar lo que traiga el POST.
                return False, 'Un técnico solo puede autoasignarse el ticket.'
            nuevo_id = usuario.id
        else:
            if tecnico_id is None or str(tecnico_id) == '':
                nuevo_id = None  # desasignar
            elif str(tecnico_id).isdigit():
                nuevo_id = int(tecnico_id)
            else:
                return False, 'Identificador de técnico inválido.'

        if nuevo_id == pregunta.tecnico_asignado_id:
            # Sin cambio efectivo: mensaje informativo, sin auditoria.
            if nuevo_id is None:
                return True, 'El ticket no tenía técnico asignado.'
            if usuario.rol == 'tecnico':
                return True, 'El ticket ya está asignado a ti.'
            return True, 'El ticket ya está asignado a ese técnico.'

        anterior = pregunta.tecnico_asignado

        if usuario.rol == 'tecnico' and anterior is not None:
            # Ya asignado a otro técnico: no apropiarse ni desasignar.
            return False, 'El ticket ya tiene un técnico asignado.'

        if nuevo_id is not None:
            destino = Usuario.objects.filter(pk=nuevo_id).first()
            if destino is None:
                return False, 'El técnico indicado no existe.'
            if destino.rol != 'tecnico':
                return False, (
                    'Solo se puede asignar a usuarios con rol técnico.'
                )
            if not destino.activo:
                return False, 'El técnico está inactivo.'

        pregunta.tecnico_asignado_id = nuevo_id
        pregunta.save(update_fields=['tecnico_asignado'])

        nombre_anterior = anterior.usuario if anterior else 'Sin técnico'
        if nuevo_id is None:
            operacion = 'Desasignación de técnico'
            detalle = f'{operacion}: {nombre_anterior} -> Sin técnico'
            mensaje = 'Técnico desasignado correctamente.'
        else:
            destino_nombre = Usuario.objects.get(pk=nuevo_id).usuario
            if anterior is None:
                operacion = 'Asignación de técnico'
            else:
                operacion = 'Reasignación de técnico'
            detalle = (
                f'{operacion}: {nombre_anterior} -> {destino_nombre}'
            )
            mensaje = f'Técnico asignado: {destino_nombre}.'
        # No existe un accion propio para asignaciones: agregarlo a
        # ACCIONES generaria una migracion no autorizada en 6B. Se usa
        # 'modificar_pregunta' con el detalle de la operacion.
        Auditoria.objects.create(
            usuario=usuario,
            pregunta=pregunta,
            accion='modificar_pregunta',
            detalle=detalle[:255],
        )
        return True, mensaje


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
        pregunta = (
            Preguntas.objects
            .select_for_update()
            .select_related('elemento_catalogo')
            .get(idPregunta=id_pregunta)
        )
        texto_anterior = pregunta.Pregunta
        usuario_original = pregunta.Usuario
        fecha_original = pregunta.Fecha_creacion
        elemento_original = pregunta.elemento_catalogo

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

        detalle = (
            f'Estado: {actualizada.estado}; '
            f'Prioridad: {actualizada.prioridad}'
        )
        if actualizada.elemento_catalogo_id != _id_elemento(elemento_original):
            detalle += (
                f' ; Elemento Marvel: {_texto_elemento(elemento_original)}'
                f' -> {_texto_elemento(actualizada.elemento_catalogo)}'
            )
        Auditoria.objects.create(
            usuario=usuario,
            pregunta=actualizada,
            accion='modificar_pregunta',
            detalle=detalle[:255],
        )
        return {
            'form': form,
            'pregunta': actualizada,
            'guardado': True,
            'datos_invalidos': False,
        }


def _id_elemento(elemento):
    """Identificador del elemento relacionado (None si no hay)."""
    return elemento.pk if elemento is not None else None


def _texto_elemento(elemento):
    """Texto corto del elemento para la auditoria (None -> 'Sin elemento')."""
    if elemento is None:
        return 'Sin elemento'
    return f'{elemento.get_tipo_display()}: {elemento.nombre}'
