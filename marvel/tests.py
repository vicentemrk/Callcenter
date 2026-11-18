"""Pruebas de la sincronizacion del catalogo (Fase B3) y de las vistas
del catalogo visual (Fase B4).

Cubren el mapeo y el almacenamiento idempotente usando respuestas
simuladas de MCU API (sin llamadas de red y sin tocar la base real:
los TestCase de Django corren sobre una base de prueba transitoria).

Estructura simulada de cada "pagina": igual al envelope real de la API
({"data": [...], "total": N, "page": 1, "limit": 10, "_links": {...}}).
"""

from datetime import date
import re

from django.db import IntegrityError
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from marvel import services
from marvel.mcu_client import MCUAPIInvalidResponse
from marvel.models import ElementoCatalogo, Resena

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

    def test_mapear_untitled_x_men_usa_imagen_respaldo(self):
        registro = {
            'id': 76,
            'title': 'Untitled X-Men film',
            'overview': None,
            'cover_url': None,
            'release_date': '2028-05-05',
            'phase': None,
            'saga': None,
        }
        datos = services.mapear_elemento('movie', registro)
        self.assertEqual(
            datos['imagen'],
            '/static/img/marvel/untitled-x-men.jpg',
        )

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
        respuesta = self.client.get('/marvel/catalogo/')
        self.assertEqual(respuesta.status_code, 200)
        # El header compartido debe mostrar el enlace al catalogo.
        self.assertContains(respuesta, 'Catálogo Marvel')

    def test_listado_solo_activos(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('tvshow', 1, 'WandaVision')
        self.crear('movie', 2, 'Retirado', activo=False)

        respuesta = self.client.get('/marvel/catalogo/')
        nombres = [e.nombre for e in respuesta.context['pagina'].object_list]
        self.assertEqual(set(nombres), {'Iron Man', 'WandaVision'})
        self.assertFalse(respuesta.context['hay_catalogo'] is False)

    def test_busqueda_por_nombre(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('movie', 2, 'Iron Man 2')
        self.crear('tvshow', 1, 'Loki')

        respuesta = self.client.get('/marvel/catalogo/', {'q': 'iron man'})
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


class RutasBloque4ATests(TestCase):
    """Bloque 4A: el catalogo vive en /marvel/catalogo/ y el detalle en
    /marvel/<pk>/. Desde el Bloque 4C /marvel/ es la landing Universo
    Marvel definitiva (las expectativas de redireccion temporal fueron
    reemplazadas, no eliminadas)."""

    def crear(self, tipo, mcu_id, nombre, activo=True):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def test_catalogo_responde_en_marvel_catalogo(self):
        self.crear('movie', 1, 'Iron Man')

        respuesta = self.client.get(reverse('marvel:catalogo'))

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Iron Man')

    def test_raiz_marvel_es_la_landing_universo(self):
        """Bloque 4C: /marvel/ ya no redirige; es la landing definitiva."""
        self.crear('movie', 1, 'Iron Man')

        respuesta = self.client.get(reverse('marvel:raiz'))

        self.assertEqual(respuesta.status_code, 200)
        # Sin redireccion: la respuesta ES la landing.
        self.assertFalse(respuesta.has_header('Location'))
        self.assertContains(respuesta, 'Universo')

    def test_querystring_en_la_raiz_no_rompe_la_landing(self):
        """El filtro antiguo ?q=... ya no se hereda del 4A: la landing
        ignora el querystring (el filtrado ocurre en /marvel/catalogo/)."""
        self.crear('movie', 1, 'Iron Man')

        respuesta = self.client.get('/marvel/?q=iron')
        self.assertEqual(respuesta.status_code, 200)

        respuesta_catalogo = self.client.get('/marvel/catalogo/', {'q': 'iron'})
        self.assertEqual(respuesta_catalogo.status_code, 200)
        nombres = [e.nombre for e in respuesta_catalogo.context['pagina'].object_list]
        self.assertEqual(nombres, ['Iron Man'])

    def test_busqueda_y_filtros_en_la_nueva_ruta(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('movie', 2, 'Iron Man 2')
        self.crear('tvshow', 1, 'Loki')

        respuesta = self.client.get(
            reverse('marvel:catalogo'), {'q': 'iron', 'tipo': 'peliculas'}
        )
        nombres = [e.nombre for e in respuesta.context['pagina'].object_list]
        self.assertEqual(set(nombres), {'Iron Man', 'Iron Man 2'})

        respuesta = self.client.get(
            reverse('marvel:catalogo'), {'tipo': 'series'}
        )
        nombres = [e.nombre for e in respuesta.context['pagina'].object_list]
        self.assertEqual(nombres, ['Loki'])

    def test_paginacion_en_la_nueva_ruta(self):
        for numero in range(1, 14):  # 13 elementos -> 12 + 1
            self.crear('movie', numero, f'Titulo {numero}')

        respuesta = self.client.get(
            reverse('marvel:catalogo'), {'page': 2}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(len(respuesta.context['pagina'].object_list), 1)
        # Los enlaces de paginacion conservan la nueva ruta.
        self.assertContains(respuesta, '?page=1')

    def test_detalle_sigue_disponible_en_marvel_pk(self):
        elemento = self.crear('movie', 1, 'Iron Man')

        respuesta = self.client.get(f'/marvel/{elemento.pk}/')
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Iron Man')

        respuesta = self.client.get('/marvel/99999/')
        self.assertEqual(respuesta.status_code, 404)


class LandingUniversoBloque4CTests(TestCase):
    """Bloque 4C: landing Universo Marvel en /marvel/ (reemplaza la
    redireccion temporal del 4A).

    Cubre: respuesta 200 publica, header con el enlace nuevo, destacados
    desde la base local, catalogo vacio, galeria estatica sin registros
    de personajes y conservacion de rutas y permisos.
    """

    def crear(self, tipo, mcu_id, nombre, activo=True, con_imagen=False,
              fecha_estreno=None, fase=None):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            imagen='https://ejemplo/img.jpg' if con_imagen else None,
            fecha_estreno=fecha_estreno,
            fase=fase,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def _crear_usuario(self, username, rol='cliente'):
        from online.models import Usuario

        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def test_landing_publica_200_para_visitante_y_todos_los_roles(self):
        respuesta = self.client.get(reverse('marvel:raiz'))
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Universo')

        for rol in ('cliente', 'tecnico', 'administrador'):
            with self.subTest(rol=rol):
                usuario = self._crear_usuario(f'universo-{rol}', rol)
                self.client.force_login(usuario)
                respuesta = self.client.get(reverse('marvel:raiz'))
                self.assertEqual(respuesta.status_code, 200)

    def test_header_enlaza_universo_marvel_y_catalogo(self):
        respuesta = self.client.get(reverse('marvel:raiz'))
        contenido = respuesta.content.decode('utf-8')

        self.assertIn('Universo Marvel', contenido)
        self.assertIn('href="/marvel/"', contenido)
        self.assertIn(
            f'href="{reverse("marvel:catalogo")}"', contenido,
        )

    def test_destacados_desde_la_base_local(self):
        nueva = self.crear(
            'movie', 1, 'Estreno reciente',
            fecha_estreno=date(2024, 1, 1), fase=5,
        )
        self.crear('movie', 2, 'Estreno viejo', fecha_estreno=date(2008, 5, 2))
        self.crear('movie', 3, 'Retirada', activo=False,
                   fecha_estreno=date(2025, 1, 1))
        self.crear('tvshow', 1, 'Serie vigente', fecha_estreno=date(2021, 1, 1))

        respuesta = self.client.get(reverse('marvel:raiz'))
        contenido = respuesta.content.decode('utf-8')

        # El mas reciente primero (orden por estreno descendente) y sin
        # elementos inactivos.
        self.assertIn('Estreno reciente', contenido)
        self.assertIn('Estreno viejo', contenido)
        self.assertIn('Serie vigente', contenido)
        self.assertNotIn('Retirada', contenido)
        self.assertLess(
            contenido.find('Estreno reciente'),
            contenido.find('Estreno viejo'),
        )
        # Cada tarjeta destacada enlaza a su ficha con nombre de URL.
        self.assertIn(
            reverse('marvel:detalle', args=[nueva.pk]), contenido,
        )

    def test_landing_funciona_con_catalogo_vacio(self):
        respuesta = self.client.get(reverse('marvel:raiz'))
        contenido = respuesta.content.decode('utf-8')

        self.assertEqual(respuesta.status_code, 200)
        # Sin destacados ni accesos con conteos, pero con hero y galeria.
        self.assertNotIn('Del catálogo', contenido)
        self.assertNotIn('Películas destacadas', contenido)
        self.assertIn('universo-galeria', contenido)

    def test_galeria_estatica_no_depende_de_registros(self):
        # Sin ningun registro en la base la galeria se ve igual: son
        # recursos locales, no elementos de catalogo ni personajes.
        respuesta = self.client.get(reverse('marvel:raiz'))
        contenido = respuesta.content.decode('utf-8')

        self.assertEqual(ElementoCatalogo.objects.count(), 0)
        personajes = (
            'iron-man-poster.jpg',
            'captain-america-poster.jpg',
            'thor-poster.jpg',
            'hulk-poster.jpg',
            'scarlet-witch-poster.jpg',
            'loki-poster.jpg',
        )
        for personaje in personajes:
            self.assertIn(f'img/marvel/{personaje}', contenido)
        # La galeria es visual: los <li> no estan envueltos en enlaces.
        self.assertNotIn('<a class="universo-galeria', contenido)

    def test_enlaces_internos_de_la_landing_resuelven(self):
        self.crear('movie', 1, 'Iron Man')
        self.crear('tvshow', 1, 'Loki')

        respuesta = self.client.get(reverse('marvel:raiz'))
        hrefs = re.findall(r'href="(/[^"]*)"', respuesta.content.decode('utf-8'))
        # Solo enlaces de navegacion: los <link> de CSS (/static/) no los
        # sirve el test client sin staticfiles.
        hrefs = [href for href in hrefs if not href.startswith('/static/')]

        self.assertTrue(hrefs)
        for href in set(hrefs):
            with self.subTest(href=href):
                respuesta_interna = self.client.get(href)
                self.assertEqual(respuesta_interna.status_code, 200)

    def test_rutas_de_catalogo_y_fichas_conservadas(self):
        elemento = self.crear('movie', 1, 'Iron Man')

        respuesta_catalogo = self.client.get(reverse('marvel:catalogo'))
        self.assertEqual(respuesta_catalogo.status_code, 200)
        self.assertContains(respuesta_catalogo, 'Iron Man')

        respuesta_ficha = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]))
        self.assertEqual(respuesta_ficha.status_code, 200)

    def test_permisos_conservados(self):
        cliente = self._crear_usuario('universo-cliente')
        self.client.force_login(cliente)
        respuesta = self.client.get(reverse('marvel:raiz'))
        self.assertEqual(respuesta.status_code, 200)
        # El cliente sigue sin ver enlaces al panel administrativo.
        self.assertNotContains(respuesta, reverse('administracion'))

        admin = self._crear_usuario('universo-admin', 'administrador')
        self.client.force_login(admin)
        respuesta = self.client.get(reverse('marvel:raiz'))
        self.assertContains(respuesta, reverse('administracion'))


class ResenaModeloTests(TestCase):
    """Bloque 5B: modelo Resena, validaciones y restricciones.

    Las validaciones de contenido (calificacion, referencia tematica,
    elemento reseñable/activo, autor cliente) viven en clean() y se
    verifican con full_clean(); la unicidad (elemento, usuario) esta
    protegida TAMBIEN por la base de datos (UniqueConstraint), de modo
    que un save() directo sin full_clean la respeta igualmente.
    """

    EXCLUIDAS_FULL_CLEAN = {'fecha_publicacion'}  # auto_now_add

    def crear_elemento(self, tipo='movie', mcu_id=1, nombre='Iron Man',
                       activo=True):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def crear_usuario(self, username, rol='cliente'):
        from online.models import Usuario

        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def _resena(self, usuario, elemento, calificacion=4,
                referencia='Tony Stark construye el traje.'):
        return Resena(
            elemento=elemento,
            usuario=usuario,
            calificacion=calificacion,
            referencia_tematica=referencia,
        )

    # --- 1. Creacion valida -------------------------------------------------
    def test_creacion_valida(self):
        usuario = self.crear_usuario('resena-autor')
        elemento = self.crear_elemento()

        resena = self._resena(usuario, elemento)
        resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        resena.save()

        self.assertIsNotNone(resena.pk)
        self.assertEqual(resena.usuario, usuario)
        self.assertEqual(resena.elemento, elemento)
        # 14. Por defecto se publica visible.
        self.assertTrue(resena.visible)
        self.assertIsNotNone(resena.fecha_publicacion)

    def test_referencia_se_normaliza_con_trim(self):
        usuario = self.crear_usuario('resena-trim')
        elemento = self.crear_elemento(mcu_id=2)

        resena = self._resena(
            usuario, elemento, referencia='   Traje Mark I   ',
        )
        resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        resena.save()

        self.assertEqual(
            resena.referencia_tematica,
            'Traje Mark I',  # trim coherente con el resto del proyecto
        )

    # --- 2-5. Calificacion ---------------------------------------------------
    def test_calificacion_limites_aceptados(self):
        usuario = self.crear_usuario('resena-limites')
        elemento = self.crear_elemento(mcu_id=3)

        for calificacion in (1, 5):
            with self.subTest(calificacion=calificacion):
                resena = self._resena(
                    usuario, elemento, calificacion=calificacion,
                )
                # Solo valida: no guarda, para no chocar con la unicidad.
                resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    def test_calificacion_fuera_de_rango_rechazada(self):
        usuario = self.crear_usuario('resena-fuera')
        elemento = self.crear_elemento(mcu_id=4)

        for calificacion in (0, 6, -1):
            with self.subTest(calificacion=calificacion):
                resena = self._resena(
                    usuario, elemento, calificacion=calificacion,
                )
                with self.assertRaises(ValidationError):
                    resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    # --- 6-10. Referencia tematica -------------------------------------------
    def test_referencia_longitudes_aceptadas(self):
        usuario = self.crear_usuario('resena-longitudes')
        elemento = self.crear_elemento(mcu_id=5)

        for longitud in (10, 200):  # limites exactos
            with self.subTest(longitud=longitud):
                resena = self._resena(
                    usuario, elemento, referencia='A' * longitud,
                )
                resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    def test_referencia_corta_o_larga_rechazada(self):
        usuario = self.crear_usuario('resena-largo')
        elemento = self.crear_elemento(mcu_id=6)

        for longitud in (9, 201):
            with self.subTest(longitud=longitud):
                resena = self._resena(
                    usuario, elemento, referencia='A' * longitud,
                )
                with self.assertRaises(ValidationError):
                    resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    def test_referencia_vacia_o_solo_espacios_rechazada(self):
        usuario = self.crear_usuario('resena-espacios')
        elemento = self.crear_elemento(mcu_id=7)

        for referencia in ('', '     '):
            with self.subTest(referencia=representar(referencia)):
                resena = self._resena(
                    usuario, elemento, referencia=referencia,
                )
                with self.assertRaises(ValidationError):
                    resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    # --- 11. Unicidad usuario-elemento ----------------------------------------
    def test_segunda_resena_del_mismo_usuario_rechazada(self):
        usuario = self.crear_usuario('resena-duplicada')
        elemento = self.crear_elemento(mcu_id=8)

        primera = self._resena(usuario, elemento, calificacion=5)
        primera.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        primera.save()

        # full_clean (aplicacion) detecta la constraint como ValidationError.
        duplicada = self._resena(usuario, elemento, calificacion=2)
        with self.assertRaises(ValidationError):
            duplicada.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

        # La base de datos tambien la protege: save() directo sin
        # full_clean levanta IntegrityError.
        with self.assertRaises(IntegrityError):
            duplicada.save()

    def test_mismo_usuario_puede_resenar_elementos_distintos(self):
        usuario = self.crear_usuario('resena-multi-elemento')
        elemento_a = self.crear_elemento(mcu_id=9, nombre='Iron Man')
        elemento_b = self.crear_elemento(
            'tvshow', 10, 'WandaVision',
        )

        for elemento in (elemento_a, elemento_b):
            resena = self._resena(usuario, elemento)
            resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
            resena.save()

        self.assertEqual(usuario.resenas.count(), 2)

    def test_usuarios_distintos_pueden_resenar_el_mismo_elemento(self):
        usuario_a = self.crear_usuario('resena-usuaria-a')
        usuario_b = self.crear_usuario('resena-usuaria-b')
        elemento = self.crear_elemento(mcu_id=11)

        for usuario in (usuario_a, usuario_b):
            resena = self._resena(usuario, elemento)
            resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
            resena.save()

        self.assertEqual(elemento.resenas.count(), 2)

    # --- 15-17. Validaciones de clean() ---------------------------------------
    def test_elemento_inactivo_rechazado(self):
        usuario = self.crear_usuario('resena-inactivo')
        elemento = self.crear_elemento(mcu_id=12, activo=False)

        resena = self._resena(usuario, elemento)
        with self.assertRaises(ValidationError):
            resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    def test_tipo_no_resenable_rechazado(self):
        usuario = self.crear_usuario('resena-tipo')
        # Registro directo con tipo fuera de choices: simula una base
        # tocada fuera de Django (los characters se retiraron en el
        # Bloque 1); la reseña debe rechazarlo igualmente.
        elemento = ElementoCatalogo.objects.create(
            tipo='character',
            mcu_id=13,
            nombre='Registro historico',
        )

        resena = self._resena(usuario, elemento)
        with self.assertRaises(ValidationError):
            resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    def test_autores_sin_rol_cliente_rechazados(self):
        elemento = self.crear_elemento(mcu_id=14)

        for rol in ('tecnico', 'administrador'):
            with self.subTest(rol=rol):
                usuario = self.crear_usuario(f'resena-{rol}', rol)
                resena = self._resena(usuario, elemento)
                with self.assertRaises(ValidationError):
                    resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)

    # --- 18. Ordenamiento ------------------------------------------------------
    def test_ordenamiento_por_fecha_de_publicacion(self):
        usuario = self.crear_usuario('resena-orden')
        elemento = self.crear_elemento(mcu_id=15)

        antigua = self._resena(usuario, elemento, calificacion=3)
        antigua.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        antigua.save()

        usuario_b = self.crear_usuario('resena-orden-b')
        reciente = self._resena(usuario_b, elemento, calificacion=5)
        reciente.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        reciente.save()

        # auto_now_add impide fijar fechas en la instancia: se actualizan
        # por queryset (igual al comportamiento real con el tiempo).
        base = timezone.now()
        antigua.refresh_from_db()
        Resena.objects.filter(pk=antigua.pk).update(
            fecha_publicacion=base - timezone.timedelta(days=1),
        )
        Resena.objects.filter(pk=reciente.pk).update(
            fecha_publicacion=base,
        )

        orden = list(Resena.objects.all())
        self.assertEqual(orden, [reciente, antigua])

    # --- 19. Integridad de relaciones (CASCADE) --------------------------------
    def test_borrar_usuario_elimina_sus_resenas(self):
        usuario = self.crear_usuario('resena-cascade-u')
        elemento = self.crear_elemento(mcu_id=16)

        resena = self._resena(usuario, elemento)
        resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        resena.save()

        usuario.delete()
        self.assertEqual(elemento.resenas.count(), 0)

    def test_borrar_elemento_elimina_sus_resenas(self):
        usuario = self.crear_usuario('resena-cascade-e')
        elemento = self.crear_elemento(mcu_id=17)

        resena = self._resena(usuario, elemento)
        resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        resena.save()

        elemento.delete()
        self.assertEqual(usuario.resenas.count(), 0)

    def test_related_names_desde_ambos_lados(self):
        usuario = self.crear_usuario('resena-related')
        elemento = self.crear_elemento(mcu_id=18)

        resena = self._resena(usuario, elemento)
        resena.full_clean(exclude=self.EXCLUIDAS_FULL_CLEAN)
        resena.save()

        self.assertIn(resena, elemento.resenas.all())
        self.assertIn(resena, usuario.resenas.all())
        self.assertIn('Iron Man', str(resena))
        self.assertIn(str(usuario), str(resena))


