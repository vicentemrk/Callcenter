from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from marvel.constants import (
    CALIFICACION_MAXIMA,
    CALIFICACION_MINIMA,
    TIPOS_ELEMENTO,
    TIPOS_RESEÑABLES,
)
from marvel.validators import validar_referencia_tematica


class ElementoCatalogo(models.Model):
    """Elemento del universo Marvel sincronizado desde MCU API.

    Representa una pelicula o una serie. Los IDs de MCU API son
    independientes por recurso (movie #1 no es tvshow #1), por lo que la
    unicidad es compuesta por (tipo, mcu_id).
    """

    mcu_id = models.PositiveIntegerField(
        verbose_name='ID de MCU API',
        db_index=True,
    )
    tipo = models.CharField(
        verbose_name='Tipo',
        max_length=10,
        choices=TIPOS_ELEMENTO,
        db_index=True,
    )
    nombre = models.CharField(
        verbose_name='Nombre',
        max_length=200,
        db_index=True,
    )
    descripcion = models.TextField(
        verbose_name='Descripcion',
        null=True,
        blank=True,
    )
    imagen = models.URLField(
        verbose_name='Imagen',
        max_length=500,
        null=True,
        blank=True,
    )
    fecha_estreno = models.DateField(
        verbose_name='Fecha de estreno',
        null=True,
        blank=True,
    )
    fase = models.PositiveSmallIntegerField(
        verbose_name='Fase del MCU',
        null=True,
        blank=True,
    )
    saga = models.CharField(
        verbose_name='Saga',
        max_length=100,
        null=True,
        blank=True,
    )
    activo = models.BooleanField(
        verbose_name='Activo',
        default=True,
    )
    datos_json = models.JSONField(
        verbose_name='Datos adicionales',
        null=True,
        blank=True,
    )
    sincronizado_en = models.DateTimeField(
        verbose_name='Ultima sincronizacion',
        null=True,
        blank=True,
    )

    class Meta:
        verbose_name = 'Elemento de catalogo'
        verbose_name_plural = 'Elementos de catalogo'
        ordering = ['tipo', 'nombre']
        db_table = 'marvel_elementocatalogo'
        constraints = [
            models.UniqueConstraint(
                fields=['tipo', 'mcu_id'],
                name='elementocatalogo_tipo_mcu_id_unique',
            ),
        ]

    def __str__(self):
        return f"{self.get_tipo_display()} #{self.mcu_id}: {self.nombre}"


class Resena(models.Model):
    """Resena de un usuario sobre una pelicula o serie del catalogo.

    Reglas aprobadas (Bloque 5B, decisiones del 5A):
    - Solo elementos de tipo movie/tvshow, activos y existentes.
    - Calificacion obligatoria 1..5; sin comentario adicional.
    - Referencia tematica obligatoria de 10 a 200 caracteres.
    - Maximo una reseña por (elemento, usuario): UniqueConstraint.
    - Se publica visible por defecto; ocultar/restaurar es de
      moderacion (Bloque 5D) y sera exclusivo del administrador.
    - No hay edicion ni eliminacion por el autor en este ciclo.

    Que protege cada capa:
    - BASE DE DATOS: unicidad (elemento, usuario) — la constraint se
      crea en la migracion y rechaza duplicados incluso si se salva
      sin pasar por full_clean().
    - VALIDACION DE APLICACION (clean/full_clean): calificacion 1..5,
      referencia tematica, elemento activo y reseñable, autor cliente.
      save() de Django NO llama full_clean(); la capa de vistas
      (Bloque 5C) usara el formulario, que ejecuta full_clean, y la
      unicidad queda garantizada ademas por la base.
    """

    elemento = models.ForeignKey(
        ElementoCatalogo,
        on_delete=models.CASCADE,
        related_name='resenas',
        verbose_name='Elemento reseñado',
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='resenas',
        verbose_name='Autor de la reseña',
    )
    calificacion = models.PositiveSmallIntegerField(
        verbose_name='Calificación',
        validators=[
            MinValueValidator(CALIFICACION_MINIMA),
            MaxValueValidator(CALIFICACION_MAXIMA),
        ],
    )
    referencia_tematica = models.CharField(
        verbose_name='Referencia temática',
        max_length=200,
        validators=[validar_referencia_tematica],
        help_text=(
            'Cita, personaje, escena, saga o elemento de Marvel al que '
            'refiere la reseña (10 a 200 caracteres).'
        ),
    )
    visible = models.BooleanField(
        verbose_name='Visible',
        default=True,
        db_index=True,
    )
    fecha_publicacion = models.DateTimeField(
        verbose_name='Fecha de publicación',
        auto_now_add=True,
    )

    def clean(self):
        """Validaciones de aplicacion a nivel de modelo.

        Se ejecutan con instancia.full_clean(); save() no las llama
        automaticamente, por eso 5C hara pasar por el formulario.
        """
        super().clean()

        # Normalizacion coherente con el resto del proyecto (trim).
        self.referencia_tematica = (self.referencia_tematica or '').strip()

        if self.elemento_id:
            elemento = self.elemento
            if elemento.tipo not in TIPOS_RESEÑABLES:
                raise ValidationError({
                    'elemento': _(
                        'Solo se pueden reseñar películas y series del catálogo.'
                    ),
                })
            if not elemento.activo:
                raise ValidationError({
                    'elemento': _(
                        'El elemento está inactivo y no admite reseñas.'
                    ),
                })

        if self.usuario_id and self.usuario.rol != 'cliente':
            raise ValidationError({
                'usuario': _('Solo los clientes pueden publicar reseñas.'),
            })

    class Meta:
        verbose_name = 'Reseña'
        verbose_name_plural = 'Reseñas'
        ordering = ['-fecha_publicacion']
        db_table = 'marvel_resena'
        constraints = [
            models.UniqueConstraint(
                fields=['elemento', 'usuario'],
                name='resena_elemento_usuario_unique',
            ),
        ]

    def __str__(self):
        return (
            f"Reseña de {self.usuario} sobre {self.elemento.nombre} "
            f"({self.calificacion}/5)"
        )
