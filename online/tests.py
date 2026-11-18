from unittest.mock import patch

import json
import re

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.test import override_settings
from online.constants import CATEGORIAS_PREGUNTA
from online.models import Auditoria, Preguntas, Respuesta, Usuario
from online.forms import PreguntasForm
from marvel.models import ElementoCatalogo
from online.ia_utils import (
    INSTRUCCIONES_CLASIFICADOR,
    INSTRUCCIONES_SISTEMA,
    MENSAJE_NO_DISPONIBLE,
    AsistenteIA,
)


class ConversationAccessTests(TestCase):
    def setUp(self):
        self.owner = self.create_user('owner', 'owner@example.com')
        self.other = self.create_user('other', 'other@example.com')
        self.question = Preguntas.objects.create(
            Titulo='Consulta',
            Pregunta='No inicia el juego',
            Fecha_creacion=timezone.now(),
            Usuario=self.owner,
        )

    def create_user(self, username, email, **fields):
        user = Usuario.objects.create(
            usuario=username,
            correo=email,
            **fields,
        )
        user.set_password('test-password-123')
        user.save()
        return user

    def test_user_cannot_view_another_users_conversation(self):
        self.client.force_login(self.other)

        response = self.client.get(
            reverse('respuestas', args=[self.other.id, self.question.idPregunta])
        )

        self.assertRedirects(response, reverse('inicio', args=[self.other.id]))

    def test_admin_and_technician_can_view_conversations(self):
        for username, email, role in (
            ('admin', 'admin@example.com', {'admin': True}),
            ('tech', 'tech@example.com', {'tecnico': True}),
        ):
            with self.subTest(role=username):
                user = self.create_user(username, email, **role)
                self.client.force_login(user)
                response = self.client.get(
                    reverse('respuestas', args=[user.id, self.question.idPregunta])
                )
                self.assertEqual(response.status_code, 200)

    def test_reply_uses_url_question_not_tampered_hidden_question(self):
        another_question = Preguntas.objects.create(
            Titulo='Otra consulta',
            Pregunta='No hay audio',
            Fecha_creacion=timezone.now(),
            Usuario=self.other,
        )
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('respuestas', args=[self.owner.id, self.question.idPregunta]),
            {
                'Respuesta': 'Prueba reiniciar el juego.',
                'id_Pregunta': another_question.idPregunta,
                'Usuario': self.other.id,
                'FechaHora': timezone.now().isoformat(),
            },
        )

        self.assertRedirects(
            response,
            reverse(
                'respuestas',
                args=[self.owner.id, self.question.idPregunta],
            ),
        )
        respuesta = Respuesta.objects.get()
        self.assertEqual(respuesta.id_Pregunta_id, self.question.idPregunta)
        self.assertEqual(respuesta.Usuario_id, self.owner.id)

    def test_inactive_users_cannot_log_in(self):
        self.owner.activo = False
        self.owner.save()

        response = self.client.post(
            reverse('Login'),
            {'Usuario': self.owner.usuario, 'password': 'test-password-123'},
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse('_auth_user_id' in self.client.session)
        self.assertTrue(response.context['form'].non_field_errors())

    @override_settings(IA_API_KEY='test-key')
    @patch('online.ia_utils.OpenAI')
    def test_openai_error_no_se_muestra_al_usuario(self, openai_cls):
        # El remoto falla: el asistente responde con el mensaje amable.
        openai_cls.return_value.chat.completions.create.side_effect = RuntimeError(
            'detalle interno de OpenAI'
        )

        respuesta = AsistenteIA().generar_respuesta_automatica(
            'Mi juego funciona lento'
        )

        self.assertEqual(respuesta, MENSAJE_NO_DISPONIBLE)
        self.assertNotIn('detalle interno de OpenAI', respuesta)

class AsistenteIAClassificationTests(TestCase):
    @override_settings(IA_API_KEY='test-key')
    @patch('online.ia_utils.OpenAI')
    def test_clasificar_preguntas_devuelve_otros_si_la_ia_falla(
        self, openai_cls
    ):
        openai_cls.return_value.chat.completions.create.side_effect = RuntimeError(
            'fallo de OpenAI'
        )

        resultado = AsistenteIA().clasificar_preguntas([
            'No funciona el mouse',
            'El juego va lento',
        ])

        # Sin respaldo local: cada texto queda como 'otros', sin excepcion.
        self.assertEqual(resultado, ['otros', 'otros'])

class RedireccionesServidorTests(TestCase):
    """Las redirecciones por rol se resuelven en el servidor (HTTP 302)."""

    def crear_usuario(self, username, **fields):
        user = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            **fields,
        )
        user.set_password('test-password-123')
        user.save()
        return user

    def test_index_anonimo_responde_200(self):
        response = self.client.get(reverse('index'))

        self.assertEqual(response.status_code, 200)

