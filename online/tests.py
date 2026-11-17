from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from django.test import override_settings
from online.models import Auditoria, Preguntas, Respuesta, Usuario
from online.forms import PreguntasForm, PreguntaAdminForm
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

    def test_logout_requires_post(self):
        self.client.force_login(self.owner)

        response = self.client.get(reverse('Logout'))

        self.assertEqual(response.status_code, 405)
        self.assertTrue(self.client.session.get('_auth_user_id'))

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

    def test_categoria_por_defecto_es_otros(self):
        self.assertEqual(self.question.categoria, 'otros')

    @patch('online.views.AsistenteIA')
    def test_inicio_guarda_la_categoria_al_crear_pregunta(self, asistente_cls):
        asistente_cls.return_value.clasificar_pregunta.return_value = 'hardware'
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('inicio', args=[self.owner.id]),
            {
                'Titulo': 'Mouse',
                'Pregunta': 'No funciona el mouse',
                'Usuario': self.owner.id,
                'Fecha_creacion': timezone.now().isoformat(),
            },
        )

        self.assertRedirects(response, reverse('inicio', args=[self.owner.id]))
        pregunta = Preguntas.objects.get(Titulo='Mouse')
        self.assertEqual(pregunta.categoria, 'hardware')
        asistente_cls.return_value.clasificar_pregunta.assert_called_once_with(
            'No funciona el mouse'
        )

    @patch(
        'online.views.RecomendadorIA.recomendar_respuestas_similares',
        return_value=[],
    )
    @patch(
        'online.views.AsistenteIA.generar_respuesta_automatica',
        return_value='Respuesta de prueba',
    )
    def test_inicio_conecta_la_consulta_con_el_asistente(
        self,
        generar_respuesta,
        recomendar_respuestas,
    ):
        self.client.force_login(self.owner)

        response = self.client.get(
            reverse('inicio', args=[self.owner.id]),
            {'buscar_ayuda': 'Mi juego funciona lento'},
        )

        self.assertEqual(response.status_code, 200)
        generar_respuesta.assert_called_once_with('Mi juego funciona lento')
        recomendar_respuestas.assert_called_once_with('Mi juego funciona lento')
        self.assertEqual(
            response.context['sugerencias_ia'],
            {
                'consulta_original': 'Mi juego funciona lento',
                'respuesta_automatica': 'Respuesta de prueba',
                'recomendaciones': [],
            },
        )

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

    @override_settings(IA_API_KEY='test-key')
    @patch('online.ia_utils.OpenAI')
    def test_generar_respuesta_nunca_propaga_excepcion_del_sdk(self, openai_cls):
        # Cualquier excepcion del SDK se convierte en el mensaje amable.
        openai_cls.return_value.chat.completions.create.side_effect = Exception(
            'fallo del SDK'
        )

        respuesta = AsistenteIA().generar_respuesta_automatica(
            'Mi juego funciona lento'
        )

        self.assertEqual(respuesta, MENSAJE_NO_DISPONIBLE)


class AsistenteIAClassificationTests(TestCase):
    @override_settings(IA_API_KEY='test-key')
    @patch('online.ia_utils.OpenAI')
    def test_clasificar_preguntas_usa_una_sola_llamada(self, openai_cls):
        openai_cls.return_value.chat.completions.create.return_value = Mock(
            choices=[
                Mock(message=Mock(content='["hardware", "software"]'))
            ]
        )

        resultado = AsistenteIA().clasificar_preguntas([
            'No funciona el mouse',
            'El juego va lento',
        ])

        self.assertEqual(resultado, ['hardware', 'software'])
        self.assertEqual(
            openai_cls.return_value.chat.completions.create.call_count,
            1,
        )

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

    @patch('online.ia_utils.OpenAI')
    def test_clasificar_preguntas_vacias_no_llama_a_openai(self, openai_cls):
        resultado = AsistenteIA().clasificar_preguntas([])

        self.assertEqual(resultado, [])
        openai_cls.assert_not_called()


