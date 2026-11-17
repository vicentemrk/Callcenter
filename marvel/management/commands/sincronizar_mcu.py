"""Comando de sincronizacion del catalogo MCU.

Sintaxis definitiva (documentada tambien en cambios_marvel.txt):

    python manage.py sincronizar_mcu                          # todos los tipos, sin limite
    python manage.py sincronizar_mcu --tipo movie --limite 10
    python manage.py sincronizar_mcu --tipo tvshow --limite 10
    python manage.py sincronizar_mcu --tipo character --limite 10
    python manage.py sincronizar_mcu --tipo todos --limite 10 --pagina 10

- --tipo: movie | tvshow | character | todos (por defecto: todos).
- --limite: cantidad maxima de registros a procesar POR TIPO. Sin limite
  el comando recorre TODAS las paginas del tipo (sincronizacion completa).
- --pagina: tamanio de pagina pedida a la API (1-100; la API rechaza
  limites mayores que 100 con un 400).

La sincronizacion es idempotente por (tipo, mcu_id): repetir el comando
no duplica ni re-graba registros sin cambios, y NUNCA elimina elementos.
"""

from django.core.management.base import BaseCommand, CommandError

from marvel.mcu_client import (
    MCUAPIError,
    MCUAPIRateLimitError,
)
from marvel import services
from marvel.constants import TIPOS_ELEMENTO

TIPOS_VALIDOS = ('movie', 'tvshow', 'character')


class Command(BaseCommand):
    help = (
        'Sincroniza el catalogo Marvel (peliculas, series y personajes) '
        'desde MCU API hacia la tabla local marvel_elementocatalogo. '
        'Idempotente: repetirlo no duplica registros.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--tipo',
            choices=TIPOS_VALIDOS + ('todos',),
            default='todos',
            help="Tipo a sincronizar: movie | tvshow | character | todos.",
        )
        parser.add_argument(
            '--limite',
            type=int,
            default=None,
            metavar='N',
            help=(
                'Cantidad maxima de registros por tipo. Sin este '
                'parametro la sincronizacion es completa (todas las paginas).'
            ),
        )
        parser.add_argument(
            '--pagina',
            type=int,
            default=10,
            metavar='N',
            help='Registros por pagina solicitada a la API (por defecto 10, maximo 100).',
        )

    def _validar_parametros(self, limite, tamano_pagina):
        if limite is not None and limite < 1:
            raise CommandError('--limite debe ser mayor o igual a 1.')
        if not 1 <= tamano_pagina <= 100:
            raise CommandError('--pagina debe estar entre 1 y 100.')

    def _resumen(self, stats):
        """Linea de resumen para cada tipo, legible y sin datos sensibles."""
        return (
            f"{stats['tipo']}: procesados={stats['procesados']}"
            f" creados={stats['creados']} actualizados={stats['actualizados']}"
            f" sin_cambios={stats['sin_cambios']} incompletos={stats['incompletos']}"
            f" errores={stats['errores']} paginas={stats['paginas']}"
            f" total_api={stats['total_api']} parcial={stats['acotado']}"
        )

    def handle(self, *args, **opciones):
        tipo = opciones['tipo']
        limite = opciones['limite']
        tamano_pagina = opciones['pagina']

        self._validar_parametros(limite, tamano_pagina)

        tipos = TIPOS_VALIDOS if tipo == 'todos' else (tipo,)
        hubo_errores = False

        for nombre in tipos:
            try:
                stats = services.sincronizar_tipo(
                    nombre,
                    limite=limite,
                    tamano_pagina=tamano_pagina,
                )
            except MCUAPIRateLimitError as error:
                # 429: terminar este tipo; el resto de tipos se reintenta
                # porque el rate limit se restablece por minuto.
                self.stderr.write(self.style.WARNING(
                    f"{nombre}: limite de tasa de MCU API alcanzado ({error}). "
                    "Espera un minuto y vuelve a ejecutar el comando."
                ))
                hubo_errores = True
                continue
            except MCUAPIError as error:
                self.stderr.write(self.style.ERROR(
                    f"{nombre}: fallo de MCU API: {error}"
                ))
                hubo_errores = True
                continue
            except Exception as error:  # no ocultar fallos inesperados
                self.stderr.write(self.style.ERROR(
                    f"{nombre}: error inesperado ({type(error).__name__}): {error}"
                ))
                hubo_errores = True
                continue

            self.stdout.write(self.style.SUCCESS(self._resumen(stats)))
            if stats['errores'] or stats['incompletos']:
                hubo_errores = True

        if hubo_errores:
            raise CommandError(
                'La sincronizacion termino con errores o registros incompletos. '
                'Revise la bitacora logs/callcentergamer.log para los detalles.'
            )