def representar(texto):
    """Etiqueta legible para subTest con textos de espacios."""
    return repr(texto)


class ResenasBloque5CTests(TestCase):
    """Bloque 5C: publicacion y visualizacion de reseñas en la ficha.

    GET publico; POST solo para clientes autenticados (visitante ->
    login, tecnico/admin -> 403). El servidor asigna autor/elemento/
    visible y filtra las ocultas segun rol (no por CSS).
    """

    def crear_elemento(self, tipo='movie', mcu_id=1, nombre='Iron Man',
                       activo=True):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def crear_usuario(self, username, rol='cliente'):
        from online.models import Usuario

        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def crear_resena(self, usuario, elemento, calificacion=4,
                     referencia='Tony Stark construye el traje.',
                     visible=True):
        return Resena.objects.create(
            elemento=elemento,
            usuario=usuario,
            calificacion=calificacion,
            referencia_tematica=referencia,
            visible=visible,
        )

    def _publicar(self, elemento, calificacion='4',
                  referencia='Tony Stark construye el traje.',
                  follow=False, **extra):
        datos = {
            'calificacion': calificacion,
            'referencia_tematica': referencia,
            **extra,
        }
        return self.client.post(
            reverse('marvel:detalle', args=[elemento.pk]), datos,
            follow=follow,
        )

    # --- 1-3. GET publico y publicacion --------------------------------------
    def test_get_de_detalle_publico(self):
        elemento = self.crear_elemento()

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Reseñas')
        self.assertContains(respuesta, 'Todavía no hay reseñas')

    def test_cliente_publica_correctamente(self):
        cliente = self.crear_usuario('c5c-cliente')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento, follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.redirect_chain[0][0],
            f'{reverse("marvel:detalle", args=[elemento.pk])}'
            '?resena=publicada#resenas',
        )
        self.assertContains(respuesta, '¡Reseña publicada!')

        resena = Resena.objects.get()
        self.assertEqual(resena.usuario, cliente)
        self.assertEqual(resena.elemento, elemento)
        self.assertEqual(resena.calificacion, 4)
        self.assertTrue(resena.visible)

    def test_publicacion_visible_inmediatamente(self):
        cliente = self.crear_usuario('c5c-visibilidad')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        self._publicar(elemento)
        # Sin sesion: la reseña ya es parte del listado publico.
        self.client.logout()
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertContains(respuesta, 'c5c-visibilidad')
        self.assertContains(respuesta, 'Tony Stark construye el traje.')

    # --- 4-7. Validaciones del formulario --------------------------------------
    def test_calificacion_invalida_rechazada(self):
        cliente = self.crear_usuario('c5c-calif')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        for calificacion in ('0', '6', '', 'abc'):
            with self.subTest(calificacion=calificacion):
                respuesta = self._publicar(
                    elemento, calificacion=calificacion,
                )
                self.assertEqual(respuesta.status_code, 200)
                self.assertContains(respuesta, 'Calificación', status_code=200)
                self.assertEqual(Resena.objects.count(), 0)

    def test_referencia_corta_rechazada(self):
        cliente = self.crear_usuario('c5c-corta')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento, referencia='Muy corta')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'al menos 10 caracteres')
        self.assertEqual(Resena.objects.count(), 0)

    def test_referencia_larga_rechazada(self):
        cliente = self.crear_usuario('c5c-larga')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento, referencia='A' * 201)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Resena.objects.count(), 0)

    def test_referencia_solo_espacios_rechazada(self):
        cliente = self.crear_usuario('c5c-espacios')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento, referencia='      ')

        self.assertEqual(respuesta.status_code, 200)
        # El CharField de formularios hace strip: queda vacio y el
        # modelo rechaza con el mensaje de campo obligatorio.
        self.assertContains(respuesta, 'Este campo es obligatorio')
        self.assertEqual(Resena.objects.count(), 0)

    # --- 8. Duplicados ----------------------------------------------------------
    def test_cliente_no_puede_publicar_duplicados(self):
        cliente = self.crear_usuario('c5c-duplicada')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        self._publicar(elemento, calificacion='5')
        # Segundo intento por la misma via (tambien cubre el doble envio).
        respuesta = self._publicar(elemento, calificacion='2')

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Ya publicaste una reseña')
        self.assertEqual(Resena.objects.count(), 1)

    # --- 9-11. Roles que no publican ---------------------------------------------
    def test_visitante_no_puede_publicar(self):
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento)

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('Login'), respuesta['Location'])
        self.assertEqual(Resena.objects.count(), 0)

    def test_tecnico_no_puede_publicar(self):
        tecnico = self.crear_usuario('c5c-tecnico', 'tecnico')
        self.client.force_login(tecnico)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento)

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Resena.objects.count(), 0)

    def test_administrador_no_puede_publicar(self):
        admin = self.crear_usuario('c5c-admin', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento()

        respuesta = self._publicar(elemento)

        self.assertEqual(respuesta.status_code, 403)
        self.assertEqual(Resena.objects.count(), 0)

    # --- 12-13. Blindaje contra suplantacion ---------------------------------------
    def test_no_se_puede_suplantar_autor(self):
        cliente = self.crear_usuario('c5c-autor')
        otro = self.crear_usuario('c5c-otro')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        # Intento de enviar el campo 'usuario' del modelo en el POST.
        self._publicar(elemento, usuario=otro.pk)

        resena = Resena.objects.get()
        self.assertEqual(resena.usuario, cliente)

    def test_no_se_puede_ocultar_desde_post(self):
        cliente = self.crear_usuario('c5c-visible')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        # Intento de enviar 'visible' (campo del modelo) en el POST.
        self._publicar(elemento, visible='False')

        resena = Resena.objects.get()
        self.assertTrue(resena.visible)

    # --- 14-15. Elementos no reseñables ---------------------------------------------
    def test_elemento_inactivo_no_admite_resenas(self):
        cliente = self.crear_usuario('c5c-inactivo')
        self.client.force_login(cliente)
        elemento = self.crear_elemento(activo=False)

        ruta = reverse('marvel:detalle', args=[elemento.pk])
        self.assertEqual(self.client.get(ruta).status_code, 404)
        self.assertEqual(
            self.client.post(ruta, {
                'calificacion': '4',
                'referencia_tematica': 'Tony Stark construye el traje.',
            }).status_code,
            404,
        )
        self.assertEqual(Resena.objects.count(), 0)

    def test_tipo_no_resenable_rechazado(self):
        cliente = self.crear_usuario('c5c-character')
        self.client.force_login(cliente)
        # Registro fuera de choices: simula una base tocada fuera de Django.
        elemento = ElementoCatalogo.objects.create(
            tipo='character', mcu_id=99, nombre='Registro historico',
        )

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertEqual(respuesta.status_code, 404)
        self.assertEqual(Resena.objects.count(), 0)

    # --- 16-19. Visibilidad por rol ---------------------------------------------------
    def test_resenas_visibles_accesibles_publicamente(self):
        autor = self.crear_usuario('c5c-publica')
        elemento = self.crear_elemento()
        self.crear_resena(autor, elemento)

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertContains(respuesta, 'c5c-publica')
        self.assertContains(respuesta, 'Tony Stark construye el traje.')

    def test_resenas_ocultas_no_aparecen_a_visitante_ni_tecnico(self):
        autor = self.crear_usuario('c5c-oculta')
        elemento = self.crear_elemento()
        self.crear_resena(
            autor, elemento,
            referencia='Reseña oculta por moderacion.',
            visible=False,
        )

        for observador in (None, 'tecnico'):
            with self.subTest(observador=observador or 'visitante'):
                if observador:
                    self.client.force_login(
                        self.crear_usuario(f'c5c-obs-{observador}', observador),
                    )
                respuesta = self.client.get(
                    reverse('marvel:detalle', args=[elemento.pk]),
                )
                self.assertNotContains(respuesta, 'Reseña oculta')
                self.assertNotContains(respuesta, 'Oculta por moderación')
                self.client.logout()

    def test_autor_ve_su_resena_oculta_con_etiqueta(self):
        autor = self.crear_usuario('c5c-propia')
        elemento = self.crear_elemento()
        self.crear_resena(
            autor, elemento,
            referencia='Reseña oculta propia del autor.',
            visible=False,
        )
        self.client.force_login(autor)

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertContains(respuesta, 'Reseña oculta propia del autor.')
        self.assertContains(respuesta, 'Oculta por moderación')

    def test_admin_ve_resenas_ocultas_con_etiqueta(self):
        autor = self.crear_usuario('c5c-para-admin')
        elemento = self.crear_elemento()
        self.crear_resena(
            autor, elemento,
            referencia='Reseña oculta para moderar.',
            visible=False,
        )
        admin = self.crear_usuario('c5c-observador', 'administrador')
        self.client.force_login(admin)

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertContains(respuesta, 'Reseña oculta para moderar.')
        self.assertContains(respuesta, 'Oculta por moderación')

    # --- 20. XSS -----------------------------------------------------------------------
    def test_xss_escapado_en_referencia(self):
        cliente = self.crear_usuario('c5c-xss')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        # Autoescape de Django: el script debe llegar escapado.
        self._publicar(
            elemento,
            referencia='<script>alert(1)</script> Tony Stark',
        )

        self.assertEqual(Resena.objects.count(), 1)
        contenido = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        ).content.decode('utf-8')
        self.assertNotIn('<script>alert(1)</script>', contenido)
        self.assertIn('&lt;script&gt;', contenido)

    # --- 21. Integracion con la ficha ----------------------------------------------------
    def test_get_de_detalle_y_enlaces_a_tickets_siguen_funcionando(self):
        cliente = self.crear_usuario('c5c-ticket')
        self.client.force_login(cliente)
        elemento = self.crear_elemento()

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertEqual(respuesta.status_code, 200)
        # El boton de consulta de C1.4 no se rompe.
        self.assertContains(respuesta, 'Crear consulta sobre este elemento')
        self.assertContains(respuesta, reverse('inicio', args=[cliente.id]))

    # --- 22. Sin N+1 -----------------------------------------------------------------------
    def test_listado_sin_n_plus_one(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        elemento = self.crear_elemento()
        autores = [self.crear_usuario(f'c5c-perf-{i}') for i in range(8)]
        self.crear_resena(autores[0], elemento)

        ruta = reverse('marvel:detalle', args=[elemento.pk])
        with CaptureQueriesContext(connection) as contexto_1:
            self.client.get(ruta)
        consultas_con_1 = len(contexto_1)

        for autor in autores[1:]:
            self.crear_resena(autor, elemento)
        with CaptureQueriesContext(connection) as contexto_8:
            self.client.get(ruta)
        consultas_con_8 = len(contexto_8)

        # El numero de consultas es IGUAL con 1 y con 8 reseñas: el
        # listado usa select_related y no consulta por cada item.
        self.assertEqual(consultas_con_1, consultas_con_8)

    # --- Formulario por rol ------------------------------------------------------------------
    def test_formulario_solo_para_clientes_sin_resena(self):
        elemento = self.crear_elemento()

        # Visitante: enlace al login, sin formulario.
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )
        self.assertContains(respuesta, 'Inicia sesión')
        self.assertNotContains(respuesta, 'Publicar reseña')

        # Cliente sin reseña: formulario completo.
        cliente = self.crear_usuario('c5c-form-cliente')
        self.client.force_login(cliente)
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )
        self.assertContains(respuesta, 'Publicar reseña')

        # Cliente con reseña previa: aviso, sin formulario.
        self.crear_resena(cliente, elemento)
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )
        self.assertContains(respuesta, 'Ya publicaste una reseña')
        self.assertNotContains(respuesta, 'Publicar reseña')
        self.client.logout()

        # Tecnico y administrador: ni formulario ni enlace de login.
        for rol in ('tecnico', 'administrador'):
            with self.subTest(rol=rol):
                self.client.force_login(
                    self.crear_usuario(f'c5c-form-{rol}', rol),
                )
                respuesta = self.client.get(
                    reverse('marvel:detalle', args=[elemento.pk]),
                )
                self.assertNotContains(respuesta, 'Publicar reseña')
                self.assertNotContains(respuesta, 'Inicia sesión')
                self.client.logout()