class IndexBloque2CTests(TestCase):
    """Bloque 2C: '/' visible para todos los roles (sin redireccion
    automatica) y header MarvelCallCenter con navegacion coherente."""

    def _crear_usuario(self, username, rol='cliente'):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def test_index_visible_para_visitante_y_todos_los_roles(self):
        # Visitante
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)

        for rol in ('cliente', 'tecnico', 'administrador'):
            with self.subTest(rol=rol):
                user = self._crear_usuario(f'index-{rol}', rol)
                self.client.force_login(user)
                response = self.client.get(reverse('index'))
                self.assertEqual(response.status_code, 200)

    def test_header_muestra_marvelcallcenter_sin_textos_obsoletos(self):
        response = self.client.get(reverse('index'))
        contenido = response.content.decode('utf-8')

        self.assertIn('CallCenterGamer', contenido)
        self.assertNotIn('CallCenterGamer', contenido)
        self.assertNotIn('Call of Gamers', contenido)
        self.assertNotIn('Call Center Gamer', contenido)

    def test_enlaces_del_header_resuelven(self):
        rutas = {
            'index': reverse('index'),
            'catalogo': reverse('marvel:catalogo'),
            'Login': reverse('Login'),
            'Register': reverse('Register'),
        }

        response = self.client.get(reverse('index'))
        for nombre, href in rutas.items():
            with self.subTest(enlace=nombre):
                self.assertContains(response, f'href="{href}"')

        for nombre, href in rutas.items():
            with self.subTest(destino=nombre):
                self.assertEqual(self.client.get(href).status_code, 200)

    def test_header_enlaza_universo_marvel(self):
        """Bloque 4C: el header incluye 'Universo Marvel' a /marvel/,
        cuya landing ya existe."""
        response = self.client.get(reverse('index'))

        self.assertContains(response, 'Universo Marvel')
        self.assertContains(response, 'href="/marvel/"')
        self.assertEqual(self.client.get(reverse('marvel:raiz')).status_code, 200)
        # Ninguna referencia a nombres de ruta inexistentes.
        self.assertNotContains(response, 'marvel/landing')

    def test_cta_del_panel_corresponde_al_rol(self):
        cliente = self._crear_usuario('cta-cliente', 'cliente')
        self.client.force_login(cliente)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('inicio', args=[cliente.id]))

        for rol in ('tecnico', 'administrador'):
            with self.subTest(rol=rol):
                user = self._crear_usuario(f'cta-{rol}', rol)
                self.client.force_login(user)
                response = self.client.get(reverse('index'))
                self.assertContains(response, reverse('administracion'))

    def test_visitante_ve_login_y_registro_sin_cta_de_panel(self):
        response = self.client.get(reverse('index'))

        self.assertContains(response, reverse('Login'))
        self.assertContains(response, reverse('Register'))
        self.assertNotContains(response, reverse('administracion'))
        self.assertNotContains(response, '/Inicio/')

    def test_redireccion_despues_del_login_se_conserva(self):
        for rol in ('cliente', 'tecnico', 'administrador'):
            with self.subTest(rol=rol):
                user = self._crear_usuario(f'login-{rol}', rol)
                response = self.client.post(
                    reverse('Login'),
                    {'Usuario': user.usuario, 'password': 'test-password-123'},
                )
                destino = (
                    reverse('inicio', args=[user.id])
                    if rol == 'cliente'
                    else reverse('administracion')
                )
                self.assertRedirects(response, destino)

    def test_ids_unicos_en_index(self):
        response = self.client.get(reverse('index'))
        ids = re.findall(r'id="([^"]+)"', response.content.decode('utf-8'))

        duplicados = {identificador for identificador in ids
                      if ids.count(identificador) > 1}
        self.assertEqual(duplicados, set())
        self.assertIn('ctaIngresar', ids)
        self.assertNotIn('btnIngresar', ids)