class AsistenteIAMotorTests(TestCase):
    """Pruebas del cliente remoto y del comportamiento sin clave (sin red real)."""

    @override_settings(IA_API_KEY='')
    @patch('online.ia_utils.OpenAI')
    def test_sin_clave_devuelve_mensaje_no_disponible(self, openai_cls):
        asistente = AsistenteIA()

        self.assertEqual(asistente.motor_activo(), 'sin_clave')
        self.assertFalse(asistente.disponible())

        respuesta = asistente.generar_respuesta_automatica(
            'No funciona el mouse'
        )

        self.assertEqual(respuesta, MENSAJE_NO_DISPONIBLE)
        openai_cls.assert_not_called()

    @override_settings(
        IA_API_KEY='gsk_prueba',
        IA_BASE_URL='https://api.groq.com/openai/v1',
        IA_TIMEOUT=12,
    )
    @patch('online.ia_utils.OpenAI')
    def test_cliente_remoto_usa_base_url_y_timeout(self, openai_cls):
        openai_cls.return_value.chat.completions.create.return_value = Mock(
            choices=[Mock(message=Mock(content='Respuesta remota'))]
        )

        asistente = AsistenteIA()
        self.assertEqual(asistente.motor_activo(), 'groq')

        respuesta = asistente.generar_respuesta_automatica('Mi juego va lento')

        self.assertEqual(respuesta, 'Respuesta remota')
        argumentos = openai_cls.call_args.kwargs
        self.assertEqual(argumentos['api_key'], 'gsk_prueba')
        self.assertEqual(
            argumentos['base_url'],
            'https://api.groq.com/openai/v1',
        )
        self.assertEqual(argumentos['timeout'], 12)
        self.assertEqual(argumentos['max_retries'], 1)


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

    def test_index_redirige_al_cliente_a_su_inicio(self):
        cliente = self.crear_usuario('cliente-index')
        self.client.force_login(cliente)

        response = self.client.get(reverse('index'))

        self.assertRedirects(response, reverse('inicio', args=[cliente.id]))

    def test_index_redirige_al_administrador_al_panel(self):
        admin = self.crear_usuario('admin-index', rol='administrador')
        self.client.force_login(admin)

        response = self.client.get(reverse('index'))

        self.assertRedirects(response, reverse('administracion'))

    def test_index_redirige_al_tecnico_al_panel(self):
        tecnico = self.crear_usuario('tecnico-index', rol='tecnico')
        self.client.force_login(tecnico)

        response = self.client.get(reverse('index'))

        self.assertRedirects(response, reverse('administracion'))

    def test_login_y_register_redirigen_al_cliente_logueado(self):
        cliente = self.crear_usuario('cliente-auth')
        self.client.force_login(cliente)

        for nombre in ('Login', 'Register'):
            with self.subTest(vista=nombre):
                response = self.client.get(reverse(nombre))
                self.assertRedirects(
                    response,
                    reverse('inicio', args=[cliente.id]),
                )

    @patch('online.views.AsistenteIA')
    def test_inicio_redirige_al_tecnico_sin_llamar_a_la_ia(self, asistente_cls):
        tecnico = self.crear_usuario('tecnico-inicio', rol='tecnico')
        self.client.force_login(tecnico)

        response = self.client.get(
            reverse('inicio', args=[tecnico.id]),
            {'buscar_ayuda': 'Mi juego va lento'},
        )

        self.assertRedirects(response, reverse('administracion'))
        asistente_cls.assert_not_called()


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
    def test_crear_ticket_sin_elemento_marvel(self, asistente_cls):
        asistente_cls.return_value.clasificar_pregunta.return_value = 'otros'

        self._crear_ticket()

        pregunta = Preguntas.objects.get(Titulo='Ticket con Marvel')
        self.assertIsNone(pregunta.elemento_catalogo)

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

    def test_formulario_acepta_elemento_activo(self):
        form = PreguntasForm(
            data=self._datos_formulario(
                elemento_catalogo=self.elemento.pk,
            ),
        )
        self.assertTrue(form.is_valid(), form.errors)

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

    def test_formulario_rechaza_identificador_inexistente(self):
        form = PreguntasForm(
            data=self._datos_formulario(
                elemento_catalogo=self.elemento.pk + 9999,
            ),
        )
        self.assertFalse(form.is_valid())
        self.assertIn('elemento_catalogo', form.errors)

    def test_preseleccion_por_get_con_elemento_activo(self):
        response = self.client.get(
            reverse('inicio', args=[self.dueño.id]),
            {'elemento': self.elemento.pk},
        )

        self.assertEqual(response.status_code, 200)
        form = response.context['form']
        self.assertEqual(
            form['elemento_catalogo'].initial,
            self.elemento.pk,
        )
        self.assertContains(
            response,
            '<option value="{}" selected>'.format(self.elemento.pk),
        )

    def test_preseleccion_por_get_invalido_se_ignora(self):
        for valor in ('no-numero', '-5', '99999'):
            with self.subTest(valor=valor):
                response = self.client.get(
                    reverse('inicio', args=[self.dueño.id]),
                    {'elemento': valor},
                )
                self.assertEqual(response.status_code, 200)
                form = response.context['form']
                self.assertNotIn('elemento_catalogo', form.initial or {})

    def test_etiquetas_del_selector_distinguen_tipo(self):
        response = self.client.get(
            reverse('inicio', args=[self.dueño.id]),
        )

        contenido = response.content.decode('utf-8')
        self.assertIn('Pelicula: Superman', contenido)
        self.assertIn('Serie: Loki', contenido)
        self.assertIn('Sin elemento Marvel', contenido)

    @patch('online.views.AsistenteIA')
    def test_tickets_anteriores_quedan_intactos_tras_crear_con_marvel(
        self, asistente_cls,
    ):
        asistente_cls.return_value.clasificar_pregunta.return_value = 'otros'

        datos = self._datos_ticket()
        datos['elemento_catalogo'] = self.otro_elemento.pk
        self.client.post(
            reverse('inicio', args=[self.dueño.id]),
            datos,
        )

        anterior = Preguntas.objects.get(pk=self.question_anterior.pk)
        self.assertIsNone(anterior.elemento_catalogo)
        self.assertEqual(anterior.Usuario_id, self.dueño.id)
        self.assertEqual(
            Preguntas.objects.count(),
            2,
        )

    def test_select_marvel_solo_muestra_elementos_activos(self):
        inactivo = ElementoCatalogo.objects.create(
            mcu_id=251,
            tipo='tvshow',
            nombre='Serie oculta',
            activo=False,
        )

        response = self.client.get(
            reverse('inicio', args=[self.dueño.id]),
        )

        contenido = response.content.decode('utf-8')
        self.assertNotIn(inactivo.nombre, contenido)

    def test_formulario_admin_incluye_campo_y_preserva_dueno(self):
        formulario = PreguntaAdminForm(instance=self.question_anterior)

        self.assertIn('elemento_catalogo', formulario.fields)

        datos = {
            'Titulo': self.question_anterior.Titulo,
            'Pregunta': self.question_anterior.Pregunta,
            'Usuario': self.dueño.id,
            'Fecha_creacion': self.question_anterior.Fecha_creacion.isoformat(),
            'elemento_catalogo': self.otro_elemento.pk,
        }
        form = PreguntaAdminForm(data=datos, instance=self.question_anterior)
        self.assertTrue(form.is_valid(), form.errors)
        guardado = form.save(commit=False)

        self.assertEqual(guardado.Usuario_id, self.dueño.id)
        self.assertEqual(guardado.elemento_catalogo_id, self.otro_elemento.pk)


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

    def test_ticket_sin_elemento_no_muestra_bloque(self):
        self.question.elemento_catalogo = None
        self.question.save()
        self.client.force_login(self.dueño)

        response = self.client.get(
            reverse(
                'respuestas',
                args=[self.dueño.id, self.question.idPregunta],
            )
        )

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Elemento Marvel')

    def test_elemento_inactivo_se_muestra_sin_enlace(self):
        self.elemento.activo = False
        self.elemento.save()
        self.client.force_login(self.dueño)

        response = self.client.get(
            reverse(
                'respuestas',
                args=[self.dueño.id, self.question.idPregunta],
            )
        )

        contenido = response.content.decode('utf-8')
        self.assertIn('Superman', contenido)
        self.assertIn('(inactivo)', contenido)
        self.assertNotIn(f'/marvel/{self.elemento.pk}/', contenido)

    def test_listado_cliente_muestra_badge_marvel(self):
        self.client.force_login(self.dueño)

        response = self.client.get(reverse('inicio', args=[self.dueño.id]))

        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode('utf-8')
        self.assertIn('Preguntas-marvel', contenido)
        self.assertIn('Superman', contenido)

    def test_listado_cliente_sin_elemento_no_muestra_badge(self):
        self.question.elemento_catalogo = None
        self.question.save()
        self.client.force_login(self.dueño)

        response = self.client.get(reverse('inicio', args=[self.dueño.id]))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'Preguntas-marvel')

    def test_listado_admin_muestra_indicacion_marvel(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('administracion'))

        self.assertEqual(response.status_code, 200)
        contenido = response.content.decode('utf-8')
        self.assertIn('admin-categoria-marvel', contenido)
        self.assertIn('Superman', contenido)

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_cambio_de_elemento_registra_auditoria_anterior_y_nuevo(
        self, asistente_cls,
    ):
        self.client.force_login(self.admin)
        fecha_original = self.question.Fecha_creacion

        datos = self._datos_admin()
        datos['elemento_catalogo'] = self.otro_elemento.pk
        self.client.post(
            reverse('modificar_pregunta', args=[self.question.idPregunta]),
            datos,
        )

        auditoria = Auditoria.objects.filter(
            pregunta=self.question,
            accion='modificar_pregunta',
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertIn('Pelicula: Superman', auditoria.detalle)
        self.assertIn('Serie: Loki', auditoria.detalle)
        self.assertIn('->', auditoria.detalle)
        self.assertEqual(auditoria.usuario_id, self.admin.id)

        self.question.refresh_from_db()
        self.assertEqual(self.question.elemento_catalogo_id, self.otro_elemento.pk)
        self.assertEqual(self.question.Usuario_id, self.dueño.id)
        self.assertEqual(self.question.Fecha_creacion, fecha_original)

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_eliminar_relacion_registra_auditoria_sin_elemento(
        self, asistente_cls,
    ):
        self.client.force_login(self.admin)

        datos = self._datos_admin()
        datos['elemento_catalogo'] = ''
        self.client.post(
            reverse('modificar_pregunta', args=[self.question.idPregunta]),
            datos,
        )

        auditoria = Auditoria.objects.filter(
            pregunta=self.question,
            accion='modificar_pregunta',
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertIn('Pelicula: Superman', auditoria.detalle)
        self.assertIn('Sin elemento', auditoria.detalle)

        self.question.refresh_from_db()
        self.assertIsNone(self.question.elemento_catalogo)

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_modificacion_sin_cambio_no_menciona_elemento(self, asistente_cls):
        self.client.force_login(self.admin)

        datos = self._datos_admin()
        datos['elemento_catalogo'] = self.elemento.pk
        datos['Titulo'] = 'Titulo editado sin cambio de vinculo'
        self.client.post(
            reverse('modificar_pregunta', args=[self.question.idPregunta]),
            datos,
        )

        auditoria = Auditoria.objects.filter(
            pregunta=self.question,
            accion='modificar_pregunta',
        ).first()
        self.assertIsNotNone(auditoria)
        self.assertNotIn('Elemento Marvel', auditoria.detalle)
        self.assertEqual(
            Auditoria.objects.filter(pregunta=self.question).count(),
            1,
        )

    def test_cliente_ajeno_no_puede_ver_el_ticket(self):
        ajeno = self._crear_usuario('ajeno-c13', 'ajeno@example.com')
        self.client.force_login(ajeno)

        response = self.client.get(
            reverse('respuestas', args=[ajeno.id, self.question.idPregunta])
        )

        self.assertRedirects(response, reverse('inicio', args=[ajeno.id]))

