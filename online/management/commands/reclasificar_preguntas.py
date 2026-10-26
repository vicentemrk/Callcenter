"""
Comando para reclasificar las preguntas existentes con la IA actual.

Uso:
    python manage.py reclasificar_preguntas            # simulacion (no escribe)
    python manage.py reclasificar_preguntas --aplicar  # guarda los cambios

Procesa las preguntas en lotes de 20 para que el proveedor remoto reciba una
sola solicitud por lote. Si no hay clave o el proveedor falla, las preguntas
del lote quedan como 'otros' sin detener el proceso.
"""

from django.core.management.base import BaseCommand

from online.ia_utils import AsistenteIA
from online.models import Preguntas

TAMANO_LOTE = 20


class Command(BaseCommand):
    help = 'Reclasifica las preguntas existentes (por defecto en modo simulacion).'

    def add_arguments(self, parser):
        parser.add_argument(
            '--aplicar',
            action='store_true',
            help='Guarda los cambios en la base de datos. Sin este flag no escribe.',
        )

    def handle(self, *args, **options):
        aplicar = options['aplicar']
        asistente = AsistenteIA()

        ids = list(
            Preguntas.objects.order_by('idPregunta')
            .values_list('idPregunta', flat=True)
        )
        if not ids:
            self.stdout.write('No hay preguntas registradas.')
            return

        total = len(ids)
        cambios = 0
        self.stdout.write(
            f'Revisando {total} pregunta(s) en lotes de {TAMANO_LOTE}...'
        )
        if not aplicar:
            self.stdout.write(
                'Modo simulacion: no se escribira nada. Usa --aplicar para guardar.'
            )

        for inicio in range(0, total, TAMANO_LOTE):
            lote_ids = ids[inicio:inicio + TAMANO_LOTE]
            lote = list(
                Preguntas.objects.filter(idPregunta__in=lote_ids)
                .order_by('idPregunta')
            )
            textos = [pregunta.Pregunta for pregunta in lote]
            nuevas = asistente.clasificar_preguntas(textos)

            for pregunta, nueva in zip(lote, nuevas):
                if nueva == pregunta.categoria:
                    continue
                cambios += 1
                self.stdout.write(
                    f'{pregunta.idPregunta}: {pregunta.categoria} -> {nueva}'
                )
                if aplicar:
                    pregunta.categoria = nueva
                    pregunta.save(update_fields=['categoria'])

            self.stdout.write(
                f'Lote {inicio // TAMANO_LOTE + 1}: '
                f'{len(lote)} pregunta(s) revisada(s).'
            )

        if aplicar:
            self.stdout.write(
                f'Listo: {cambios} pregunta(s) actualizada(s) de {total}.'
            )
        else:
            self.stdout.write(
                f'Simulacion terminada: {cambios} pregunta(s) se actualizarian '
                f'de {total}. Ejecuta con --aplicar para guardar.'
            )
