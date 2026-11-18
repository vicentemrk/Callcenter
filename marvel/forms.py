"""Formulario de publicacion de reseñas (Bloque 5C).

Solo el cliente edita dos campos: calificacion (1..5) y
referencia_tematica (10..200). El autor, el elemento, el estado
visible y la fecha se asignan EXCLUSIVAMENTE en el servidor (vista
Detalle): el POST no puede definirlos ni suplantarlos.

Las validaciones del modelo (calificacion 1..5, referencia tematica
con trim y minimo 10 caracteres) viajan con los campos, porque el
ModelForm copia los validators del modelo a los campos del form.
"""

from django import forms

from marvel.models import Resena


class ResenaForm(forms.ModelForm):
    """Alta de reseña de un cliente sobre una ficha del catalogo."""

    class Meta:
        model = Resena
        fields = ['calificacion', 'referencia_tematica']
        widgets = {
            'referencia_tematica': forms.Textarea(
                attrs={
                    'rows': 3,
                    'maxlength': 200,
                    'placeholder': (
                        'Cita, personaje, escena o saga de Marvel al '
                        'que refiere tu reseña...'
                    ),
                },
            ),
        }
        labels = {
            'calificacion': 'Calificación',
            'referencia_tematica': 'Referencia temática',
        }
