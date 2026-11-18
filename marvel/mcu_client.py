"""Cliente HTTP de solo lectura para MCU API.

URL base documentada y verificada:
https://mcuapi.up.railway.app/api/v1

Diseno tolerante a fallos (mismo estilo que online/ia_utils.py):
- Nunca escribe en la base de datos ni toca el sistema de tickets.
- Los errores externos se envuelven en excepciones propias de este modulo,
  nunca se propagan los stack traces de transporte.
- Timeout explicito y reintentos limitados (sin ciclos indefinidos).
- Solo GET: la API es de lectura (todo endpoint es GET segun su README).

Lectura: urllib.request de la libreria estandar, para no agregar
dependencias nuevas al proyecto.

Limites recordados de la API (Etapa 2, verificados con el README real):
- Rate limit: 100 requests por minuto por IP (429 al excederlo).
- Errores en application/problem+json con detail descriptivo.
- Paginacion: page/limit, limit maximo 100.
"""

import json
import logging
import socket
import time
import urllib.error
import urllib.parse
import urllib.request

from marvel.constants import MCUAPI_BASE_URL

logger = logging.getLogger('marvel')

# Parametros de transporte. Si MCU API cae, no bloquear el sistema:
# 10 segundos por intento y 1 reintento con pausa corta.
DEFAULT_TIMEOUT = 10.0
DEFAULT_REINTENTOS = 1
PAUSA_REINTENTO = 1.0
LIMIT_MAXIMO = 100


class MCUAPIError(Exception):
    """Error base de MCU API. Cualquier fallo externo se traduce a una
    subclase de esta excepcion."""


class MCUAPITimeoutError(MCUAPIError):
    """Timeout alcanzado en todos los intentos."""


class MCUAPIConnectionError(MCUAPIError):
    """No fue posible conectar (DNS no resuelto, conexion rechazada, red cortada)."""


class MCUAPIInvalidResponse(MCUAPIError):
    """Respuesta no parseable como JSON o con formato inesperado."""


class MCUAPIBadRequest(MCUAPIError):
    """HTTP 400: parametros invalidos (la API no coacciona valores)."""


class MCUAPINotFound(MCUAPIError):
    """HTTP 404: el identificador no existe en la API."""


class MCUAPIRateLimitError(MCUAPIError):
    """HTTP 429: el limite de 100 requests/minuto por IP fue excedido."""


class MCUAPIServerError(MCUAPIError):
    """HTTP 500 o cualquier otro 5xx persistente."""


# Mapeo de codigos HTTP conocidos a excepciones de este modulo.
ERRORES_HTTP = {
    400: MCUAPIBadRequest,
    404: MCUAPINotFound,
    429: MCUAPIRateLimitError,
}