class ModeracionBloque5DTests(TestCase):
    """Bloque 5D: moderacion admin (ocultar/restaurar) y promedio.

    Moderacion SOLO admin, SOLO POST con CSRF, accion en la RUTA (no
    en parametros libres). Promedio/cantidad solo sobre visible=True
    y SOLO en la ficha de detalle. La visibilidad por rol de las
    ocultas ya esta en 5C; aqui se re-verifica el conjunto.
    """

    def crear_elemento(self, tipo='movie', mcu_id=1, nombre='Iron Man',
                       activo=True):
        return ElementoCatalogo.objects.create(
            tipo=tipo,
            mcu_id=mcu_id,
            nombre=nombre,
            activo=activo,
            datos_json={'id': mcu_id, 'type': tipo},
        )

    def crear_usuario(self, username, rol='cliente'):
        from online.models import Usuario

        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def crear_resena(self, usuario, elemento, calificacion=4,
                     referencia='Tony Stark construye el traje.',
                     visible=True):
        return Resena.objects.create(
            elemento=elemento,
            usuario=usuario,
            calificacion=calificacion,
            referencia_tematica=referencia,
            visible=visible,
        )

    def _moderar(self, elemento, resena, accion='ocultar',
                 follow=False, datos=None):
        nombre_ruta = (
            'marvel:ocultar_resena' if accion == 'ocultar'
            else 'marvel:restaurar_resena'
        )
        return self.client.post(
            reverse(nombre_ruta, args=[elemento.pk, resena.pk]),
            datos or {},
            follow=follow,
        )

    # --- 1-2. Acciones de moderacion -----------------------------------------
    def test_admin_puede_ocultar_una_resena(self):
        admin = self.crear_usuario('c5d-admin', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-a'), elemento,
        )

        respuesta = self._moderar(elemento, resena, 'ocultar', follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(
            respuesta.redirect_chain[0][0],
            f'{reverse("marvel:detalle", args=[elemento.pk])}'
            '?resena=ocultada#resenas',
        )
        self.assertContains(respuesta, 'Reseña oculta por moderación.')
        resena.refresh_from_db()
        self.assertFalse(resena.visible)

    def test_admin_puede_restaurar_una_resena(self):
        admin = self.crear_usuario('c5d-admin-b', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-b'), elemento, visible=False,
        )

        respuesta = self._moderar(elemento, resena, 'restaurar', follow=True)

        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(
            respuesta, 'Reseña restaurada: vuelve a ser visible',
        )
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    # --- 3-5. Quien NO puede moderar -------------------------------------------
    def test_cliente_no_puede_moderar(self):
        autor = self.crear_usuario('c5d-dueno')
        elemento = self.crear_elemento()
        resena = self.crear_resena(autor, elemento)

        self.client.force_login(autor)  # incluso el propio autor
        respuesta = self._moderar(elemento, resena, 'ocultar')

        self.assertEqual(respuesta.status_code, 403)
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    def test_tecnico_no_puede_moderar(self):
        tecnico = self.crear_usuario('c5d-tecnico', 'tecnico')
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-t'), elemento,
        )
        self.client.force_login(tecnico)

        respuesta = self._moderar(elemento, resena, 'ocultar')

        self.assertEqual(respuesta.status_code, 403)
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    def test_visitante_no_puede_moderar(self):
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-v'), elemento,
        )

        respuesta = self._moderar(elemento, resena, 'ocultar')

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('Login'), respuesta['Location'])
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    # --- 6-7. Metodo y CSRF ------------------------------------------------------
    def test_moderacion_por_get_rechazada(self):
        admin = self.crear_usuario('c5d-admin-get', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-g'), elemento,
        )

        for accion in ('ocultar', 'restaurar'):
            nombre_ruta = (
                'marvel:ocultar_resena' if accion == 'ocultar'
                else 'marvel:restaurar_resena'
            )
            with self.subTest(accion=accion):
                respuesta = self.client.get(
                    reverse(nombre_ruta, args=[elemento.pk, resena.pk]),
                )
                self.assertEqual(respuesta.status_code, 405)
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    def test_proteccion_csrf_en_post(self):
        admin = self.crear_usuario('c5d-admin-csrf', 'administrador')
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-c'), elemento,
        )

        cliente_con_csrf = self.client_class(enforce_csrf_checks=True)
        cliente_con_csrf.force_login(admin)
        respuesta = cliente_con_csrf.post(
            reverse('marvel:ocultar_resena', args=[elemento.pk, resena.pk]),
            {},
        )

        self.assertEqual(respuesta.status_code, 403)
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

    # --- 8. Solo cambia visible ------------------------------------------------------
    def test_moderacion_no_modifica_otros_campos(self):
        admin = self.crear_usuario('c5d-admin-x', 'administrador')
        elemento = self.crear_elemento(mcu_id=1, nombre='Iron Man')
        otro_elemento = self.crear_elemento(mcu_id=2, nombre='Thor')
        autor = self.crear_usuario('c5d-autor-x')
        resena = self.crear_resena(
            autor, elemento, calificacion=4,
            referencia='Tony Stark construye el traje.',
        )
        self.client.force_login(admin)

        # Intento de cambiar campos del modelo junto con la moderacion.
        respuesta = self._moderar(
            elemento, resena, 'ocultar',
            datos={
                'calificacion': '1',
                'referencia_tematica': 'Texto manipulado que no debe aplicar',
                'usuario': admin.pk,
                'elemento': otro_elemento.pk,
                'visible': 'True',
            },
        )

        resena.refresh_from_db()
        self.assertFalse(resena.visible)  # unico cambio permitido
        self.assertEqual(resena.calificacion, 4)
        self.assertEqual(resena.referencia_tematica,
                         'Tony Stark construye el traje.')
        self.assertEqual(resena.usuario, autor)
        self.assertEqual(resena.elemento, elemento)

    # --- 9-12. Visibilidad de ocultas por rol (re-verificacion) -------------------------
    def test_visibilidad_de_ocultas_por_rol(self):
        autor = self.crear_usuario('c5d-oculta-autor')
        elemento = self.crear_elemento()
        resena = self.crear_resena(
            autor, elemento,
            referencia='Reseña oculta de verificacion.',
            visible=False,
        )
        ruta = reverse('marvel:detalle', args=[elemento.pk])

        # Visitante y tecnico: no aparece.
        for username_rol in (None, 'tecnico'):
            with self.subTest(rol=username_rol or 'visitante'):
                if username_rol:
                    self.client.force_login(
                        self.crear_usuario(
                            f'c5d-obs-{username_rol}', username_rol,
                        ),
                    )
                respuesta = self.client.get(ruta)
                self.assertNotContains(respuesta, 'Reseña oculta')
                self.assertNotContains(respuesta, 'Oculta por moderación')
                self.client.logout()

        # El autor la ve con la etiqueta exacta.
        self.client.force_login(autor)
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Reseña oculta de verificacion.')
        self.assertContains(respuesta, 'Oculta por moderación')
        self.client.logout()

        # El administrador la ve con la etiqueta exacta.
        self.client.force_login(
            self.crear_usuario('c5d-obs-admin', 'administrador'),
        )
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Reseña oculta de verificacion.')
        self.assertContains(respuesta, 'Oculta por moderación')

    # --- 13-15. Moderacion y estadisticas ----------------------------------------------
    def test_ocultar_una_resena_modifica_el_promedio(self):
        admin = self.crear_usuario('c5d-admin-p', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento()
        buena = self.crear_resena(
            self.crear_usuario('c5d-perf-a'), elemento, calificacion=5,
        )
        baja = self.crear_resena(
            self.crear_usuario('c5d-perf-b'), elemento, calificacion=1,
        )

        ruta = reverse('marvel:detalle', args=[elemento.pk])
        respuesta = self.client.get(ruta)
        self.assertAlmostEqual(respuesta.context['promedio'], 3.0)
        self.assertEqual(respuesta.context['total_resenas_visibles'], 2)

        self._moderar(elemento, baja, 'ocultar')
        respuesta = self.client.get(ruta)
        self.assertAlmostEqual(respuesta.context['promedio'], 5.0)
        self.assertEqual(respuesta.context['total_resenas_visibles'], 1)

    def test_restaurar_una_resena_modifica_el_promedio(self):
        admin = self.crear_usuario('c5d-admin-q', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento(mcu_id=2)
        self.crear_resena(
            self.crear_usuario('c5d-perf-c'), elemento, calificacion=5,
        )
        restaurada = self.crear_resena(
            self.crear_usuario('c5d-perf-d'), elemento, calificacion=1,
            visible=False,
        )

        ruta = reverse('marvel:detalle', args=[elemento.pk])
        respuesta = self.client.get(ruta)
        self.assertAlmostEqual(respuesta.context['promedio'], 5.0)
        self.assertEqual(respuesta.context['total_resenas_visibles'], 1)

        self._moderar(elemento, restaurada, 'restaurar')
        respuesta = self.client.get(ruta)
        self.assertAlmostEqual(respuesta.context['promedio'], 3.0)
        self.assertEqual(respuesta.context['total_resenas_visibles'], 2)

    def test_ocultas_no_cuentan_en_el_total_publico(self):
        elemento = self.crear_elemento(mcu_id=3)
        self.crear_resena(
            self.crear_usuario('c5d-tot-a'), elemento, calificacion=5,
        )
        self.crear_resena(
            self.crear_usuario('c5d-tot-b'), elemento, calificacion=4,
        )
        self.crear_resena(
            self.crear_usuario('c5d-tot-c'), elemento, calificacion=2,
            visible=False,
        )

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertEqual(respuesta.context['total_resenas_visibles'], 2)
        contenido = respuesta.content.decode('utf-8')
        self.assertIn('2 reseñas', contenido)
        self.assertNotIn('3 reseñas', contenido)
        # La oculta no aparece en la respuesta publica.
        self.assertNotIn('Oculta por moderación', contenido)

    # --- 16-17. Promedio ------------------------------------------------------------------
    def test_promedio_correcto_con_varias_calificaciones(self):
        elemento = self.crear_elemento(mcu_id=4)
        for calificacion, indice in ((3, 1), (4, 2), (5, 3)):
            self.crear_resena(
                self.crear_usuario(f'c5d-avg-{indice}'),
                elemento,
                calificacion=calificacion,
            )

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertAlmostEqual(
            respuesta.context['promedio'], 4.0, places=2,
        )
        self.assertEqual(respuesta.context['total_resenas_visibles'], 3)
        # Linea de promedio presente con sus dos partes.
        contenido = respuesta.content.decode('utf-8')
        self.assertIn('resenas-promedio', contenido)
        self.assertIn('estrellas', contenido)
        self.assertIn('reseñas', contenido)

    def test_estado_sin_resenas_visibles(self):
        elemento = self.crear_elemento(mcu_id=5)

        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )

        self.assertIsNone(respuesta.context['promedio'])
        self.assertEqual(respuesta.context['total_resenas_visibles'], 0)
        self.assertContains(respuesta, 'Sin calificaciones todavía')
        self.assertContains(respuesta, 'Todavía no hay reseñas')

        # Caso limite: existen reseñas pero TODAS ocultas.
        self.crear_resena(
            self.crear_usuario('c5d-solo-oculta'),
            elemento,
            calificacion=2,
            visible=False,
        )
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )
        self.assertIsNone(respuesta.context['promedio'])
        self.assertContains(respuesta, 'Sin calificaciones todavía')

    # --- 18. Promedio exclusivo del detalle ------------------------------------------------
    def test_promedio_exclusivo_de_la_ficha_de_detalle(self):
        elemento = self.crear_elemento(mcu_id=6)
        self.crear_resena(
            self.crear_usuario('c5d-solo-detalle'), elemento,
            calificacion=5,
        )

        for ruta in (
            reverse('marvel:catalogo'),
            reverse('marvel:raiz'),
            reverse('index'),
        ):
            with self.subTest(ruta=ruta):
                respuesta = self.client.get(ruta)
                self.assertEqual(respuesta.status_code, 200)
                self.assertNotContains(respuesta, 'resenas-promedio')
                self.assertNotContains(respuesta, '/ 5 estrellas')

    # --- 19. Sin N+1 (con estadisticas incluidas) --------------------------------------------
    def test_listado_y_promedio_sin_n_plus_one(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext

        elemento = self.crear_elemento(mcu_id=7)
        autores = [self.crear_usuario(f'c5d-perf-{i}') for i in range(8)]
        self.crear_resena(autores[0], elemento)

        ruta = reverse('marvel:detalle', args=[elemento.pk])
        with CaptureQueriesContext(connection) as contexto_1:
            self.client.get(ruta)
        consultas_con_1 = len(contexto_1)

        for autor in autores[1:]:
            self.crear_resena(autor, elemento)
        with CaptureQueriesContext(connection) as contexto_8:
            self.client.get(ruta)
        consultas_con_8 = len(contexto_8)

        self.assertEqual(consultas_con_1, consultas_con_8)

    # --- 20-22. Regresion de 5B/5C ------------------------------------------------------------
    def test_rutas_de_catalogo_y_detalle_siguen_funcionando(self):
        elemento = self.crear_elemento(mcu_id=8)

        self.assertEqual(
            self.client.get(reverse('marvel:catalogo')).status_code, 200,
        )
        respuesta = self.client.get(
            reverse('marvel:detalle', args=[elemento.pk]),
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Iron Man')

    def test_flujo_de_publicacion_de_5c_sigue_funcionando(self):
        cliente = self.crear_usuario('c5d-flujo-cliente')
        self.client.force_login(cliente)
        elemento = self.crear_elemento(mcu_id=9)

        respuesta = self.client.post(
            reverse('marvel:detalle', args=[elemento.pk]),
            {
                'calificacion': '4',
                'referencia_tematica': 'Tony Stark construye el traje.',
            },
            follow=True,
        )

        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(Resena.objects.count(), 1)
        resena = Resena.objects.get()
        self.assertTrue(resena.visible)
        self.assertContains(respuesta, '¡Reseña publicada!')

    def test_botones_de_moderacion_solo_para_admin(self):
        elemento = self.crear_elemento(mcu_id=10)
        self.crear_resena(
            self.crear_usuario('c5d-btn-autor'), elemento,
        )
        self.crear_resena(
            self.crear_usuario('c5d-btn-oculta'),
            elemento,
            calificacion=2,
            visible=False,
        )
        ruta = reverse('marvel:detalle', args=[elemento.pk])

        # Visitante, cliente y tecnico: sin botones de moderacion.
        for rol in (None, 'cliente', 'tecnico'):
            with self.subTest(rol=rol or 'visitante'):
                if rol:
                    self.client.force_login(
                        self.crear_usuario(f'c5d-btn-{rol}', rol),
                    )
                respuesta = self.client.get(ruta)
                self.assertNotContains(respuesta, 'resenas-boton-moderar')
                self.assertNotContains(respuesta, 'Ocultar')
                self.assertNotContains(respuesta, 'Restaurar')
                self.client.logout()

        # Admin: botones para ambas (Ocultar la visible, Restaurar la oculta).
        self.client.force_login(
            self.crear_usuario('c5d-btn-admin', 'administrador'),
        )
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Ocultar')
        self.assertContains(respuesta, 'Restaurar')

    # --- Blindajes extra -----------------------------------------------------------------------
    def test_moderar_resena_de_otro_elemento_responde_404(self):
        admin = self.crear_usuario('c5d-admin-404', 'administrador')
        self.client.force_login(admin)
        elemento_a = self.crear_elemento(mcu_id=11, nombre='Iron Man')
        elemento_b = self.crear_elemento(mcu_id=12, nombre='Thor')
        resena_de_b = self.crear_resena(
            self.crear_usuario('c5d-autor-404'), elemento_b,
        )

        # El id de la ruta no coincide con el elemento de la reseña.
        respuesta = self._moderar(elemento_a, resena_de_b, 'ocultar')

        self.assertEqual(respuesta.status_code, 404)
        resena_de_b.refresh_from_db()
        self.assertTrue(resena_de_b.visible)

    def test_moderar_en_elemento_inactivo_responde_404(self):
        admin = self.crear_usuario('c5d-admin-off', 'administrador')
        self.client.force_login(admin)
        elemento = self.crear_elemento(mcu_id=13, activo=False)
        resena = self.crear_resena(
            self.crear_usuario('c5d-autor-off'), elemento,
        )

        respuesta = self._moderar(elemento, resena, 'ocultar')

        self.assertEqual(respuesta.status_code, 404)
        resena.refresh_from_db()
        self.assertTrue(resena.visible)

