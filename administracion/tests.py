from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from online.models import Auditoria, Preguntas, Usuario

from administracion.servicios import tickets as tickets_servicio
from administracion.servicios import usuarios as usuarios_servicio


class AdministrationAccessTests(TestCase):
    def setUp(self):
        self.admin = self.create_user(
            'admin',
            'admin@example.com',
            rol='administrador',
        )
        self.owner = self.create_user('owner', 'owner@example.com')
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

    def test_non_admin_cannot_delete_question_by_spoofing_admin_id(self):
        self.client.force_login(self.owner)

        response = self.client.post(
            reverse('borrar_pregunta', args=[self.admin.id, self.question.idPregunta])
        )

        self.assertRedirects(response, reverse('inicio', args=[self.owner.id]))
        self.assertTrue(Preguntas.objects.filter(pk=self.question.pk).exists())

    def test_admin_can_delete_question_only_with_post(self):
        self.client.force_login(self.admin)

        get_response = self.client.get(
            reverse('borrar_pregunta', args=[self.owner.id, self.question.idPregunta])
        )
        self.assertEqual(get_response.status_code, 405)
        self.assertTrue(Preguntas.objects.filter(pk=self.question.pk).exists())

        post_response = self.client.post(
            reverse('borrar_pregunta', args=[self.owner.id, self.question.idPregunta])
        )
        self.assertRedirects(post_response, reverse('administracion'))
        self.assertFalse(Preguntas.objects.filter(pk=self.question.pk).exists())

    def test_user_deletion_requires_post_and_prevents_self_deletion(self):
        self.client.force_login(self.admin)

        get_response = self.client.get(
            reverse('eliminar_usuario', args=[self.owner.id])
        )
        self.assertEqual(get_response.status_code, 405)
        self.assertTrue(Usuario.objects.filter(pk=self.owner.pk).exists())

        post_response = self.client.post(
            reverse('eliminar_usuario', args=[self.admin.id])
        )
        self.assertRedirects(post_response, reverse('gestion_usuarios'))
        self.assertTrue(Usuario.objects.filter(pk=self.admin.pk).exists())

    def test_admin_cannot_deactivate_self(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('gestion_usuarios'),
            {'Userid': self.admin.id, 'rol': 'administrador', 'activo': 'on'},
            follow=True,
        )

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.activo)
        self.assertTrue(self.admin.admin)
        self.assertContains(
            response,
            'No puedes modificar tus propios permisos ni desactivar tu cuenta.'
        )

    def test_technician_cannot_access_analytics(self):
        technician = self.create_user(
            'tech',
            'tech@example.com',
            rol='tecnico',
        )
        self.client.force_login(technician)

        response = self.client.get(reverse('analytics_ia'))

        # El técnico ya no usa el panel de cliente: Inicio lo devuelve al
        # panel de administración, así que se valida la primera redirección.
        self.assertEqual(response.status_code, 302)
        self.assertEqual(response.url, reverse('inicio', args=[technician.id]))

    def test_admin_panel_renders_with_dashboard_data(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('administracion'))

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'indexAdmin.html')
        self.assertContains(response, 'Panel de Administración')
        self.assertEqual(
            response.context['estadisticas_ia']['total_preguntas'],
            1,
        )

    def test_admin_panel_escapes_html_in_question_content(self):
        self.question.Titulo = '<script>alert(1)</script>'
        self.question.Pregunta = '<a href="https://example.com">visitar</a>'
        self.question.save()
        self.client.force_login(self.admin)

        response = self.client.get(reverse('administracion'))

        self.assertContains(
            response,
            '&lt;script&gt;alert(1)&lt;/script&gt;',
            html=False,
        )
        self.assertContains(
            response,
            '&lt;a href=&quot;https://example.com&quot;&gt;visitar&lt;/a&gt;',
            html=False,
        )
        self.assertNotContains(response, '<script>alert(1)</script>')

