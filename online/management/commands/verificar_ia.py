"""
Comando de diagnostico de la capa de IA.

Uso:
    python manage.py verificar_ia --solo-config   # solo muestra configuracion
    python manage.py verificar_ia                 # ademas hace una prueba real

Con --solo-config no se realiza ninguna llamada de red, por lo que sirve para
revisar el .env sin consumir la API. Sin el flag se prueba una consulta real y
la clasificacion de dos preguntas contra Groq, informando el origen y la
latencia. Si no hay clave o el proveedor falla, el comando termina con exit 1
para que el problema sea visible.
"""

import sys
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from online.ia_utils import MENSAJE_NO_DISPONIBLE, AsistenteIA


def enmascarar_clave(clave):
    """
    Muestra solo el prefijo y los ultimos caracteres de la clave.
    Nunca se imprime la clave completa en consola ni en logs.
    """
    if not clave:
        return '(sin clave)'
    if len(clave) <= 8:
        return '****'
    return f'{clave[:4]}****{clave[-3:]}'


def imprimible(texto):
    """
    Adapta el texto a la codificacion real de la consola.

    En Windows la consola suele usar cp1252 y el modelo puede devolver
    caracteres fuera de esa tabla, por ejemplo el guion no separable (U+2011).
    Sin esta conversion el comando terminaba con UnicodeEncodeError justo al
    imprimir una respuesta valida, que es un fallo del reporte y no de la IA.
    """
    texto = str(texto)
    codificacion = getattr(sys.stdout, 'encoding', None) or 'utf-8'
    try:
        return texto.encode(codificacion, 'replace').decode(codificacion)
    except LookupError:
        return texto.encode('ascii', 'replace').decode('ascii')


class Command(BaseCommand):
    help = (
        'Verifica la configuracion del asistente de IA y, opcionalmente, '
        'hace una consulta real de prueba.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--solo-config',
            action='store_true',
            help='Muestra la configuracion sin hacer llamadas de red.',
        )

    def handle(self, *args, **options):
        asistente = AsistenteIA()

        self.stdout.write('=== Configuracion de IA ===')
        self.stdout.write('Proveedor             : groq')
        self.stdout.write(f'Motor activo          : {asistente.motor_activo()}')
        self.stdout.write(f'Modelo                : {settings.IA_MODEL}')
        self.stdout.write(f'Base URL              : {settings.IA_BASE_URL}')
        self.stdout.write(f'Timeout (segundos)    : {settings.IA_TIMEOUT:g}')
        self.stdout.write(
            f'max_completion_tokens : {settings.IA_MAX_TOKENS}'
        )
        self.stdout.write(
            f'API key               : {enmascarar_clave(asistente.api_key)}'
        )

        if options['solo_config']:
            self.stdout.write('')
            self.stdout.write(
                'Modo --solo-config: no se realizaron llamadas de red.'
            )
            if not asistente.disponible():
                self.stdout.write(
                    'Aviso: no hay IA_API_KEY configurada; el asistente '
                    'mostrara un mensaje amable.'
                )
            return

        if not asistente.disponible():
            self.stderr.write(imprimible(
                'Resultado: no hay IA_API_KEY configurada. Define la clave en '
                '.env (https://console.groq.com) para que el asistente responda.'
            ))
            sys.exit(1)

        self.stdout.write('')
        self.stdout.write('=== Prueba de respuesta ===')
        consulta = '¿Cómo mejoro los FPS de mi juego?'
        inicio = time.perf_counter()
        respuesta = asistente.generar_respuesta_automatica(consulta)
        latencia_ms = (time.perf_counter() - inicio) * 1000
        error_respuesta = asistente.ultimo_error
        fallo_respuesta = bool(error_respuesta) or respuesta == MENSAJE_NO_DISPONIBLE

        self.stdout.write(f'Consulta   : {imprimible(consulta)}')
        self.stdout.write('Origen     : groq')
        self.stdout.write(f'Latencia   : {latencia_ms:.0f} ms')
        if error_respuesta:
            self.stdout.write(f'Error      : {imprimible(error_respuesta)}')
        self.stdout.write(f'Respuesta  : {imprimible(respuesta[:300])}')

        self.stdout.write('')
        self.stdout.write('=== Prueba de clasificacion ===')
        preguntas = ['No funciona el mouse', 'Tengo ping alto y lag']
        inicio = time.perf_counter()
        categorias = asistente.clasificar_preguntas(preguntas)
        latencia_ms = (time.perf_counter() - inicio) * 1000
        error_clasificacion = asistente.ultimo_error
        fallo_clasificacion = bool(error_clasificacion)

        for pregunta, categoria in zip(preguntas, categorias):
            self.stdout.write(f'- {imprimible(pregunta)} -> {categoria}')
        self.stdout.write('Origen     : groq')
        self.stdout.write(f'Latencia   : {latencia_ms:.0f} ms')
        if error_clasificacion:
            self.stdout.write(f'Error      : {imprimible(error_clasificacion)}')

        self.stdout.write('')
        if fallo_respuesta or fallo_clasificacion:
            motivo = error_respuesta or error_clasificacion or 'respuesta vacia'
            self.stderr.write(imprimible(
                'Resultado: el proveedor groq fallo '
                f'({motivo}); el asistente mostrara el mensaje de no disponible. '
                'Revisa logs/callcentergamer.log.'
            ))
            if 'Authentication' in motivo:
                self.stderr.write(
                    'La IA_API_KEY fue rechazada (HTTP 401). Genera una clave '
                    'nueva en https://console.groq.com y actualiza el archivo .env.'
                )
            sys.exit(1)

        self.stdout.write(
            f'Resultado: OK. El proveedor groq respondio '
            f'usando el modelo {settings.IA_MODEL}.'
        )
