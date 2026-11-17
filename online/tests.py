from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.test import override_settings
from online.models import Preguntas, Respuesta, Usuario
from online.forms import PreguntasForm
from marvel.models import ElementoCatalogo
from online.ia_utils import MENSAJE_NO_DISPONIBLE, AsistenteIA


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

