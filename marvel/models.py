from django.db import models

from marvel.constants import TIPOS_ELEMENTO


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