class TicketsConElementoMarvelTests(TestCase):
    """Fase C1.2: selector opcional de elemento Marvel al crear tickets."""

    def setUp(self):
        self.dueño = self._crear_usuario('dueno-c12', 'dueno@example.com')
        self.elemento = ElementoCatalogo.objects.create(
            mcu_id=249,
            tipo='movie',
            nombre='Superman',
            activo=True,
        )
        self.otro_elemento = ElementoCatalogo.objects.create(
            mcu_id=250,
            tipo='tvshow',
            nombre='Loki',
            activo=True,
        )
        self.question_anterior = Preguntas.objects.create(
            Titulo='Consulta previa',
            Pregunta='No carga la lista de amigos',
            Fecha_creacion=timezone.now(),
            Usuario=self.dueño,
        )
        self.client.force_login(self.dueño)

    def _crear_usuario(self, username, email):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=email,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def _datos_ticket(self):
        return {
            'Titulo': 'Ticket con Marvel',
            'Pregunta': 'La serie tiene un error de descripcion',
            'Usuario': self.dueño.id,
            'Fecha_creacion': timezone.now().isoformat(),
        }

    def _crear_ticket(self):
        """Crea un ticket via POST (IA simulada por quien llama) y
        devuelve la respuesta."""
        return self.client.post(
            reverse('inicio', args=[self.dueño.id]),
            self._datos_ticket(),
        )

    @patch('online.views.AsistenteIA')
    def test_crear_ticket_con_elemento_activo(self, asistente_cls):
        asistente_cls.return_value.clasificar_pregunta.return_value = 'otros'

        datos = self._datos_ticket()
        datos['elemento_catalogo'] = self.elemento.pk
        self.client.post(
            reverse('inicio', args=[self.dueño.id]),
            datos,
        )

        pregunta = Preguntas.objects.get(Titulo='Ticket con Marvel')
        self.assertEqual(pregunta.elemento_catalogo_id, self.elemento.pk)
        self.assertEqual(pregunta.Usuario_id, self.dueño.id)

    def _datos_formulario(self, **extra):
        datos = {
            'Titulo': 'Titulo',
            'Pregunta': 'Texto',
            'Usuario': self.dueño.id,
            'Fecha_creacion': timezone.now().isoformat(),
        }
        datos.update(extra)
        return datos

    def test_formulario_rechaza_elemento_inactivo(self):
        self.elemento.activo = False
        self.elemento.save()

        form = PreguntasForm(
            data=self._datos_formulario(
                elemento_catalogo=self.elemento.pk,
            ),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('elemento_catalogo', form.errors)
        self.assertNotIn('Usuario', form.errors)

class VinculoMarvelC13Tests(TestCase):
    """Fase C1.3: visualizacion del vinculo y auditoria de su cambio."""

    def setUp(self):
        self.dueño = self._crear_usuario('dueno-c13', 'dueno@example.com')
        self.admin = self._crear_usuario(
            'admin-c13', 'admin-c13@example.com', rol='administrador'
        )
        self.elemento = ElementoCatalogo.objects.create(
            mcu_id=300,
            tipo='movie',
            nombre='Superman',
            activo=True,
        )
        self.otro_elemento = ElementoCatalogo.objects.create(
            mcu_id=301,
            tipo='tvshow',
            nombre='Loki',
            activo=True,
        )
        self.question = Preguntas.objects.create(
            Titulo='Consulta con Marvel',
            Pregunta='Error en la ficha de la serie',
            Fecha_creacion=timezone.now(),
            Usuario=self.dueño,
            elemento_catalogo=self.elemento,
        )

    def _crear_usuario(self, username, email, **fields):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=email,
            **fields,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def _datos_admin(self):
        return {
            'Titulo': self.question.Titulo,
            'Pregunta': self.question.Pregunta,
            'Usuario': self.dueño.id,
            'Fecha_creacion': self.question.Fecha_creacion.isoformat(),
        }

    def test_ticket_con_elemento_visible_en_conversacion(self):
        self.client.force_login(self.dueño)

        response = self.client.get(
            reverse(
                'respuestas',
                args=[self.dueño.id, self.question.idPregunta],
            )
        )

        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode('utf-8')
        self.assertIn('Elemento Marvel', contenido)
        self.assertIn('Pelicula: Superman', contenido)
        self.assertIn(f'/marvel/{self.elemento.pk}/', contenido)

    def test_cliente_ajeno_no_puede_ver_el_ticket(self):
        ajeno = self._crear_usuario('ajeno-c13', 'ajeno@example.com')
        self.client.force_login(ajeno)

        response = self.client.get(
            reverse('respuestas', args=[ajeno.id, self.question.idPregunta])
        )

        self.assertRedirects(response, reverse('inicio', args=[ajeno.id]))


class CategoriasMarvelBloque3ATests(TestCase):
    """Bloque 3A: categorias del universo Marvel con compatibilidad de
    tickets historicos (los 4 reales usan 'otros', codigo conservado)."""

    def _crear_usuario(self, username, rol='cliente'):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def _ticket_historico(self, usuario):
        return Preguntas.objects.create(
            Titulo='Consulta historica',
            Pregunta='Consulta previa al cambio de categorias',
            Fecha_creacion=timezone.now(),
            Usuario=usuario,
            categoria='otros',
        )

    def test_categorias_marvel_disponibles_en_tickets_nuevos(self):
        valores = {valor for valor, _ in CATEGORIAS_PREGUNTA}
        esperados = {
            'videojuegos', 'merchandising', 'peliculas', 'series', 'comics',
            'figuras_juguetes', 'eventos', 'cuenta', 'pagos', 'otros',
        }
        self.assertEqual(valores, esperados)

        # La vista asigna al ticket nuevo la categoria devuelta por la IA
        # (simulada): una categoria Marvel es valida y se guarda.
        dueno = self._crear_usuario('cat-cliente', 'cliente')
        self.client.force_login(dueno)
        with patch('online.views.AsistenteIA') as asistente_cls:
            asistente_cls.return_value.clasificar_pregunta.return_value = (
                'peliculas'
            )
            self.client.post(
                reverse('inicio', args=[dueno.id]),
                {
                    'Titulo': 'Duda de estreno',
                    'Pregunta': 'Cuando llega la pelicula al catalogo?',
                    'Usuario': dueno.id,
                    'Fecha_creacion': timezone.now().isoformat(),
                },
            )
        ticket = Preguntas.objects.get(Titulo='Duda de estreno')
        self.assertEqual(ticket.categoria, 'peliculas')

    def test_categorias_gaming_no_seleccionables(self):
        valores = {valor for valor, _ in CATEGORIAS_PREGUNTA}
        for antigua in ('hardware', 'software', 'conexion', 'rendimiento', 'pago'):
            with self.subTest(categoria=antigua):
                self.assertNotIn(antigua, valores)

        # El modelo ya no acepta valores de la lista anterior.
        with self.assertRaises(ValidationError):
            usuario = self._crear_usuario('cat-validacion', 'cliente')
            Preguntas(
                Titulo='Invalida',
                Pregunta='Texto de prueba',
                Fecha_creacion=timezone.now(),
                Usuario=usuario,
                categoria='hardware',
            ).full_clean()

    def test_tickets_antiguos_visibles(self):
        dueno = self._crear_usuario('cat-viejo', 'cliente')
        self._ticket_historico(dueno)

        # El cliente sigue viendo su ticket con la etiqueta 'Otros'.
        self.client.force_login(dueno)
        response = self.client.get(reverse('inicio', args=[dueno.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Consulta historica')
        self.assertContains(response, 'Otros')

        # Y el panel administrativo tambien.
        self._crear_usuario('cat-admin', 'administrador')
        admin = Usuario.objects.get(usuario='cat-admin')
        self.client.force_login(admin)
        response = self.client.get(reverse('administracion'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Consulta historica')

    def test_edicion_segura_de_ticket_historico(self):
        from administracion.servicios import tickets as servicios_tickets

        admin = self._crear_usuario('cat-edit-admin', 'administrador')
        dueno = self._crear_usuario('cat-edit-dueno', 'cliente')
        historico = self._ticket_historico(dueno)
        datos = {
            'Titulo': historico.Titulo,
            'Pregunta': historico.Pregunta,
            'Usuario': dueno.id,
            'Fecha_creacion': historico.Fecha_creacion.isoformat(),
        }

        # Sin cambio de texto: la categoria historica se conserva.
        resultado = servicios_tickets.modificar(
            historico.idPregunta, datos, admin
        )
        self.assertTrue(resultado['guardado'])
        historico.refresh_from_db()
        self.assertEqual(historico.categoria, 'otros')
        self.assertEqual(historico.Usuario_id, dueno.id)
        self.assertTrue(
            Auditoria.objects.filter(
                pregunta=historico, accion='modificar_pregunta'
            ).exists()
        )

        # Con cambio de texto: la reclasificacion (IA simulada) guarda una
        # categoria valida de la lista nueva.
        datos['Pregunta'] = 'Consulta sobre el merchandising de la serie'
        with patch('administracion.servicios.tickets.AsistenteIA') as ia_cls:
            ia_cls.return_value.clasificar_pregunta.return_value = (
                'merchandising'
            )
            resultado = servicios_tickets.modificar(
                historico.idPregunta, datos, admin
            )
        self.assertTrue(resultado['guardado'])
        historico.refresh_from_db()
        self.assertEqual(historico.categoria, 'merchandising')

    def test_filtros_y_estadisticas_compatibles(self):
        from administracion.servicios import analytics as servicios_analytics

        dueno = self._crear_usuario('cat-stats', 'cliente')
        self._ticket_historico(dueno)
        admin = self._crear_usuario('cat-stats-admin', 'administrador')
        self.client.force_login(admin)

        # Filtro del panel por la categoria historica 'otros'.
        response = self.client.get(
            reverse('administracion'), {'categoria': 'otros'}
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Consulta historica')

        # Analytics etiqueta correctamente la categoria almacenada.
        contexto = servicios_analytics.construir_contexto(dias=7)
        etiquetas = [
            item['etiqueta'] for item in contexto['categorias_lista']
        ]
        self.assertIn('Otros', etiquetas)
        self.assertEqual(contexto['total_preguntas_mes'], 1)

        # Una categoria Marvel recien creada tambien queda etiquetada.
        Preguntas.objects.create(
            Titulo='Ticket series',
            Pregunta='Consulta sobre una serie del catalogo',
            Fecha_creacion=timezone.now(),
            Usuario=dueno,
            categoria='series',
        )
        contexto = servicios_analytics.construir_contexto(dias=7)
        por_codigo = {
            item['categoria']: item['etiqueta']
            for item in contexto['categorias_lista']
        }
        self.assertEqual(por_codigo.get('series'), 'Series')

    def test_permisos_existentes_intactos(self):
        cliente = self._crear_usuario('cat-permiso', 'cliente')
        self.client.force_login(cliente)

        response = self.client.get(reverse('administracion'))

        self.assertRedirects(response, reverse('inicio', args=[cliente.id]))


class _RespuestaIA:
    """Objeto minimo con la forma que _contenido() espera del SDK."""

    def __init__(self, contenido):
        opcion = type(
            'Opcion',
            (),
            {'message': type('Mensaje', (), {'content': contenido})()},
        )
        self.choices = [opcion]


@override_settings(IA_API_KEY='test-key')
class AsistenteIABloque3BTests(TestCase):
    """Bloque 3B: clasificacion y asistente en el contexto Marvel.

    Todas las respuestas del proveedor son simuladas (sin llamadas
    reales a Groq). El contrato de clasificar_preguntas no cambia:
    una sola llamada por lote, mismo orden, 'otros' como respaldo.
    """

    # Consultas representativas de cada categoria Marvel (3A).
    CONSULTAS = [
        ('¿Cuándo estará disponible la película Vengadores en el catálogo?',
         'peliculas'),
        ('¿La serie Loki tendrá más temporadas?', 'series'),
        ('¿Qué cómic explica el origen del personaje Rocket?', 'comics'),
        ('¿Cuándo sale el videojuego de Marvel inspirado en la saga?',
         'videojuegos'),
        ('¿Tienen poleras oficiales de merchandising Marvel?',
         'merchandising'),
        ('¿Cuándo llega la figura coleccionable de Iron Man?',
         'figuras_juguetes'),
        ('¿Habrá actividades para niños en el evento de la tienda?',
         'eventos'),
        ('¿Cómo cambio la contraseña de mi cuenta?', 'cuenta'),
        ('¿Puedo pagar con tarjeta de crédito mi compra?', 'pagos'),
    ]

    REGLAS_SIMULADAS = [
        ('contraseña', 'cuenta'),
        ('tarjeta', 'pagos'),
        ('película', 'peliculas'),
        ('serie', 'series'),
        ('cómic', 'comics'),
        ('videojuego', 'videojuegos'),
        ('merchandising', 'merchandising'),
        ('figura', 'figuras_juguetes'),
        ('evento', 'eventos'),
    ]

    def _clasificador_simulado(self, llamadas):
        """Simula al modelo: clasifica por palabras clave usando el
        contexto que el propio prompt entrega y devuelve JSON."""

        def simular(messages, max_tokens=None):
            contenido = messages[-1]['content']
            llamadas.append(contenido)
            bloque = (
                contenido
                .split('<preguntas>')[1]
                .split('</preguntas>')[0]
                .strip()
            )
            textos = [
                linea.split('. ', 1)[1]
                for linea in bloque.splitlines()
            ]
            resultado = []
            for texto in textos:
                texto_bajo = texto.lower()
                categoria = 'otros'
                for clave, valor in self.REGLAS_SIMULADAS:
                    if clave in texto_bajo:
                        categoria = valor
                        break
                resultado.append(categoria)
            return _RespuestaIA(json.dumps(resultado))

        return simular

    def test_clasificacion_por_categoria_marvel(self):
        for codigo_esperado in (
            'peliculas', 'series', 'comics', 'videojuegos', 'merchandising',
            'figuras_juguetes', 'eventos', 'cuenta', 'pagos',
        ):
            with self.subTest(categoria=codigo_esperado):
                consultas = [
                    texto
                    for texto, codigo in self.CONSULTAS
                    if codigo == codigo_esperado
                ]
                with patch.object(
                    AsistenteIA,
                    '_llamar_remoto',
                    side_effect=self._clasificador_simulado([]),
                ) as simulado:
                    resultado = AsistenteIA().clasificar_preguntas(consultas)
                self.assertEqual(resultado, [codigo_esperado] * len(consultas))
                simulado.assert_called_once()

    def test_clasificador_recibe_las_diez_categorias_marvel(self):
        """El prompt del clasificador lista los codigos exactos de la
        lista vigente (sin duplicarlos en otro archivo)."""
        llamadas = []
        with patch.object(
            AsistenteIA,
            '_llamar_remoto',
            side_effect=self._clasificador_simulado(llamadas),
        ):
            AsistenteIA().clasificar_preguntas(['¿Qué hay de nuevo?'])

        contenido = llamadas[0]
        for valor, _ in CATEGORIAS_PREGUNTA:
            with self.subTest(categoria=valor):
                self.assertIn(valor, contenido)

    def test_categoria_invalida_del_proveedor_cae_a_otros(self):
        llamada_invalida = _RespuestaIA('["hardware"]')

        with patch.object(
            AsistenteIA, '_llamar_remoto', return_value=llamada_invalida
        ):
            resultado = AsistenteIA().clasificar_preguntas(
                ['¿Cuándo llega la película al catálogo?']
            )

        self.assertEqual(resultado, ['otros'])

    def test_respuesta_malformada_del_proveedor_cae_a_otros(self):
        respuesta_malformada = _RespuestaIA(
            'Lo siento, no puedo clasificar eso.'
        )

        with patch.object(
            AsistenteIA, '_llamar_remoto', return_value=respuesta_malformada
        ):
            resultado = AsistenteIA().clasificar_preguntas(
                ['¿Qué cómic recomiendas?', '¿Cuándo llega la serie?']
            )

        self.assertEqual(resultado, ['otros', 'otros'])

    @override_settings(IA_API_KEY='')
    def test_sin_clave_clasifica_en_otros_sin_llamar_al_proveedor(self):
        with patch.object(AsistenteIA, '_llamar_remoto') as simulado:
            resultado = AsistenteIA().clasificar_preguntas(
                ['¿Qué película llegará primero?']
            )

        self.assertEqual(resultado, ['otros'])
        simulado.assert_not_called()

    def test_contrato_de_retorno_y_orden_se_conservan(self):
        textos = [texto for texto, _ in reversed(self.CONSULTAS)]
        esperados = [codigo for _, codigo in reversed(self.CONSULTAS)]

        # clasificar_preguntas: un solo lote -> UNA llamada remota.
        llamadas = []
        with patch.object(
            AsistenteIA,
            '_llamar_remoto',
            side_effect=self._clasificador_simulado(llamadas),
        ):
            resultado = AsistenteIA().clasificar_preguntas(textos)
        self.assertEqual(resultado, esperados)
        self.assertEqual(len(llamadas), 1)

        # clasificar_pregunta reutiliza el flujo por lote y devuelve un
        # solo valor (su propio lote de 1).
        llamadas_unica = []
        with patch.object(
            AsistenteIA,
            '_llamar_remoto',
            side_effect=self._clasificador_simulado(llamadas_unica),
        ):
            clasificacion_unica = AsistenteIA().clasificar_pregunta(textos[0])
        self.assertEqual(clasificacion_unica, esperados[0])
        self.assertEqual(len(llamadas_unica), 1)

    def test_respuesta_automatica_devuelve_el_contenido_del_proveedor(self):
        with patch.object(
            AsistenteIA,
            '_llamar_remoto',
            return_value=_RespuestaIA(
                'Esa película llega al catálogo la próxima semana.'
            ),
        ):
            respuesta = AsistenteIA().generar_respuesta_automatica(
                '¿Cuándo llega la película al catálogo?'
            )

        self.assertEqual(
            respuesta,
            'Esa película llega al catálogo la próxima semana.',
        )

    def test_instrucciones_activas_sin_referencias_gaming(self):
        self.assertIn('CallCenterGamer', INSTRUCCIONES_SISTEMA)
        self.assertIn('CallCenterGamer', INSTRUCCIONES_CLASIFICADOR)
        self.assertNotIn('gaming', INSTRUCCIONES_SISTEMA)
        self.assertNotIn('hardware', INSTRUCCIONES_SISTEMA)

    def test_asistente_de_inicio_sin_textos_gaming(self):
        usuario = Usuario.objects.create(
            usuario='ia-texto',
            correo='ia-texto@example.com',
        )
        usuario.set_password('test-password-123')
        usuario.save()
        self.client.force_login(usuario)

        response = self.client.get(reverse('inicio', args=[usuario.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'problemas de hardware')
        self.assertNotContains(response, 'juego lento')
        self.assertContains(response, 'videojuegos de Marvel')


class LandingBloque4BTests(TestCase):
    """Bloque 4B: landing '/' del call center Marvel.

    Los estados por rol (200 para visitante/cliente/tecnico/admin,
    CTA del panel, Login/Registro para visitantes y ids unicos) ya
    estan cubiertos por IndexBloque2CTests; aqui se prueba el contenido
    nuevo de la landing.
    """

    def _crear_usuario(self, username, rol='cliente'):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def test_landing_muestra_las_secciones_principales(self):
        response = self.client.get(reverse('index'))
        contenido = response.content.decode('utf-8')

        self.assertIn('¿Qué puedes hacer?', contenido)
        self.assertIn('¿Cómo funciona?', contenido)
        self.assertIn('Bienvenido a', contenido)
        self.assertIn('Explorar el catálogo', contenido)
        # Descripcion del servicio: catalogo + consultas + tickets.
        self.assertIn('películas y series Marvel', contenido)
        self.assertIn('tickets', contenido)

    def test_comentarios_de_plantilla_no_aparecen_en_el_html(self):
        """Regresion 7A: los comentarios {# ... #} multilínea no son
        válidos en Django (solo de una línea) y su texto crudo se
        colaba en la landing justo debajo del menú. Deben renderizar
        vacío: ni el texto del comentario ni sintaxis de plantilla
        visible en el HTML generado (cualquier rol)."""
        for rol in (None, 'cliente', 'administrador'):
            with self.subTest(rol=rol):
                if rol is None:
                    self.client.logout()
                else:
                    self.client.force_login(
                        self._crear_usuario(f'landing-{rol}-7a', rol),
                    )
                response = self.client.get(reverse('index'))
                contenido = response.content.decode('utf-8')

                self.assertNotIn(
                    'Landing principal del Call Center Marvel', contenido,
                )
                self.assertNotIn('{#', contenido)
                self.assertNotIn('#}', contenido)
                self.assertNotIn('{% comment', contenido)
                self.assertNotIn('{%', contenido)
                self.assertNotIn('%}', contenido)

    def test_cta_catalogo_apunta_a_la_ruta_real(self):
        response = self.client.get(reverse('index'))

        # El CTA del catalogo siempre usa el nombre de URL del catalogo
        # (ruta real /marvel/catalogo/ de 4A), nunca la raiz /marvel/.
        self.assertContains(
            response, f'href="{reverse("marvel:catalogo")}"'
        )
        # El enlace a /marvel/ que aparece es el de "Universo Marvel"
        # del header (Bloque 4C), no un CTA de la landing.

    def test_accesos_por_rol_en_landing(self):
        cliente = self._crear_usuario('landing-cliente', 'cliente')
        self.client.force_login(cliente)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('inicio', args=[cliente.id]))
        # Un cliente no recibe acceso al panel administrativo.
        self.assertNotContains(response, reverse('administracion'))

        admin = self._crear_usuario('landing-admin', 'administrador')
        self.client.force_login(admin)
        response = self.client.get(reverse('index'))
        self.assertContains(response, reverse('administracion'))

    def test_sin_enlaces_a_funcionalidades_inexistentes(self):
        response = self.client.get(reverse('index'))

        self.assertNotContains(response, 'Reseñas')
        self.assertNotContains(response, 'resenas')
        self.assertNotContains(response, 'marvel/landing')

    def test_hero_usa_recurso_local_del_proyecto(self):
        response = self.client.get(reverse('index'))

        self.assertContains(response, 'data-carrusel-peliculas')
        self.assertContains(response, 'peliculas-slides')
        self.assertContains(response, 'avengers-endgame.jpg')
        self.assertContains(response, 'Póster de Avengers: Endgame')

    def test_rutas_de_4a_siguen_funcionando(self):
        # La landing 4B no rompe el catálogo ni la landing de 4C.
        respuesta_catalogo = self.client.get(reverse('marvel:catalogo'))
        self.assertEqual(respuesta_catalogo.status_code, 200)

        respuesta_raiz = self.client.get(reverse('marvel:raiz'))
        self.assertEqual(respuesta_raiz.status_code, 200)
        self.assertContains(respuesta_raiz, 'Universo')