class UltimoAdministradorTests(TestCase):
    def crear_usuario(self, username, rol, activo=True):
        user = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
            activo=activo,
        )
        user.set_password('test-password-123')
        user.save()
        return user

    def test_no_elimina_al_ultimo_administrador_activo(self):
        actor = self.crear_usuario('admin-inactivo', 'administrador', activo=False)
        objetivo = self.crear_usuario('admin-unico-activo', 'administrador')

        with self.assertRaisesMessage(
            usuarios_servicio.ErrorUsuarios,
            'No puedes dejar el sistema sin administradores activos.',
        ):
            usuarios_servicio.eliminar(objetivo, actor)

        self.assertTrue(Usuario.objects.filter(pk=objetivo.pk).exists())

    def test_no_degrada_al_ultimo_administrador_activo(self):
        actor = self.crear_usuario('admin-inactivo-2', 'administrador', activo=False)
        objetivo = self.crear_usuario('admin-unico-activo-2', 'administrador')

        with self.assertRaisesMessage(
            usuarios_servicio.ErrorUsuarios,
            'No puedes dejar el sistema sin administradores activos.',
        ):
            usuarios_servicio.actualizar(
                objetivo, {'rol': 'tecnico', 'activo': 'on'}, actor
            )

        objetivo.refresh_from_db()
        self.assertEqual(objetivo.rol, 'administrador')


