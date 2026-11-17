"""Servicios de sincronizacion del catalogo MCU hacia la base local.

Estrategia hibrida aprobada (Etapa 2): MCU API es la fuente de datos;
la base local es la fuente de lectura del sistema. Este modulo solo
escribe en marvel.models y NUNCA elimina ni desactiva registros: la
desactivacion de elementos ausentes de la API no esta implementada
en la Fase B3 y quedo sujeta a autorizacion explicita.

La sincronizacion es idempotente: identifica cada elemento por
(tipo, mcu_id) y usa la comparacion campo a campo (equivale a
update_or_create) para no volver a grabar registros que no cambiaron,
con estadisticas separadas de creado/actualizado/sin_cambios para el
comando.
"""

import logging
from datetime import datetime

from django.db import IntegrityError
from django.utils import timezone

from marvel.models import ElementoCatalogo

logger = logging.getLogger('marvel')

# Tipo interno -> nombre del metodo de lectura de MCUAPIClient.
METODOS_API = {
    'movie': 'obtener_peliculas',
    'tvshow': 'obtener_series',
    'character': 'obtener_personajes',
}

# Estados posibles de guardar_elemento, reportados por el comando.
ESTADO_CREADO = 'creado'
ESTADO_ACTUALIZADO = 'actualizado'
ESTADO_SIN_CAMBIOS = 'sin_cambios'
ESTADO_INCOMPLETO = 'incompleto'
ESTADO_ERROR = 'error'


def _ahora():
    """Momento de sincronizacion que se marca en los registros tocados."""
    return timezone.now()


