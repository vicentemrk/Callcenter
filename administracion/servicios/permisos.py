"""Decorador de control de acceso por rol."""

from functools import wraps

from django.contrib import messages
from django.shortcuts import redirect


def _redirigir(request, destino):
    """Resuelve el destino de un redirect, admitiendo callables."""
    if callable(destino):
        return destino(request)
    if destino == 'inicio':
        return redirect('inicio', id=request.user.id)
    return redirect(destino or 'inicio')


def rol_requerido(*roles, destino=None, mensaje=None, redirecciones=None):
    """Permite la vista solo a los roles indicados.

    ``destino`` es el nombre de URL (o un callable) al que redirigir cuando el
    rol no está permitido; ``mensaje`` se muestra como error en ese caso.
    ``redirecciones`` permite un destino distinto según el rol del usuario.
    """

    def decorador(vista):
        @wraps(vista)
        def envoltura(request, *args, **kwargs):
            if request.user.rol in roles:
                return vista(request, *args, **kwargs)
            if mensaje:
                messages.error(request, mensaje)
            mapa = redirecciones or {}
            if request.user.rol in mapa:
                return redirect(mapa[request.user.rol])
            return _redirigir(request, destino)

        return envoltura

    return decorador