class AsignacionTecnicoBloque6BTests(TestCase):
    """Bloque 6B: asignacion de tecnicos sobre Preguntas.tecnico_asignado.

    Reglas aprobadas (6A): el admin asigna/reasigna/desasigna cualquier
    tecnico activo; el tecnico SOLO se autoasigna tickets libres (o
    reafirma el suyo); cliente/visitante no pueden; los tickets
    cerrados no cambian de tecnico hasta reabrirse; cada cambio
    efectivo queda auditado y los intentos fallidos no tocan nada.
    """

    def setUp(self):
        self.admin = self.crear_usuario('adm-6b', 'administrador')
        self.tecnico1 = self.crear_usuario('tecnico1-6b', 'tecnico')
        self.tecnico2 = self.crear_usuario('tecnico2-6b', 'tecnico')
        self.cliente = self.crear_usuario('cliente-6b', 'cliente')
        self.pregunta = self.crear_pregunta(self.cliente)

    def crear_usuario(self, username, rol, activo=True):
        user = Usuario.objects.create(
            usuario=username,
            correo=f'{username}@example.com',
            rol=rol,
            activo=activo,
        )
        user.set_password('test-password-123')
        user.save()
        return user

    def crear_pregunta(self, usuario, titulo='Consulta 6B', estado='en_proceso',
                       tecnico=None):
        return Preguntas.objects.create(
            Titulo=titulo,
            Pregunta='Texto de la consulta de prueba.',
            Fecha_creacion=timezone.now(),
            Usuario=usuario,
            estado=estado,
            tecnico_asignado=tecnico,
        )

    def _ruta(self, pregunta=None):
        return reverse('asignar_tecnico', args=[(pregunta or self.pregunta).idPregunta])

    # --- 1-3. Operaciones del administrador ---------------------------------
    def test_admin_asigna_reasigna_y_desasigna(self):
        self.client.force_login(self.admin)

        # Asignacion inicial.
        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': self.tecnico1.id}, follow=True,
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, 'Técnico asignado: tecnico1-6b.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico1)

        # Reasignacion a otro tecnico activo.
        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': self.tecnico2.id}, follow=True,
        )
        self.assertContains(respuesta, 'Técnico asignado: tecnico2-6b.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico2)

        # Desasignacion (tecnico_id vacio).
        respuesta = self.client.post(self._ruta(), {'tecnico_id': ''}, follow=True)
        self.assertContains(respuesta, 'Técnico desasignado')
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)

        # Auditoria de los tres cambios efectivos, en orden.
        auditos = list(Auditoria.objects.order_by('id'))
        self.assertEqual(len(auditos), 3)
        self.assertIn('Asignación de técnico: Sin técnico -> tecnico1-6b', auditos[0].detalle)
        self.assertIn('Reasignación de técnico: tecnico1-6b -> tecnico2-6b', auditos[1].detalle)
        self.assertIn('Desasignación de técnico: tecnico2-6b -> Sin técnico', auditos[2].detalle)
        for registro in auditos:
            self.assertEqual(registro.usuario, self.admin)
            self.assertEqual(registro.pregunta, self.pregunta)
            self.assertEqual(registro.accion, 'modificar_pregunta')

    # --- 4. Autoasignacion del tecnico --------------------------------------
    def test_tecnico_se_autoasigna_ticket_libre(self):
        self.client.force_login(self.tecnico1)

        respuesta = self.client.post(self._ruta(), {}, follow=True)

        self.assertContains(respuesta, 'Técnico asignado: tecnico1-6b.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico1)
        registro = Auditoria.objects.get()
        self.assertEqual(registro.usuario, self.tecnico1)

    def test_tecnico_reafirma_su_propia_asignacion_sin_duplicar_auditoria(self):
        self.pregunta.tecnico_asignado = self.tecnico1
        self.pregunta.save()
        self.client.force_login(self.tecnico1)

        respuesta = self.client.post(self._ruta(), {}, follow=True)

        self.assertContains(respuesta, 'El ticket ya está asignado a ti.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico1)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_admin_repite_asignacion_sin_duplicar_auditoria(self):
        self.pregunta.tecnico_asignado = self.tecnico1
        self.pregunta.save()
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': self.tecnico1.id}, follow=True,
        )

        self.assertContains(respuesta, 'El ticket ya está asignado a ese técnico.')
        self.assertEqual(Auditoria.objects.count(), 0)

    # --- 5-7. Lo que el tecnico NO puede hacer ------------------------------
    def test_tecnico_no_puede_asignar_a_otro_tecnico(self):
        self.client.force_login(self.tecnico1)

        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': self.tecnico2.id}, follow=True,
        )

        self.assertContains(respuesta, 'Un técnico solo puede autoasignarse')
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_tecnico_no_puede_apropiarse_de_ticket_de_otro(self):
        self.pregunta.tecnico_asignado = self.tecnico2
        self.pregunta.save()
        self.client.force_login(self.tecnico1)

        respuesta = self.client.post(self._ruta(), {}, follow=True)

        self.assertContains(respuesta, 'El ticket ya tiene un técnico asignado.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico2)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_tecnico_no_puede_desasignar(self):
        self.pregunta.tecnico_asignado = self.tecnico1
        self.pregunta.save()
        self.client.force_login(self.tecnico1)

        # Intento de desasignar (tecnico_id vacio): se trata como
        # autoasignacion, que no cambia nada porque ya es suyo.
        respuesta = self.client.post(self._ruta(), {'tecnico_id': ''}, follow=True)

        self.assertContains(respuesta, 'El ticket ya está asignado a ti.')
        self.pregunta.refresh_from_db()
        self.assertEqual(self.pregunta.tecnico_asignado, self.tecnico1)
        self.assertEqual(Auditoria.objects.count(), 0)

    # --- 8-9. Cliente y visitante ---------------------------------------------
    def test_cliente_no_puede_asignar(self):
        self.client.force_login(self.cliente)

        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': self.tecnico1.id},
        )

        self.assertEqual(respuesta.status_code, 302)
        self.assertEqual(respuesta['Location'], reverse('inicio', args=[self.cliente.id]))
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_visitante_es_redirigido_al_login(self):
        respuesta = self.client.post(self._ruta(), {'tecnico_id': self.tecnico1.id})

        self.assertEqual(respuesta.status_code, 302)
        self.assertIn(reverse('Login'), respuesta['Location'])
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)

    # --- 10-11. Metodo y CSRF --------------------------------------------------
    def test_get_de_asignacion_devuelve_405(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get(self._ruta())

        self.assertEqual(respuesta.status_code, 405)
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)

    def test_post_sin_csrf_es_rechazado(self):
        cliente_con_csrf = self.client_class(enforce_csrf_checks=True)
        cliente_con_csrf.force_login(self.admin)

        respuesta = cliente_con_csrf.post(
            self._ruta(), {'tecnico_id': self.tecnico1.id},
        )

        self.assertEqual(respuesta.status_code, 403)
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    # --- 12-15. Validacion del tecnico destino ----------------------------------
    def test_tecnico_inexistente_es_rechazado(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post(self._ruta(), {'tecnico_id': 99999}, follow=True)

        self.assertContains(respuesta, 'El técnico indicado no existe.')
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_identificador_malformado_es_rechazado(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': '1; DROP TABLE'}, follow=True,
        )

        self.assertContains(respuesta, 'Identificador de técnico inválido.')
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_cliente_y_administrador_no_pueden_ser_asignados(self):
        self.client.force_login(self.admin)

        for destino in (self.cliente, self.admin):
            with self.subTest(destino=destino.rol):
                respuesta = self.client.post(
                    self._ruta(), {'tecnico_id': destino.id}, follow=True,
                )
                self.assertContains(
                    respuesta, 'Solo se puede asignar a usuarios con rol técnico.',
                )
                self.pregunta.refresh_from_db()
                self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_tecnico_inactivo_no_puede_ser_asignado(self):
        inactivo = self.crear_usuario('tecnico-off-6b', 'tecnico', activo=False)
        self.client.force_login(self.admin)

        respuesta = self.client.post(
            self._ruta(), {'tecnico_id': inactivo.id}, follow=True,
        )

        self.assertContains(respuesta, 'El técnico está inactivo.')
        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    # --- 16-17. Tickets cerrados ------------------------------------------------
    def test_ticket_cerrado_no_permite_cambios(self):
        cerrada = self.crear_pregunta(
            self.cliente, titulo='Cerrada 6B', estado='cerrado',
        )
        self.client.force_login(self.admin)

        # Admin: no puede asignar.
        respuesta = self.client.post(
            self._ruta(cerrada), {'tecnico_id': self.tecnico1.id}, follow=True,
        )
        self.assertContains(respuesta, 'El ticket está cerrado: reabre la pregunta')

        # Tecnico: tampoco puede autoasignarse.
        self.client.force_login(self.tecnico1)
        respuesta = self.client.post(self._ruta(cerrada), {}, follow=True)
        self.assertContains(respuesta, 'El ticket está cerrado: reabre la pregunta')

        cerrada.refresh_from_db()
        self.assertIsNone(cerrada.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_ticket_reabierto_vuelve_a_permitir_asignacion(self):
        cerrada = self.crear_pregunta(
            self.cliente, titulo='Reabierta 6B', estado='cerrado',
        )
        self.client.force_login(self.admin)

        tickets_servicio.reabrir(cerrada.idPregunta, self.admin)
        respuesta = self.client.post(
            self._ruta(cerrada), {'tecnico_id': self.tecnico1.id}, follow=True,
        )

        self.assertContains(respuesta, 'Técnico asignado: tecnico1-6b.')
        cerrada.refresh_from_db()
        self.assertEqual(cerrada.tecnico_asignado, self.tecnico1)

    # --- 18-19. Comportamiento del campo del modelo ------------------------------
    def test_set_null_al_eliminar_tecnico(self):
        self.pregunta.tecnico_asignado = self.tecnico1
        self.pregunta.save()

        self.tecnico1.delete()
        self.pregunta.refresh_from_db()

        self.assertIsNone(self.pregunta.tecnico_asignado)

    def test_limit_choices_to_restringe_opciones_del_modelo(self):
        campo = Preguntas._meta.get_field('tecnico_asignado')

        self.assertEqual(campo.get_limit_choices_to(), {'rol': 'tecnico'})

        # Django aplica limit_choices_to durante ModelForm.__init__():
        # el formulario derivado del modelo solo ofrece tecnicos.
        from django import forms as django_forms

        class FormularioCampo(django_forms.ModelForm):
            class Meta:
                model = Preguntas
                fields = ['tecnico_asignado']

        formulario = FormularioCampo()
        opcion_id = {str(u.id) for u in formulario.fields['tecnico_asignado'].queryset}
        self.assertIn(str(self.tecnico1.id), opcion_id)
        self.assertNotIn(str(self.cliente.id), opcion_id)
        self.assertNotIn(str(self.admin.id), opcion_id)

    # --- 20-21. Badges en panel y ficha -----------------------------------------
    def test_badge_correcto_en_el_panel(self):
        asignada = self.crear_pregunta(
            self.cliente, titulo='Asignada 6B', tecnico=self.tecnico1,
        )
        ruta = reverse('administracion')

        # Admin: ve ambos badges y el selector con los tecnicos activos.
        self.client.force_login(self.admin)
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Sin asignar')
        self.assertContains(respuesta, 'tecnico1-6b')
        self.assertContains(respuesta, 'filtro-tecnico')
        # El admin no ve el boton de autoasignacion.
        self.assertNotContains(respuesta, '>Autoasignarme<')

        # Tecnico: ve el badge, el boton solo en el ticket libre y el
        # estado informativo en el suyo.
        self.client.force_login(self.tecnico1)
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Autoasignarme')
        self.assertContains(respuesta, 'Tu asignación')
        self.assertContains(respuesta, 'Sin asignar')

    def test_badge_correcto_en_la_ficha(self):
        ruta = reverse('respuestas', args=[self.cliente.id, self.pregunta.idPregunta])

        # Sin tecnico: "Sin técnico asignado".
        self.client.force_login(self.cliente)
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Sin técnico asignado')

        # Con tecnico: nombre legible.
        self.pregunta.tecnico_asignado = self.tecnico1
        self.pregunta.save()
        respuesta = self.client.get(ruta)
        self.assertContains(respuesta, 'Técnico: tecnico1-6b')

    # --- 22-25. Filtro por tecnico ----------------------------------------------
    def test_filtro_por_tecnico_y_sin_asignar(self):
        libre = self.crear_pregunta(self.cliente, titulo='Libre 6B')
        de_tecnico1 = self.crear_pregunta(
            self.cliente, titulo='De tecnico1 6B', tecnico=self.tecnico1,
        )
        de_tecnico2 = self.crear_pregunta(
            self.cliente, titulo='De tecnico2 6B', tecnico=self.tecnico2,
        )
        self.client.force_login(self.admin)
        ruta = reverse('administracion')

        def titulos(query):
            respuesta = self.client.get(ruta, query)
            return {
                p.idPregunta for p in respuesta.context['Preguntas'].object_list
            }

        self.assertEqual(titulos({'tecnico': str(self.tecnico1.id)}), {de_tecnico1.idPregunta})
        self.assertEqual(
            titulos({'tecnico': 'sin_asignar'}),
            {self.pregunta.idPregunta, libre.idPregunta},
        )
        # Valor invalido: se ignora (no filtra ni explota).
        self.assertEqual(titulos({'tecnico': 'xyz'}), {
            self.pregunta.idPregunta, libre.idPregunta,
            de_tecnico1.idPregunta, de_tecnico2.idPregunta,
        })

        # Combinacion con filtros existentes.
        libre.estado = 'pendiente'
        libre.save()
        self.assertEqual(
            titulos({'tecnico': 'sin_asignar', 'estado': 'pendiente'}),
            {libre.idPregunta},
        )

    def test_filtro_incluye_chip_de_remoccion(self):
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('administracion'), {'tecnico': 'sin_asignar'},
        )
        self.assertContains(respuesta, 'Técnico: Sin asignar')

        respuesta = self.client.get(
            reverse('administracion'), {'tecnico': str(self.tecnico1.id)},
        )
        self.assertContains(respuesta, 'Técnico: tecnico1-6b')

    def test_paginacion_conserva_el_filtro(self):
        # La pagina muestra 20 registros: con 21 asignados al mismo
        # tecnico hay una segunda pagina que debe mantener el filtro.
        for indice in range(21):
            self.crear_pregunta(
                self.cliente, titulo=f'Paginada {indice} 6B',
                tecnico=self.tecnico1,
            )
        self.client.force_login(self.admin)

        respuesta = self.client.get(
            reverse('administracion'), {'tecnico': str(self.tecnico1.id)},
        )
        self.assertEqual(respuesta.context['total_filtrado'], 21)
        # Los enlaces de paginacion conservan el filtro (querystring tag).
        contenido = respuesta.content.decode('utf-8')
        self.assertIn(f'tecnico={self.tecnico1.id}', contenido)
        self.assertIn('page=2', contenido)

        respuesta_2 = self.client.get(
            reverse('administracion'),
            {'tecnico': str(self.tecnico1.id), 'page': 2},
        )
        self.assertEqual(respuesta_2.context['page_obj'].number, 2)
        self.assertEqual(len(respuesta_2.context['Preguntas'].object_list), 1)

    # --- 26-30. Auditoria e integridad --------------------------------------------
    def test_intentos_fallidos_no_modifican_ni_auditan(self):
        self.client.force_login(self.admin)
        antes = Auditoria.objects.count()

        self.client.post(self._ruta(), {'tecnico_id': 99999})
        self.client.post(self._ruta(), {'tecnico_id': self.cliente.id})
        self.client.post(self._ruta(), {'tecnico_id': 'no-numero'})
        self.client.post(self._ruta(), {'tecnico_id': ''})  # desasignar sin tecnico previo

        self.pregunta.refresh_from_db()
        self.assertIsNone(self.pregunta.tecnico_asignado)
        self.assertEqual(Auditoria.objects.count(), antes)

    def test_tickets_historicos_no_se_modifican(self):
        historica = self.crear_pregunta(
            self.cliente, titulo='Consulta historica', estado='resuelto',
        )
        self.client.force_login(self.admin)

        # Operaciones sobre otros tickets...
        self.client.post(self._ruta(), {'tecnico_id': self.tecnico1.id})
        # ...y un intento fallido sobre la historica.
        cerrada = self.crear_pregunta(
            self.cliente, titulo='Cerrada historica', estado='cerrado',
        )
        self.client.post(self._ruta(cerrada), {'tecnico_id': self.tecnico1.id})

        historica.refresh_from_db()
        self.assertIsNone(historica.tecnico_asignado)
        self.assertEqual(historica.estado, 'resuelto')
        # Ninguna auditoria sobre tickets distintos del asignado.
        self.assertFalse(
            Auditoria.objects.exclude(pregunta=self.pregunta).exists()
        )


class CierreReaperturaBloque6DTests(TestCase):
    """Rutas CerrarPregunta y ReabrirPregunta (validacion 6D).

    El servicio tickets.cerrar/reabrir existia con auditoria, pero las
    rutas no tenian pruebas: aqui se validan permisos (admin y tecnico
    si, cliente y visitante no), metodo POST obligatorio y auditoria.
    """

    def setUp(self):
        self.admin = self.crear_usuario(
            'admin', 'admin@example.com', rol='administrador',
        )
        self.tecnico = self.crear_usuario(
            'tech', 'tech@example.com', rol='tecnico',
        )
        self.cliente = self.crear_usuario(
            'owner', 'owner@example.com',
        )
        self.ticket = self.crear_ticket(estado='en_proceso')
        self.cerrado = self.crear_ticket(
            titulo='Cerrado previo', estado='cerrado',
        )

    def crear_usuario(self, username, email, **campos):
        usuario = Usuario.objects.create(
            usuario=username,
            correo=email,
            **campos,
        )
        usuario.set_password('test-password-123')
        usuario.save()
        return usuario

    def crear_ticket(self, titulo='Abierta 6D', estado='pendiente'):
        return Preguntas.objects.create(
            Titulo=titulo,
            Pregunta='Contenido del ticket de prueba.',
            Fecha_creacion=timezone.now(),
            Usuario=self.cliente,
            estado=estado,
        )

    def ruta(self, vista, ticket=None):
        return reverse(vista, args=[(ticket or self.ticket).idPregunta])

    def test_admin_cierra_y_reabre_con_auditoria(self):
        self.client.force_login(self.admin)

        respuesta = self.client.post(self.ruta('cerrar_pregunta'), follow=True)
        self.assertRedirects(respuesta, reverse('administracion'))
        self.assertContains(respuesta, 'Pregunta cerrada correctamente.')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'cerrado')
        self.assertTrue(Auditoria.objects.filter(
            pregunta=self.ticket,
            accion='cambiar_estado',
            detalle='Estado cambiado a cerrado',
        ).exists())

        auditorias_antes = Auditoria.objects.count()
        respuesta = self.client.post(
            self.ruta('reabrir_pregunta'), follow=True,
        )
        self.assertRedirects(respuesta, reverse('administracion'))
        self.assertContains(respuesta, 'Pregunta reabierta correctamente.')
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'en_proceso')
        self.assertTrue(Auditoria.objects.filter(
            pregunta=self.ticket,
            accion='cambiar_estado',
            detalle='Estado cambiado a en proceso',
        ).exists())
        self.assertEqual(Auditoria.objects.count(), auditorias_antes + 1)

    def test_tecnico_puede_cerrar_y_reabrir(self):
        self.client.force_login(self.tecnico)

        self.client.post(self.ruta('cerrar_pregunta'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'cerrado')

        self.client.post(self.ruta('reabrir_pregunta'))
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'en_proceso')

    def test_cliente_no_puede_cerrar_ni_reabrir(self):
        self.client.force_login(self.cliente)

        for vista in ('cerrar_pregunta', 'reabrir_pregunta'):
            respuesta = self.client.post(self.ruta(vista))
            self.assertEqual(respuesta.status_code, 302)
            self.assertEqual(
                respuesta['Location'],
                reverse('inicio', args=[self.cliente.id]),
            )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'en_proceso')
        self.cerrado.refresh_from_db()
        self.assertEqual(self.cerrado.estado, 'cerrado')
        self.assertEqual(Auditoria.objects.count(), 0)

    def test_visitante_es_redirigido_al_login(self):
        for vista in ('cerrar_pregunta', 'reabrir_pregunta'):
            respuesta = self.client.post(self.ruta(vista))
            self.assertEqual(respuesta.status_code, 302)
            self.assertIn(reverse('Login'), respuesta['Location'])
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'en_proceso')

    def test_get_devuelve_405(self):
        self.client.force_login(self.admin)
        for vista in ('cerrar_pregunta', 'reabrir_pregunta'):
            respuesta = self.client.get(self.ruta(vista))
            self.assertEqual(respuesta.status_code, 405)
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.estado, 'en_proceso')

    def test_ticket_inexistente_muestra_mensaje_sin_cambios(self):
        self.client.force_login(self.admin)
        auditorias_antes = Auditoria.objects.count()

        for vista in ('cerrar_pregunta', 'reabrir_pregunta'):
            respuesta = self.client.post(
                reverse(vista, args=[99999]), follow=True,
            )
            self.assertRedirects(respuesta, reverse('administracion'))
            self.assertContains(respuesta, 'La pregunta no existe.')

        self.assertEqual(Auditoria.objects.count(), auditorias_antes)