def _texto(valor):
    """Normaliza a texto limpio o None; los vacios cuentan como sin dato."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _fecha(valor):
    """Convierte 'YYYY-MM-DD' a date; None si falta o es invalida.

    La API verificada usa el formato '2008-05-02'. Un formato inesperado
    no interrumpe la sincronizacion: se avisa en el log y queda sin dato.
    """
    texto = _texto(valor)
    if not texto:
        return None
    try:
        return datetime.strptime(texto, '%Y-%m-%d').date()
    except ValueError:
        logger.warning('Fecha no reconocida: %r', texto)
        return None


def _fase(valor):
    """Convierte la fase a entero no negativo, o None (characters no tienen)."""
    if valor is None:
        return None
    try:
        fase = int(valor)
    except (TypeError, ValueError):
        logger.warning('Fase no reconocida: %r', valor)
        return None
    return fase if fase >= 0 else None


def mapear_elemento(tipo, registro):
    """Traduce un registro JSON de la API a campos de ElementoCatalogo.

    Claves distintas por tipo (verificado en Etapa 2 con responses reales):
    - movie/tvshow: title, overview, cover_url, release_date, phase, saga.
    - character: name, description, image_url (sin fecha/fase/saga).
    Los campos ausentes o nulos quedan en None; el JSON original se
    conserva entero en datos_json para no perder informacion.
    """
    if tipo == 'character':
        nombre = _texto(registro.get('name'))
        descripcion = _texto(registro.get('description'))
        imagen = _texto(registro.get('image_url'))
        fecha_estreno = None
        fase = None
        saga = None
    else:
        nombre = _texto(registro.get('title'))
        descripcion = _texto(registro.get('overview'))
        imagen = _texto(registro.get('cover_url'))
        fecha_estreno = _fecha(registro.get('release_date'))
        fase = _fase(registro.get('phase'))
        saga = _texto(registro.get('saga'))

    return {
        'mcu_id': registro.get('id'),
        'nombre': nombre,
        'descripcion': descripcion,
        'imagen': imagen,
        'fecha_estreno': fecha_estreno,
        'fase': fase,
        'saga': saga,
    }


def guardar_elemento(tipo, registro, sincronizado_en, comparar_json=True):
    """Guarda (crea o actualiza) un elemento identificado por tipo+mcu_id.

    Devuelve uno de los ESTADO_* descritos arriba:
    - ESTADO_CREADO: el elemento no existia y se creo completo.
    - ESTADO_ACTUALIZADO: existia y al menos un campo cambio.
    - ESTADO_SIN_CAMBIOS: existia y nada cambio; NO se re-graba (asi
      sincronizar dos veces seguidas devuelve sin_cambios x N).
    - ESTADO_INCOMPLETO: registro sin mcu_id valido o sin nombre.
    - ESTADO_ERROR: fallo de escritura, ya registrado en el log.

    ``comparar_json=False`` (solo pruebas) ignora datos_json al comparar.
    Nunca elimina registros.
    """
    datos = mapear_elemento(tipo, registro)

    mcu_id_crudo = datos.pop('mcu_id')
    try:
        mcu_id = int(mcu_id_crudo)
        if mcu_id < 1:
            raise ValueError
    except (TypeError, ValueError):
        logger.error('Registro de tipo %s sin mcu_id valido: %r', tipo, mcu_id_crudo)
        return ESTADO_INCOMPLETO

    if not datos['nombre']:
        logger.error('Registro %s/%s sin nombre util', tipo, mcu_id)
        return ESTADO_INCOMPLETO

    try:
        existente = ElementoCatalogo.objects.get(tipo=tipo, mcu_id=mcu_id)
    except ElementoCatalogo.DoesNotExist:
        existente = None

    if existente is None:
        try:
            ElementoCatalogo.objects.create(
                tipo=tipo,
                mcu_id=mcu_id,
                **datos,
                datos_json=registro,
                sincronizado_en=sincronizado_en,
            )
        except (IntegrityError, ValueError) as error:
            logger.error('No se pudo crear %s/%s: %s', tipo, mcu_id, error)
            return ESTADO_ERROR
        return ESTADO_CREADO

    # Comparacion: los campos mapeados contra lo guardado, y el JSON
    # original contra datos_json (si el API cambia un campo que no
    # mapeamos a columna, igual detectamos el cambio por el JSON).
    cambio_json = comparar_json and (existente.datos_json != registro)
    campos_cambiados = [
        campo
        for campo, valor in datos.items()
        if getattr(existente, campo) != valor
    ]

    if not campos_cambiados and not cambio_json:
        return ESTADO_SIN_CAMBIOS

    for campo in campos_cambiados:
        setattr(existente, campo, datos[campo])
    existente.datos_json = registro
    existente.sincronizado_en = sincronizado_en
    try:
        existente.save()
    except (IntegrityError, ValueError) as error:
        logger.error('No se pudo actualizar %s/%s: %s', tipo, mcu_id, error)
        return ESTADO_ERROR
    return ESTADO_ACTUALIZADO


def sincronizar_tipo(tipo, limite=None, tamano_pagina=10, cliente=None):
    """Recorre la API paginada hasta agotar paginas o llegar al limite.

    Devuelve un diccionario de estadisticas:
    {tipo, procesados, creados, actualizados, sin_cambios, incompletos,
     errores, paginas, total_api, acotado}
    ``acotado`` True significa que se detuvo por el limite declarado
    (sincronizacion parcial), no porque la API se agotara.

    ``cliente`` permite inyectar un cliente simulado en las pruebas
    (elimina la dependencia de la red en unitarias).
    """
    from marvel.mcu_client import MCUAPIClient

    cliente = cliente or MCUAPIClient()
    metodo = getattr(cliente, METODOS_API[tipo])

    stats = {
        'tipo': tipo,
        'procesados': 0,
        'creados': 0,
        'actualizados': 0,
        'sin_cambios': 0,
        'incompletos': 0,
        'errores': 0,
        'paginas': 0,
        'total_api': 0,
        'acotado': False,
    }
    ahora = _ahora()

    pagina = 1
    while True:
        envelope = metodo(page=pagina, limit=tamano_pagina)
        stats['paginas'] += 1
        stats['total_api'] = envelope.get('total', stats['total_api'])
        registros = envelope.get('data') or []
        enlaces = envelope.get('_links') or {}

        # Salvaguarda anti-ciclos: la API anuncio que hay mas paginas pero
        # devolvio datos vacios; cortar para no girar indefinidamente.
        if not registros:
            if 'next' in enlaces:
                logger.warning(
                    '%s: la API anuncio next pero pagina %s llego vacia.',
                    tipo, pagina,
                )
            break

        for registro in registros:
            if limite is not None and stats['procesados'] >= limite:
                stats['acotado'] = True
                return stats

            stats['procesados'] += 1
            estado = guardar_elemento(tipo, registro, ahora)
            if estado == ESTADO_CREADO:
                stats['creados'] += 1
            elif estado == ESTADO_ACTUALIZADO:
                stats['actualizados'] += 1
            elif estado == ESTADO_SIN_CAMBIOS:
                stats['sin_cambios'] += 1
            elif estado == ESTADO_INCOMPLETO:
                stats['incompletos'] += 1
            else:
                stats['errores'] += 1

        if 'next' not in enlaces:
            break
        pagina += 1

    return stats


def sincronizar_catalogo(tipos, limite=None, tamano_pagina=10, cliente=None):
    """Sincroniza varios tipos en orden y devuelve la lista de estadisticas."""
    return [
        sincronizar_tipo(tipo, limite=limite, tamano_pagina=tamano_pagina, cliente=cliente)
        for tipo in tipos
    ]
