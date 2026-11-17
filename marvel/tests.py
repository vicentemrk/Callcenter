"""Pruebas de la sincronizacion del catalogo (Fase B3) y de las vistas
del catalogo visual (Fase B4).

Cubren el mapeo y el almacenamiento idempotente usando respuestas
simuladas de MCU API (sin llamadas de red y sin tocar la base real:
los TestCase de Django corren sobre una base de prueba transitoria).

Estructura simulada de cada "pagina": igual al envelope real de la API
({"data": [...], "total": N, "page": 1, "limit": 10, "_links": {...}}).
"""

from datetime import date

from django.test import TestCase
from django.urls import reverse

from marvel import services
from marvel.mcu_client import MCUAPIInvalidResponse
from marvel.models import ElementoCatalogo

ACUMULADOR_NULO = None  # referencia legible para valores ausentes


def envelope(pagina, total=8, con_next=False):
    """Construye un envelope de listado igual al de la API real."""
    return {
        'data': pagina,
        'total': total,
        'page': 1,
        'limit': 10,
        '_links': {
            'self': {'href': 'https://simulado/self'},
            'first': {'href': 'https://simulado/first'},
            **({'next': {'href': 'https://simulado/next'}} if con_next else {}),
        },
    }


def registro_pelicula(id, titulo):
    """Registro de pelicula con los campos opcionales vacios."""
    return {
        'id': id,
        'title': titulo,
        'overview': None,
        'cover_url': None,
        'release_date': None,
        'phase': None,
        'saga': None,
    }


class ClienteSimulado:
    """Imita los metodos de lectura de MCUAPIClient sin red."""

    def __init__(self, paginas_por_metodo):
        # {nombre_metodo: [envelope_pagina1, envelope_pagina2, ...]}
        self.envelopes = paginas_por_metodo
        self.llamadas = []

    def _responder(self, metodo, page, limit):
        self.llamadas.append((metodo, page, limit))
        paginas = self.envelopes[metodo]
        if page > len(paginas):
            raise MCUAPIInvalidResponse('pagina fuera del simulador: %s' % page)
        return paginas[page - 1]

    def obtener_peliculas(self, page=1, limit=10, filtros=None):
        return self._responder('obtener_peliculas', page, limit)

    def obtener_series(self, page=1, limit=10, filtros=None):
        return self._responder('obtener_series', page, limit)


class PruebaMapeo(TestCase):
    """mapear_elemento traduce el JSON de la API por tipo de contenido."""

    def test_mapear_pelicula_completa(self):
        registro = {
            'id': 1,
            'title': 'Iron Man',
            'overview': 'Tony Stark construye el traje.',
            'cover_url': 'https://ejemplo/img.jpg',
            'release_date': '2008-05-02',
            'phase': 1,
            'saga': 'Infinity Saga',
            'box_office': '585171547',  # no mapea a columna; queda en datos_json
        }
        datos = services.mapear_elemento('movie', registro)
        self.assertEqual(datos, {
            'mcu_id': 1,
            'nombre': 'Iron Man',
            'descripcion': 'Tony Stark construye el traje.',
            'imagen': 'https://ejemplo/img.jpg',
            'fecha_estreno': date(2008, 5, 2),
            'fase': 1,
            'saga': 'Infinity Saga',
        })

    def test_mapear_registro_de_personaje_queda_incompleto(self):
        """Un registro de personaje ya no entra: no tiene 'title' y se descarta."""
        registro = {
            'id': 1,
            'name': 'Tony Stark',
            'alias': 'Iron Man',
            'description': 'Bilionario genio.',
            'image_url': 'https://ejemplo/tony.jpg',
        }
        datos = services.mapear_elemento('character', registro)
        self.assertIsNone(datos['nombre'])
        self.assertIsNone(datos['descripcion'])

        estado = services.guardar_elemento('character', registro, services._ahora())
        self.assertEqual(estado, services.ESTADO_INCOMPLETO)
        self.assertEqual(ElementoCatalogo.objects.count(), 0)


class PruebaGuardarElemento(TestCase):
    """guardar_elemento: upsert idempotente por tipo+mcu_id."""

    def registro(self):
        return {
            'id': 1,
            'title': 'Iron Man',
            'overview': 'Primer traje.',
            'cover_url': 'https://ejemplo/1.jpg',
            'release_date': '2008-05-02',
            'phase': 1,
            'saga': 'Infinity Saga',
        }

    def test_crea_luego_sin_cambios(self):
        self.assertEqual(
            services.guardar_elemento('movie', self.registro(), services._ahora()),
            services.ESTADO_CREADO,
        )

        # Repeticion con el mismo JSON: sin cambios y sin regrabacion
        # (sincronizado_en debe mantenerse del primer guardado).
        estado_2 = services.guardar_elemento('movie', self.registro(), services._ahora())
        registrados = ElementoCatalogo.objects.filter(tipo='movie', mcu_id=1)
        fecha_guardada = registrados.first().sincronizado_en

        self.assertEqual(estado_2, services.ESTADO_SIN_CAMBIOS)
        self.assertEqual(registrados.count(), 1)

        services.guardar_elemento('movie', self.registro(), services._ahora())
        self.assertEqual(registrados.first().sincronizado_en, fecha_guardada)

