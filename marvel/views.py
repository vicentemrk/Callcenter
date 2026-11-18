"""Vistas del catalogo Marvel.

Regla de la Fase B4: todas las vistas consultan UNICAMENTE la base de
datos local (ElementoCatalogo). Ninguna vista llama a MCU API durante
la navegacion, tal como exige la estrategia hibrida aprobada: una
caida de la API jamas afecta al catalogo ni al Call Center.

Los elementos inactivos (activo=False) no se muestran: responden 404
en ambas vistas porque todavia no son parte del catalogo publico.

Bloque 5C: el Detalle acepta GET (publico) y POST (publicacion de
resenas, solo clientes autenticados). Las reseñas ocultas por
moderacion se filtran EN EL SERVIDOR segun el rol del solicitante.
"""

from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseForbidden
from django.db.models import Avg, Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from marvel.forms import ResenaForm
from marvel.models import ElementoCatalogo, Resena

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


def _detacados(tipo):
    """Elementos activos destacados de un tipo, para la landing Universo.

    Una sola consulta por tipo (solo columnas necesarias, ordenada por
    estreno descendente) con limite de 4 fichas. El catalogo vacio es
    un estado normal: la plantilla oculta la seccion correspondiente.
    """
    return (
        ElementoCatalogo.objects
        .filter(activo=True, tipo=tipo)
        .only('id', 'nombre', 'imagen', 'tipo', 'fase', 'fecha_estreno')
        .order_by('-fecha_estreno', 'nombre')[:4]
    )


