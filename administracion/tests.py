from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from online.models import Preguntas, Usuario

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