class PruebaSincronizarTipo(TestCase):
    """sincronizar_tipo: paginacion, limite e idempotencia al repetir."""

    def cliente(self, paginas_peliculas):
        return ClienteSimulado({'obtener_peliculas': paginas_peliculas})

    def test_sincroniza_toda_la_pagina_sin_limite(self):
        cliente = self.cliente([
            envelope([registro_pelicula(i, f'Titulo {i}') for i in range(1, 5)], total=4),
        ])
        stats = services.sincronizar_tipo('movie', cliente=cliente)

        self.assertEqual(stats, {
            'tipo': 'movie',
            'procesados': 4,
            'creados': 4,
            'actualizados': 0,
            'sin_cambios': 0,
            'incompletos': 0,
            'errores': 0,
            'paginas': 1,
            'total_api': 4,
            'acotado': False,
        })
        self.assertEqual(ElementoCatalogo.objects.filter(tipo='movie').count(), 4)

    def test_repetir_no_duplica(self):
        registros = [registro_pelicula(i, f'Titulo {i}') for i in range(1, 5)]
        cliente = self.cliente([envelope(registros, total=8, con_next=True),
                                envelope([], total=8)])

        stats_1 = services.sincronizar_tipo('movie', cliente=cliente)
        stats_2 = services.sincronizar_tipo('movie', cliente=cliente)

        self.assertEqual(stats_1['creados'], 4)
        self.assertEqual(stats_2['creados'], 0)
        self.assertEqual(stats_2['sin_cambios'], 4)
        self.assertEqual(stats_2['actualizados'], 0)
        # Tambien cubre el guard: la segunda pagina (vacia con next)
        # no debe dejar el ciclo girando indefinidamente.
        self.assertEqual(ElementoCatalogo.objects.count(), 4)

class PruebaCatalogoVistas(TestCase):
    """Vistas del catalogo visual (Fase B4), siempre contra la base local."""

    def crear(self, tipo, mcu_id, nombre, activo=True, con_imagen=False,
              fase=None, descripcion=None):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            imagen='https://ejemplo/img.jpg' if con_imagen else None,
            fase=fase,
            descripcion=descripcion,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def test_catalogo_publico_sin_login(self):
        respuesta = self.client.get('/marvel/')
        self.assertEqual(respuesta.status_code, 200)
        # El header compartido debe mostrar el enlace al catalogo.
        self.assertContains(respuesta, 'Catálogo Marvel')

    def test_listado_solo_activos(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('tvshow', 1, 'WandaVision')
        self.crear('movie', 2, 'Retirado', activo=False)

        respuesta = self.client.get('/marvel/')
        nombres = [e.nombre for e in respuesta.context['pagina'].object_list]
        self.assertEqual(set(nombres), {'Iron Man', 'WandaVision'})
        self.assertFalse(respuesta.context['hay_catalogo'] is False)

    def test_busqueda_por_nombre(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('movie', 2, 'Iron Man 2')
        self.crear('tvshow', 1, 'Loki')

        respuesta = self.client.get('/marvel/', {'q': 'iron man'})
        nombres = [e.nombre for e in respuesta.context['pagina'].object_list]
        self.assertEqual(set(nombres), {'Iron Man', 'Iron Man 2'})
        self.assertEqual(respuesta.context['total_resultados'], 2)

    def test_detalle_completo(self):
        elemento = self.crear(
            'movie', 1, 'Iron Man',
            con_imagen=True,
            fase=1,
            descripcion='Tony Stark construye el traje.',
        )
        respuesta = self.client.get(f'/marvel/{elemento.pk}/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Iron Man')
        self.assertContains(respuesta, 'Tony Stark construye el traje.')
        self.assertContains(respuesta, 'Fase 1')
        # informacion extra del JSON sincronizado (string de la duracion)
        guardado = ElementoCatalogo.objects.get(pk=elemento.pk)
        guardado.datos_json = {**guardado.datos_json, 'duration': 126}
        guardado.save()
        respuesta = self.client.get(f'/marvel/{elemento.pk}/')
        self.assertContains(respuesta, '126')

    def test_detalle_inexistente_y_no_activo(self):
        respuesta = self.client.get('/marvel/7777/')
        self.assertEqual(respuesta.status_code, 404)

        inactivo = self.crear('movie', 5, 'Elemento retirado', activo=False)
        respuesta = self.client.get(f'/marvel/{inactivo.pk}/')
        self.assertEqual(respuesta.status_code, 404)


class ConsultaDesdeFichaTests(TestCase):
    """Fase C1.4: crear consultas desde la ficha del catalogo.

    Reutiliza la preseleccion ?elemento= de C1.2 (vista Inicio); aqui
    solo se prueba el enlace de la ficha y el comportamiento por rol.
    """

    def setUp(self):
        self.elemento = ElementoCatalogo.objects.create(
            mcu_id=400,
            tipo='movie',
            nombre='Superman',
            activo=True,
        )
        self.cliente = self._crear_usuario('cliente-c14', rol='cliente')
        self.tecnico = self._crear_usuario('tecnico-c14', rol='tecnico')
        self.admin = self._crear_usuario('admin-c14', rol='administrador')

    def _crear_usuario(self, username, rol):
        from online.models import Usuario

        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def _ruta_inicio_con_elemento(self, usuario, elemento):
        return (
            reverse('inicio', args=[usuario.id])
            + f'?elemento={elemento.pk}'
        )

    def test_boton_visible_para_cliente_autenticado(self):
        self.client.force_login(self.cliente)

        respuesta = self.client.get(f'/marvel/{self.elemento.pk}/')

        self.assertEqual(respuesta.status_code, 200)
        contenido = respuesta.content.decode('utf-8')
        self.assertIn('Crear consulta sobre este elemento', contenido)
        self.assertIn(
            self._ruta_inicio_con_elemento(self.cliente, self.elemento),
            contenido,
        )