def LandingUniverso(request):
    """Landing Universo Marvel (Bloque 4C), publica para cualquier rol.

    Presenta el universo Marvel y enlaza al catalogo (que sigue siendo
    la unica ruta de listado). Los destacados se leen de la base local
    con consultas eficientes; NINGUNA llamada a MCU API ocurre aqui.
    La galeria de personajes es 100% visual con recursos locales
    estaticos (no hay registros de personajes desde el Bloque 1).
    """
    return render(request, 'marvel/universo.html', {
        'peliculas_destacadas': _detacados('movie'),
        'series_destacadas': _detacados('tvshow'),
        'total_peliculas': ElementoCatalogo.objects.filter(
            activo=True, tipo='movie').count(),
        'total_series': ElementoCatalogo.objects.filter(
            activo=True, tipo='tvshow').count(),
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


def _resenas_para(elemento, usuario):
    """Reseñas del elemento que el solicitante puede ver (Bloque 5C).

    Filtrado EN EL SERVIDOR, no con CSS:
    - visitante y tecnico: SOLO las visibles;
    - cliente: las visibles + la suya propia (aunque este oculta, la
      ve con la etiqueta "Oculta por moderación");
    - administrador: todas (necesita verlas para moderar en 5D).
    Con select_related('usuario') el listado NO genera N+1.
    """
    resenas = elemento.resenas.select_related('usuario')

    if not usuario.is_authenticated:
        return resenas.filter(visible=True)
    if usuario.rol == 'administrador':
        return resenas
    if usuario.rol == 'cliente':
        return resenas.filter(Q(visible=True) | Q(usuario=usuario))
    return resenas.filter(visible=True)  # tecnico


def Detalle(request, pk):
    """Ficha de detalle de un elemento activo, con reseñas (5C).

    404 si no existe o si esta inactivo. GET es publico; POST publica
    una reseña SOLO para clientes autenticados (visitante -> login,
    tecnico/admin -> 403). El autor, el elemento y el estado visible
    se asignan en el servidor: el POST no puede suplantarlos.
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

    usuario = request.user
    form = None

    if request.method == 'POST':
        if not usuario.is_authenticated:
            # El visitante que intenta publicar va al login.
            return redirect(f"{reverse('Login')}?next={request.path}")
        if usuario.rol != 'cliente':
            # Tecnico y administrador no publican reseñas.
            return HttpResponseForbidden(
                'Solo los clientes pueden publicar reseñas.'
            )

        form = ResenaForm(request.POST)
        if form.is_valid():
            # Unicidad pre-chequeada y re-chequeada por la base dentro
            # de la transaccion (duplicados por doble envio).
            ya_publicada = Resena.objects.filter(
                elemento=elemento, usuario=usuario,
            ).exists()
            if ya_publicada:
                form.add_error(
                    None,
                    'Ya publicaste una reseña de este título.',
                )
            else:
                try:
                    with transaction.atomic():
                        Resena.objects.create(
                            elemento=elemento,
                            usuario=usuario,
                            visible=True,  # sin cola de aprobacion (5A)
                            **form.cleaned_data,
                        )
                except IntegrityError:
                    form.add_error(
                        None,
                        'Ya publicaste una reseña de este título.',
                    )
                else:
                    # POST-redirect-GET: evita reenvios al actualizar.
                    return redirect(
                        f"{reverse('marvel:detalle', args=[elemento.pk])}"
                        '?resena=publicada#resenas'
                    )

    contexto = {
        'elemento': elemento,
        'fichas': _detalles_extra(elemento),
        'resenas': _resenas_para(elemento, usuario),
        'calificaciones': [1, 2, 3, 4, 5],
        # Banner de exito tras el PRG (?resena=publicada).
        'resena_publicada': request.GET.get('resena') == 'publicada',
        # Banners de moderacion (Bloque 5D).
        'resena_ocultada': request.GET.get('resena') == 'ocultada',
        'resena_restaurada': request.GET.get('resena') == 'restaurada',
    }

    # Promedio y cantidad SOLO de reseñas visibles (Bloque 5D): una
    # consulta con aggregate, sin N+1, sin reseñas de otros elementos.
    # El promedio vive exclusivamente en la ficha de detalle.
    estadisticas = elemento.resenas.filter(visible=True).aggregate(
        promedio=Avg('calificacion'),
        total=Count('pk'),
    )
    contexto['promedio'] = estadisticas['promedio']
    contexto['total_resenas_visibles'] = estadisticas['total']

    if usuario.is_authenticated and usuario.rol == 'cliente':
        ya_resenada = Resena.objects.filter(
            elemento=elemento, usuario=usuario,
        ).exists()
        contexto['ya_resenada'] = ya_resenada
        if not ya_resenada and form is None:
            form = ResenaForm()
    contexto['form'] = form

    return render(request, 'marvel/detalle.html', contexto)


_ACCIONES_MODERACION = {'ocultar': False, 'restaurar': True}


@require_POST
def ModerarResena(request, pk, resena_id, accion):
    """Moderacion de una reseña: ocultar/restaurar (Bloque 5D).

    - SOLO POST (require_POST: un GET responde 405) y SOLO
      administrador autenticado (visitante -> login; tecnico/cliente
      -> 403, incluso el cliente dueño de la reseña).
    - La accion vive en la RUTA (no en un parametro libre del
      cliente); solo se aceptan ocultar/restaurar.
    - La reseña debe pertenecer al elemento de la ruta: otro id
      responde 404 sin revelar informacion de elementos ajenos.
    - SOLO cambia visible: calificacion, referencia_tematica, autor y
      elemento NUNCA se modifican (no hay edicion ni eliminacion).
    """
    if accion not in _ACCIONES_MODERACION:
        # Defensivo: solo llega si las rutas cambian a futuro.
        raise Http404('Accion de moderacion inexistente.')

    usuario = request.user
    if not usuario.is_authenticated:
        return redirect(f"{reverse('Login')}?next={request.path}")
    if usuario.rol != 'administrador':
        return HttpResponseForbidden(
            'Solo los administradores pueden moderar reseñas.'
        )

    if pk < 1 or resena_id < 1:
        raise Http404('Reseña inexistente.')

    elemento = get_object_or_404(ElementoCatalogo, pk=pk, activo=True)
    if elemento.tipo not in _CONFIGURADO:
        raise Http404('Elemento de tipo desconocido.')

    resena = get_object_or_404(Resena, pk=resena_id, elemento=elemento)

    resena.visible = _ACCIONES_MODERACION[accion]
    resena.save(update_fields=['visible'])

    # POST-redirect-GET con ancla a la seccion de reseñas.
    return redirect(
        f"{reverse('marvel:detalle', args=[elemento.pk])}"
        f"?resena={'ocultada' if not resena.visible else 'restaurada'}"
        '#resenas'
    )
