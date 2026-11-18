"""Validadores del modelo Resena (Bloque 5B).

Se aplican a nivel de modelo (full_clean), no de formularios: las
reglas de contenido deben cumplirse sin importar como se construya la
instancia. La normalizacion (trim) se hace en clean(); el validador
solo rechaza, no muta el valor.
"""

from django.core.exceptions import ValidationError
from django.utils.translation import gettext_lazy as _

from marvel.constants import REFERENCIA_MINIMA


def validar_referencia_tematica(valor):
    """Referencia tematica: 10..200 caracteres REALES.

    max_length=200 lo protege el propio CharField (y la base). Aqui se
    rechaza el texto vacio o de solo espacios, y el texto que tras
    quitar espacios de los extremos quede con menos de
    REFERENCIA_MINIMA caracteres.
    """
    texto = (valor or '').strip()
    if not texto:
        raise ValidationError(
            _('La referencia temática no puede estar vacía.'),
            code='referencia_vacia',
        )
    if len(texto) < REFERENCIA_MINIMA:
        raise ValidationError(
            _(
                'La referencia temática debe tener al menos '
                '%(minima)d caracteres (sin contar espacios de los extremos).'
            ),
            code='referencia_corta',
            params={'minima': REFERENCIA_MINIMA},
        )
