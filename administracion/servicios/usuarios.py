"""Gestión de usuarios: filtros, contadores e invariante de último admin."""

from django.db import transaction
from django.db.models import Count, Q

from online.forms import UsuarioRolForm
from online.models import Auditoria, Usuario


class ErrorUsuarios(Exception):
    """Error de negocio al modificar o eliminar usuarios."""


def es_ultimo_admin_activo(usuario):
    """True si es el único administrador activo del sistema."""
    if usuario.rol != 'administrador' or not usuario.activo:
        return False
    return not (
        Usuario.objects
        .filter(rol='administrador', activo=True)
        .exclude(pk=usuario.pk)
        .exists()
    )


def filtrar(q='', rol='', activo=''):
    """Listado de usuarios con búsqueda y filtros validados."""
    usuarios = Usuario.objects.all()
    q = (q or '').strip()[:100]
    if q:
        usuarios = usuarios.filter(
            Q(usuario__icontains=q) | Q(correo__icontains=q)
        )
    roles_validos = {valor for valor, _ in Usuario.ROLES}
    if rol in roles_validos:
        usuarios = usuarios.filter(rol=rol)
    if activo in ('1', '0'):
        usuarios = usuarios.filter(activo=(activo == '1'))
    return usuarios.order_by('usuario')


def contadores():
    """Totales por rol y cuentas inactivas en una sola consulta."""
    return Usuario.objects.aggregate(
        administradores=Count('pk', filter=Q(rol='administrador')),
        tecnicos=Count('pk', filter=Q(rol='tecnico')),
        clientes=Count('pk', filter=Q(rol='cliente')),
        inactivos=Count('pk', filter=Q(activo=False)),
        total=Count('pk'),
    )


def actualizar(usuario_objetivo, datos, actor):
    """Actualiza rol y estado de una cuenta, protegiendo al último admin."""
    if usuario_objetivo.pk == actor.pk:
        raise ErrorUsuarios(
            "No puedes modificar tus propios permisos ni desactivar tu cuenta."
        )

    with transaction.atomic():
        objetivo = Usuario.objects.select_for_update().get(
            pk=usuario_objetivo.pk
        )
        era_ultimo_admin = es_ultimo_admin_activo(objetivo)

        form = UsuarioRolForm(datos, instance=objetivo)
        if 'rol' not in datos:
            rol_legacy = (
                'administrador'
                if datos.get('admin') == 'on'
                else 'tecnico'
                if datos.get('tecnico') == 'on'
                else 'cliente'
            )
            form = UsuarioRolForm(
                {
                    'rol': rol_legacy,
                    'activo': datos.get('activo') == 'on',
                },
                instance=objetivo,
            )
        if not form.is_valid():
            raise ErrorUsuarios("Los datos del usuario no son válidos.")

        nuevo_rol = form.cleaned_data['rol']
        nuevo_activo = form.cleaned_data['activo']
        if era_ultimo_admin and (
            nuevo_rol != 'administrador' or not nuevo_activo
        ):
            raise ErrorUsuarios(
                "No puedes dejar el sistema sin administradores activos."
            )

        form.save()
        Auditoria.objects.create(
            usuario=actor,
            accion='modificar_usuario',
            detalle=f'Usuario {objetivo.usuario}: rol {objetivo.rol}',
        )
    return objetivo


def eliminar(usuario_objetivo, actor):
    """Elimina una cuenta, protegiendo al último admin activo."""
    if usuario_objetivo.pk == actor.pk:
        raise ErrorUsuarios("No puedes eliminar tu propia cuenta.")

    with transaction.atomic():
        objetivo = Usuario.objects.select_for_update().get(
            pk=usuario_objetivo.pk
        )
        if es_ultimo_admin_activo(objetivo):
            raise ErrorUsuarios(
                "No puedes dejar el sistema sin administradores activos."
            )
        nombre = objetivo.usuario
        objetivo.delete()
        Auditoria.objects.create(
            usuario=actor,
            accion='eliminar_usuario',
            detalle=f'Usuario {nombre} eliminado',
        )
    return nombre


def actualizar_desde_post(user_id, datos, actor):
    """Actualiza desde el POST de gestión; devuelve ``(éxito, mensaje)``."""
    try:
        objetivo = Usuario.objects.get(id=user_id)
    except (Usuario.DoesNotExist, TypeError, ValueError):
        return False, "El usuario no existe."
    try:
        actualizar(objetivo, datos, actor)
    except ErrorUsuarios as error:
        return False, str(error)
    return True, f"Usuario {objetivo.usuario} actualizado correctamente."


def eliminar_por_id(user_id, actor):
    """Elimina desde el POST de gestión; devuelve ``(éxito, mensaje)``."""
    try:
        objetivo = Usuario.objects.get(id=user_id)
        nombre = eliminar(objetivo, actor)
    except Usuario.DoesNotExist:
        return False, "El usuario no existe."
    except ErrorUsuarios as error:
        return False, str(error)
    return True, f"Usuario {nombre} eliminado correctamente."


def construir_contexto(request):
    """Contexto de ``GestionUsuarios.html`` con filtros y contadores."""
    filtros = {
        clave: request.GET.get(clave, '')
        for clave in ('q', 'rol', 'activo')
    }
    listado = filtrar(**filtros)
    return {
        'Usuarios': listado,
        'contadores': contadores(),
        'filtros': filtros,
        'q': filtros['q'],
        'roles': Usuario.ROLES,
        'total_filtrado': listado.count(),
    }