class MCUAPIClient:
    """Cliente HTTP GET para MCU API. Pensado para ser reutilizado por el
    proceso de sincronizacion de la Fase B3 (aun no implementado).
    """

    def __init__(
        self,
        base_url=None,
        timeout=DEFAULT_TIMEOUT,
        reintentos=DEFAULT_REINTENTOS,
    ):
        self.base_url = str(base_url or MCUAPI_BASE_URL).rstrip('/')
        self.timeout = float(timeout)
        self.reintentos = max(0, int(reintentos))

    # ------------------------------------------------------------------
    # Transporte
    # ------------------------------------------------------------------
    def _construir_url(self, ruta, parametros=None):
        url = f'{self.base_url}/{str(ruta).lstrip("/")}'

        if parametros:
            url = f'{url}?{urllib.parse.urlencode(parametros)}'
        return url

    def _url_host(self):
        """Host de la API (para /health, que vive fuera de /api/v1)."""
        partes = urllib.parse.urlsplit(self.base_url)
        return f'{partes.scheme}://{partes.netloc}'

    def _leer_error(self, http_error):
        """Extrae el mensaje del cuerpo application/problem+json.

        Devuelve texto amable; nunca propaga el formato bruto si la API
        no envio JSON (puede tratarse de un 502 de proxy).
        """
        try:
            cuerpo = http_error.read().decode('utf-8')
            problema = json.loads(cuerpo)
            detalle = str(problema.get('detail', '')).strip()
            if detalle:
                return detalle
        except (UnicodeDecodeError, json.JSONDecodeError, AttributeError, OSError):
            pass

        return f'La API respondio HTTP {http_error.code}.'

    def _solicitud(self, url):
        """Ejecuta un GET con timeout y reintentos limitados.

        Devuelve el JSON parseado (dict o list) o lanza una excepcion de
        este modulo. El ciclo tiene tope: reintentos + 1 intentos en total,
        sin backoff exponencial ni ciclos indefinidos. Los 400/404/429 no
        se reintentan (400 significa parametros invalidos y repetir un 429
        empeoraria el rate limiting).
        """
        ultima_excepcion = None

        for intento in range(self.reintentos + 1):
            if intento:
                time.sleep(PAUSA_REINTENTO)

            request = urllib.request.Request(
                url,
                method='GET',
                headers={
                    'Accept': 'application/json',
                    'User-Agent': 'CallCenterGamer/0.1 (Django)',
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as respuesta:
                    cuerpo = respuesta.read().decode('utf-8')
                return json.loads(cuerpo)

            except socket.timeout:
                ultima_excepcion = MCUAPITimeoutError(
                    f'Timeout tras {self.timeout} segundos solicitando {url}.'
                )
                logger.warning('MCU API timeout (intento %s): %s', intento + 1, url)

            except urllib.error.HTTPError as error:
                detalle = self._leer_error(error)
                clase = ERRORES_HTTP.get(error.code, MCUAPIServerError)
                excepcion = clase(detalle)

                if 500 <= error.code < 600 and intento < self.reintentos:
                    ultima_excepcion = excepcion
                    logger.warning(
                        'MCU API no respondio (intento %s): HTTP %s en %s',
                        intento + 1, error.code, url,
                    )
                    continue

                raise excepcion

            except urllib.error.URLError as error:
                causa = getattr(error, 'reason', error)
                if isinstance(causa, socket.timeout):
                    ultima_excepcion = MCUAPITimeoutError(
                        f'Timeout tras {self.timeout} segundos solicitando {url}.'
                    )
                    logger.warning('MCU API timeout (intento %s): %s', intento + 1, url)
                else:
                    ultima_excepcion = MCUAPIConnectionError(
                        f'No se pudo conectar con {url}: {causa}.'
                    )
                    logger.warning(
                        'MCU API sin conexion (intento %s): %s', intento + 1, url
                    )

            except (UnicodeDecodeError, json.JSONDecodeError):
                raise MCUAPIInvalidResponse(
                    f'La respuesta de {url} no es JSON valido.'
                )

            except OSError as error:
                ultima_excepcion = MCUAPIConnectionError(
                    f'Error de red solicitando {url}: {error}.'
                )
                logger.warning(
                    'MCU API error de red (intento %s): %s', intento + 1, url
                )

        raise ultima_excepcion

    # ------------------------------------------------------------------
    # Validacion de formatos (respuestas inesperadas)
    # ------------------------------------------------------------------
    @staticmethod
    def _requiere_envelope(datos, url):
        """Los endpoints de listado devuelven {'data': [...], 'total', ...}."""
        if not isinstance(datos, dict) or not isinstance(datos.get('data'), list):
            raise MCUAPIInvalidResponse(
                f'Formato inesperado en listado de {url}.'
            )
        return datos

    @staticmethod
    def _requiere_detalle(datos, url):
        """Los endpoints de detalle devuelven un dict con 'id'."""
        if not isinstance(datos, dict) or 'id' not in datos:
            raise MCUAPIInvalidResponse(
                f'Formato inesperado en detalle de {url}.'
            )
        return datos

    # ------------------------------------------------------------------
    # Endpoints publicos (todos confirmados en Etapa 2)
    # ------------------------------------------------------------------
    def _listar(self, ruta, page, limit, filtros):
        if page < 1 or not 1 <= int(limit) <= LIMIT_MAXIMO:
            raise MCUAPIBadRequest(
                'page debe ser >= 1 y limit entre 1 y '
                f'{LIMIT_MAXIMO}.'
            )
        parametros = {'page': int(page), 'limit': int(limit)}
        parametros.update(filtros or {})
        url = self._construir_url(ruta, parametros)
        datos = self._solicitud(url)
        return self._requiere_envelope(datos, url)

    def _obtener(self, ruta, mcu_id):
        try:
            identificador = int(mcu_id)
        except (TypeError, ValueError):
            raise MCUAPIBadRequest(f'Identificador invalido: {mcu_id!r}.')
        url = self._construir_url(f'{ruta}/{identificador}')
        datos = self._solicitud(url)
        return self._requiere_detalle(datos, url)

    def estado(self):
        """GET /health (documentado: vive en el host, fuera de /api/v1).

        Devuelve un dict similar a {"status": "ok", "version": "3.0.0",
        "uptime": <int>, "database": "up"}. Al venir como dict completo,
        no se valida la forma interna.
        """
        url = f'{self._url_host()}/health'
        datos = self._solicitud(url)

        if not isinstance(datos, dict):
            raise MCUAPIInvalidResponse(
                f'Formato inesperado en health: {datos!r}.'
            )
        return datos

    def obtener_peliculas(self, page=1, limit=10, filtros=None):
        """GET /movies con paginacion."""
        return self._listar('movies', page=page, limit=limit, filtros=filtros)

    def obtener_series(self, page=1, limit=10, filtros=None):
        """GET /tvshows con paginacion."""
        return self._listar('tvshows', page=page, limit=limit, filtros=filtros)

    def obtener_pelicula(self, mcu_id):
        """GET /movies/{id}."""
        return self._obtener('movies', mcu_id)

    def obtener_serie(self, mcu_id):
        """GET /tvshows/{id}."""
        return self._obtener('tvshows', mcu_id)

    def buscar(self, termino, tipo=None, page=1, limit=10):
        """GET /search?q= (busqueda tolerante a typos).

        ``tipo`` puede ser 'movie' o 'tvshow' y unifica con el parametro
        ``type`` de la API; se ignora fuera de esos valores validos para
        no generar un 400.
        """
        if not str(termino or '').strip():
            raise MCUAPIBadRequest('El termino de busqueda no puede ser vacio.')

        parametros = {'q': str(termino).strip()}
        if tipo in ('movie', 'tvshow'):
            parametros['type'] = tipo
        return self._listar('search', page=page, limit=limit, filtros=parametros)
