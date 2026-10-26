from datetime import timedelta
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from online.models import Preguntas, Respuesta, Usuario

from administracion.views import _formatear_duracion
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

    def test_admin_can_delete_another_user_with_post(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('eliminar_usuario', args=[self.owner.id])
        )

        self.assertRedirects(response, reverse('gestion_usuarios'))
        self.assertFalse(Usuario.objects.filter(pk=self.owner.pk).exists())

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

    def test_admin_cannot_remove_own_admin_role(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('gestion_usuarios'),
            {'Userid': self.admin.id, 'rol': 'cliente', 'activo': 'on'},
            follow=True,
        )

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.activo)
        self.assertTrue(self.admin.admin)
        self.assertContains(
            response,
            'No puedes modificar tus propios permisos ni desactivar tu cuenta.'
        )

    def test_admin_cannot_change_own_tecnico_role(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('gestion_usuarios'),
            {'Userid': self.admin.id, 'rol': 'administrador', 'activo': 'on'},
            follow=True,
        )

        self.admin.refresh_from_db()
        self.assertTrue(self.admin.admin)
        self.assertContains(
            response,
            'No puedes modificar tus propios permisos ni desactivar tu cuenta.'
        )

    def test_admin_can_update_another_user_roles(self):
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('gestion_usuarios'),
            {'Userid': self.owner.id, 'activo': 'on', 'rol': 'administrador'},
            follow=True,
        )

        self.owner.refresh_from_db()
        self.assertTrue(self.owner.activo)
        self.assertTrue(self.owner.admin)
        self.assertEqual(self.owner.rol, 'administrador')
        self.assertContains(response, 'actualizado correctamente')

    def test_user_management_marks_self_row_read_only(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('gestion_usuarios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Tu cuenta')
        self.assertNotContains(
            response,
            reverse('eliminar_usuario', args=[self.admin.id])
        )
        self.assertNotContains(response, f'id="activo-{self.admin.id}"')

    def test_technician_is_redirected_from_user_management_to_panel(self):
        technician = self.create_user(
            'tech-usuarios',
            'tech-usuarios@example.com',
            rol='tecnico',
        )
        self.client.force_login(technician)

        response = self.client.get(reverse('gestion_usuarios'))

        self.assertRedirects(response, reverse('administracion'))

    def test_analytics_route_is_available_to_admin(self):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('analytics_ia'))

        self.assertEqual(response.status_code, 200)
        self.assertNotIn('error', response.context['analytics_data'])

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

    def test_technician_sees_panel_without_admin_actions(self):
        technician = self.create_user(
            'tech-panel',
            'tech-panel@example.com',
            rol='tecnico',
        )
        self.client.force_login(technician)

        response = self.client.get(reverse('administracion'))

        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, reverse('gestion_usuarios'))
        self.assertNotContains(
            response,
            reverse(
                'borrar_pregunta',
                args=[self.owner.id, self.question.idPregunta],
            ),
        )

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_admin_panel_uses_stored_category_without_ai(self, asistente_cls):
        self.question.categoria = 'hardware'
        self.question.save()
        self.client.force_login(self.admin)

        response = self.client.get(reverse('administracion'))

        self.assertEqual(response.status_code, 200)
        asistente_cls.assert_not_called()
        self.assertEqual(
            response.context['tendencias_ia'][0]['categoria'],
            'hardware',
        )

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_analytics_uses_stored_categories_without_ai(self, asistente_cls):
        self.question.categoria = 'hardware'
        self.question.save()
        for categoria in ('hardware', 'software'):
            Preguntas.objects.create(
                Titulo=f'Consulta-{categoria}',
                Pregunta='Detalle del problema',
                Fecha_creacion=timezone.now(),
                Usuario=self.owner,
                categoria=categoria,
            )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('analytics_ia'))

        self.assertEqual(response.status_code, 200)
        asistente_cls.assert_not_called()
        self.assertEqual(
            response.context['analytics_data']['categorias_tendencia'],
            {'hardware': 2, 'software': 1},
        )

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_user_management_does_not_call_ai(self, asistente_cls):
        self.client.force_login(self.admin)

        response = self.client.get(reverse('gestion_usuarios'))

        self.assertEqual(response.status_code, 200)
        asistente_cls.assert_not_called()

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_modify_question_get_does_not_call_ai(self, asistente_cls):
        self.client.force_login(self.admin)

        response = self.client.get(
            reverse('modificar_pregunta', args=[self.question.idPregunta])
        )

        self.assertEqual(response.status_code, 200)
        asistente_cls.assert_not_called()

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_modify_question_reclassifies_when_text_changes(self, asistente_cls):
        asistente_cls.return_value.clasificar_pregunta.return_value = 'conexion'
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('modificar_pregunta', args=[self.question.idPregunta]),
            {
                'Titulo': 'Consulta',
                'Pregunta': 'No tengo internet',
                'Usuario': self.owner.id,
                'Fecha_creacion': self.question.Fecha_creacion.isoformat(),
            },
        )

        self.assertRedirects(response, reverse('administracion'))
        self.question.refresh_from_db()
        self.assertEqual(self.question.categoria, 'conexion')
        asistente_cls.return_value.clasificar_pregunta.assert_called_once_with(
            'No tengo internet'
        )

    @patch('administracion.servicios.tickets.AsistenteIA')
    def test_modify_question_keeps_category_when_text_unchanged(self, asistente_cls):
        self.question.categoria = 'hardware'
        self.question.save()
        self.client.force_login(self.admin)

        response = self.client.post(
            reverse('modificar_pregunta', args=[self.question.idPregunta]),
            {
                'Titulo': 'Consulta actualizada',
                'Pregunta': self.question.Pregunta,
                'Usuario': self.owner.id,
                'Fecha_creacion': self.question.Fecha_creacion.isoformat(),
            },
        )

        self.assertRedirects(response, reverse('administracion'))
        self.question.refresh_from_db()
        self.assertEqual(self.question.Titulo, 'Consulta actualizada')
        self.assertEqual(self.question.categoria, 'hardware')
        asistente_cls.assert_not_called()

    def test_analytics_tiempo_promedio_usa_primera_respuesta_de_staff(self):
        ahora = timezone.now()
        self.question.Fecha_creacion = ahora - timedelta(days=5)
        self.question.save()
        Respuesta.objects.create(
            Respuesta='Respuesta del administrador',
            id_Pregunta=self.question,
            Usuario=self.admin,
            FechaHora=ahora - timedelta(days=3),
        )

        otra_pregunta = Preguntas.objects.create(
            Titulo='Otra consulta',
            Pregunta='Detalle del problema',
            Fecha_creacion=ahora - timedelta(days=4),
            Usuario=self.owner,
        )
        Respuesta.objects.create(
            Respuesta='Respuesta del autor',
            id_Pregunta=otra_pregunta,
            Usuario=self.owner,
            FechaHora=ahora - timedelta(days=3, hours=12),
        )
        Respuesta.objects.create(
            Respuesta='Respuesta del tecnico',
            id_Pregunta=otra_pregunta,
            Usuario=self.admin,
            FechaHora=ahora - timedelta(days=3),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('analytics_ia'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['analytics_data']['tiempo_promedio_respuesta'],
            '1.5 días',
        )

    def test_analytics_tiempo_promedio_sin_respuestas_de_staff(self):
        Respuesta.objects.create(
            Respuesta='Respuesta del autor',
            id_Pregunta=self.question,
            Usuario=self.owner,
            FechaHora=timezone.now(),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('analytics_ia'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['analytics_data']['tiempo_promedio_respuesta'],
            'Sin datos',
        )

    def test_analytics_tiempo_promedio_ignora_respuestas_anteriores_a_la_pregunta(self):
        Respuesta.objects.create(
            Respuesta='Respuesta inconsistente',
            id_Pregunta=self.question,
            Usuario=self.admin,
            FechaHora=timezone.now() - timedelta(days=2),
        )
        self.client.force_login(self.admin)

        response = self.client.get(reverse('analytics_ia'))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.context['analytics_data']['tiempo_promedio_respuesta'],
            'Sin datos',
        )


class FormateoDuracionTests(SimpleTestCase):
    def test_formatea_dias(self):
        self.assertEqual(
            _formatear_duracion(timedelta(days=1, hours=12)),
            '1.5 días',
        )

    def test_formatea_horas(self):
        self.assertEqual(
            _formatear_duracion(timedelta(hours=2, minutes=30)),
            '2.5 horas',
        )

    def test_formatea_hora_exacta(self):
        self.assertEqual(
            _formatear_duracion(timedelta(hours=1)),
            '1 hora',
        )

    def test_formatea_minutos(self):
        self.assertEqual(
            _formatear_duracion(timedelta(minutes=30)),
            '30 minutos',
        )


class PanelPaginacionBusquedaTests(TestCase):
    def setUp(self):
        self.admin = self.crear_usuario(
            'admin-panel', 'admin-panel@example.com', rol='administrador'
        )
        self.owner = self.crear_usuario('owner-panel', 'owner-panel@example.com')
        self.otro = self.crear_usuario('otro-panel', 'otro-panel@example.com')
        ahora = timezone.now()
        for indice in range(24):
            Preguntas.objects.create(
                Titulo=f'Pregunta {indice:02d}',
                Pregunta='Detalle del problema',
                Fecha_creacion=ahora - timedelta(minutes=indice),
                Usuario=self.owner,
            )
        Preguntas.objects.create(
            Titulo='Falla de conexión especial',
            Pregunta='No navega',
            Fecha_creacion=ahora - timedelta(days=1),
            Usuario=self.otro,
        )
        self.client.force_login(self.admin)

    def crear_usuario(self, username, email, **fields):
        user = Usuario.objects.create(
            usuario=username,
            correo=email,
            **fields,
        )
        user.set_password('test-password-123')
        user.save()
        return user

    def test_panel_pagina_de_20_y_segunda_pagina_de_5(self):
        primera = self.client.get(reverse('administracion'))
        self.assertEqual(primera.status_code, 200)
        self.assertEqual(len(primera.context['Preguntas']), 20)
        self.assertEqual(primera.context['page_obj'].paginator.count, 25)
        self.assertEqual(primera.context['total_filtrado'], 25)

        segunda = self.client.get(reverse('administracion'), {'page': 2})
        self.assertEqual(segunda.status_code, 200)
        self.assertEqual(len(segunda.context['Preguntas']), 5)
        self.assertEqual(segunda.context['page_obj'].number, 2)

    def test_pagina_fuera_de_rango_no_falla(self):
        response = self.client.get(reverse('administracion'), {'page': 999})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['page_obj'].number, 2)

    def test_buscador_filtra_por_titulo(self):
        response = self.client.get(reverse('administracion'), {'q': 'especial'})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_filtrado'], 1)
        self.assertEqual(len(response.context['Preguntas']), 1)
        self.assertEqual(response.context['q'], 'especial')

    def test_buscador_filtra_por_usuario(self):
        response = self.client.get(
            reverse('administracion'), {'q': 'owner-panel'}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['total_filtrado'], 24)
        self.assertEqual(len(response.context['Preguntas']), 20)

        response_otro = self.client.get(
            reverse('administracion'), {'q': 'otro-panel'}
        )
        self.assertEqual(response_otro.context['total_filtrado'], 1)


class AnalyticsPeriodoTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create(
            usuario='admin-analytics',
            correo='admin-analytics@example.com',
            rol='administrador',
        )
        self.admin.set_password('test-password-123')
        self.admin.save()
        ahora = timezone.now()
        self.reciente = Preguntas.objects.create(
            Titulo='Conexión reciente',
            Pregunta='No navega',
            Fecha_creacion=ahora - timedelta(days=1),
            Usuario=self.admin,
            categoria='conexion',
        )
        self.vieja = Preguntas.objects.create(
            Titulo='Hardware antiguo',
            Pregunta='No enciende',
            Fecha_creacion=ahora - timedelta(days=20),
            Usuario=self.admin,
            categoria='hardware',
        )
        Preguntas.objects.create(
            Titulo='Fuera del período',
            Pregunta='Muy antigua',
            Fecha_creacion=ahora - timedelta(days=40),
            Usuario=self.admin,
            categoria='otros',
        )
        Respuesta.objects.create(
            Respuesta='Respuesta del administrador',
            id_Pregunta=self.reciente,
            Usuario=self.admin,
            FechaHora=ahora,
        )
        self.client.force_login(self.admin)

    def test_periodo_de_7_dias(self):
        response = self.client.get(reverse('analytics_ia'), {'dias': 7})

        datos = response.context['analytics_data']
        self.assertEqual(response.status_code, 200)
        self.assertEqual(datos['periodo']['dias'], 7)
        self.assertEqual(datos['total_preguntas_mes'], 1)
        self.assertEqual(datos['total_respuestas'], 1)
        self.assertEqual(datos['porcentaje_resueltas'], 100.0)
        self.assertEqual(
            datos['categorias_lista'][0]['etiqueta'], 'Conexión'
        )

    def test_periodo_invalido_cae_a_30_dias(self):
        response = self.client.get(reverse('analytics_ia'), {'dias': 999})

        datos = response.context['analytics_data']
        self.assertEqual(datos['periodo']['dias'], 30)
        self.assertEqual(datos['periodo']['etiqueta'], 'Últimos 30 días')
        self.assertEqual(datos['total_preguntas_mes'], 2)
        self.assertEqual(datos['porcentaje_resueltas'], 50.0)

    def test_porcentaje_resueltas_sin_preguntas_es_cero(self):
        Preguntas.objects.all().delete()
        respuesta = self.client.get(
            reverse('analytics_ia'), {'dias': 7}
        )

        datos = respuesta.context['analytics_data']
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(datos['total_preguntas_mes'], 0)
        self.assertEqual(datos['porcentaje_resueltas'], 0)
        self.assertEqual(datos['categorias_lista'], [])


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

    def test_eliminar_otro_administrador_permitido(self):
        actor = self.crear_usuario('admin-uno', 'administrador')
        objetivo = self.crear_usuario('admin-dos', 'administrador')
        self.client.force_login(actor)

        response = self.client.post(
            reverse('eliminar_usuario', args=[objetivo.id])
        )

        self.assertRedirects(response, reverse('gestion_usuarios'))
        self.assertFalse(Usuario.objects.filter(pk=objetivo.pk).exists())

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

    def test_no_desactiva_al_ultimo_administrador_activo(self):
        actor = self.crear_usuario('admin-inactivo-3', 'administrador', activo=False)
        objetivo = self.crear_usuario('admin-unico-activo-3', 'administrador')

        with self.assertRaisesMessage(
            usuarios_servicio.ErrorUsuarios,
            'No puedes dejar el sistema sin administradores activos.',
        ):
            usuarios_servicio.actualizar(
                objetivo, {'rol': 'administrador'}, actor
            )

        objetivo.refresh_from_db()
        self.assertTrue(objetivo.activo)
