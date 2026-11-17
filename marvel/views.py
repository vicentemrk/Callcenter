"""Vistas de solo lectura del catalogo Marvel.

Regla de la Fase B4: todas las vistas consultan UNICAMENTE la base de
datos local (ElementoCatalogo). Ninguna vista llama a MCU API durante la
navegacion, tal como exige la estrategia hibrida aprobada: una caida de
la API jamas afecta al catalogo ni al Call Center.

Los elementos inactivos (activo=False) no se muestran: responden 404 en
ambas vistas porque todavia no son parte del catalogo publico.
"""

from django.core.paginator import Paginator
from django.http import Http404
from django.shortcuts import get_object_or_404, render

from marvel.models import ElementoCatalogo

# Tamano de pagina del listado (paginacion estandar de Django).
ELEMENTOS_POR_PAGINA = 12

# Filtro de URL -> valor de tipo guardado en la base.
TIPOS_DE_URL = {
    'peliculas': 'movie',
    'series': 'tvshow',
}


def _parametros_consulta(request):
    """Construye la string de query preservando filtros en la paginacion.

    Copia q/tipo/fase del GET y descarta 'page', para que los links de
    paginacion no arrastren la pagina anterior. Devuelve '' o '&q=...&...'.
    """
    copia = request.GET.copy()
    copia.pop('page', None)
    return ''.join(
        f'&{clave}={valor}'
        for clave, valor in copia.items()
        if valor
    )


def Catalogo(request):
    """Listado del catalogo con busqueda, filtros y paginacion.

    GET admite: q (texto libre por nombre), tipo (peliculas|series),
    fase (nro) y page. Vacia el catálogo muestra un mensaje informativo;
    con filtros sin resultados, otro mensaje.
    """
    elementos = (
        ElementoCatalogo.objects
        .filter(activo=True)
        .order_by('tipo', 'nombre')
    )

    busqueda = str(request.GET.get('q', '')).strip()
    tipo = str(request.GET.get('tipo', '')).strip().lower()
    fase = str(request.GET.get('fase', '')).strip()

    if busqueda:
        elementos = elementos.filter(nombre__icontains=busqueda)
    if tipo in TIPOS_DE_URL:
        elementos = elementos.filter(tipo=TIPOS_DE_URL[tipo])
    if fase.isdigit():
        elementos = elementos.filter(fase=int(fase))

    paginador = Paginator(elementos, ELEMENTOS_POR_PAGINA)
    pagina = paginador.get_page(request.GET.get('page'))

    # Fases realmente presentes en el catalogo (para el <select>):
    # no se proponen fases que no existen en los datos.
    fases_disponibles = (
        ElementoCatalogo.objects
        .filter(activo=True)
        .exclude(fase__isnull=True)
        .order_by('fase')
        .values_list('fase', flat=True)
        .distinct()
    )

    return render(request, 'marvel/catalogo.html', {
        'pagina': pagina,
        'busqueda': busqueda,
        'tipo': tipo,
        'fase': fase,
        'fases_disponibles': fases_disponibles,
        'total_resultados': paginador.count,
        'hay_catalogo': ElementoCatalogo.objects.filter(activo=True).exists(),
        'parametros': _parametros_consulta(request),
    })


def _detalles_extra(elemento):
    """Lista de fichas etiqueta/valor para la plantilla de detalle.

    Extrae del JSON sincronizado SOLO claves verificadas de la API
    (Etapa 2); si la clave no existe o viene vacia, la ficha no se
    muestra: no se inventan datos. La duracion aplica a peliculas y los
    episodios a series.
    """
    json_api = elemento.datos_json or {}

    claves = {
        'movie': [('Dirección', 'directed_by'), ('Duración', 'duration')],
        'tvshow': [('Dirección', 'directed_by'), ('Temporadas', 'season'),
                   ('Episodios', 'number_episodes')],
    }[elemento.tipo]

    fichas = []
    for etiqueta, clave in claves:
        valor = _limpio(json_api.get(clave))
        if valor is not None:
            fichas.append({'etiqueta': etiqueta, 'valor': str(valor)})
    return fichas


_CONFIGURADO = {'movie', 'tvshow'}  # tipos del modelo


def _limpio(valor):
    """Normaliza cualquier dato de la API a texto util o None."""
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def Detalle(request, pk):
    """Ficha de detalle de un elemento activo.

    404 si no existe o si esta inactivo. Nulos mostrados como
    'Sin dato' en la plantilla; extras en fichas solo si la API
    efectivamente los entrego al sincronizar.
    """
    if pk < 1:
        raise Http404('Elemento inexistente.')

    elemento = get_object_or_404(
        ElementoCatalogo,
        pk=pk,
        activo=True,
    )
    if elemento.tipo not in _CONFIGURADO:
        # Blindaje: el tipo se guardo con choices, pero si la base se
        # tocara fuera de Django, la plantilla no debe romperse.
        raise Http404('Elemento de tipo desconocido.')

    return render(request, 'marvel/detalle.html', {
        'elemento': elemento,
        'fichas': _detalles_extra(elemento),
    })
