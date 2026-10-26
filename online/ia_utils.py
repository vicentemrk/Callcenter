import json

from openai import OpenAI
from django.conf import settings

from online.constants import CATEGORIAS_PREGUNTA

class AsistenteIA:
    def __init__(self):
        self.api_key = settings.OPENAI_API_KEY

    def _client(self):
        if not self.api_key:
            raise RuntimeError("La variable de entorno OPENAI_API_KEY no está configurada.")
        return OpenAI(api_key=self.api_key)
    
    def generar_respuesta_automatica(self, pregunta, historial_contexto=""):
        """
        Genera una respuesta automática usando IA
        """
        try:
            prompt = f"""
            Eres un asistente técnico especializado en videojuegos y hardware gaming.
            
            Contexto del historial: {historial_contexto}
            
            Pregunta del usuario: {pregunta}
            
            Por favor, proporciona una respuesta útil, técnica pero comprensible.
            Si necesitas más información, pídela amablemente.
            Mantén un tono profesional pero cercano.
            
            Respuesta:
            """
            
            response = self._client().chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {"role": "system", "content": "Eres un experto técnico en videojuegos y hardware gaming."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.7
            )
            
            return (response.choices[0].message.content or "").strip()
            
        except Exception:
            return (
                "Lo siento, el asistente no está disponible en este momento. "
                "Inténtalo nuevamente más tarde."
            )
    
    def clasificar_preguntas(self, preguntas):
        """
        Clasifica una lista de preguntas en una sola llamada a OpenAI.
        Devuelve una lista de categorías en el mismo orden que la entrada.
        """
        preguntas = list(preguntas)
        if not preguntas:
            return []

        categorias = [valor for valor, _ in CATEGORIAS_PREGUNTA]
        textos = [str(pregunta or "").strip()[:500] for pregunta in preguntas]

        textos_unicos = []
        indice_por_texto = {}
        for texto in textos:
            if texto and texto not in indice_por_texto:
                indice_por_texto[texto] = len(textos_unicos)
                textos_unicos.append(texto)

        if not textos_unicos:
            return ["otros"] * len(preguntas)

        try:
            listado = "\n".join(
                f"{indice}. {texto}"
                for indice, texto in enumerate(textos_unicos, 1)
            )
            prompt = f"""
            Clasifica cada pregunta en una de estas categorías: {', '.join(categorias)}.

            Responde únicamente con un arreglo JSON de strings, en el mismo orden,
            sin explicaciones ni texto adicional.

            Preguntas:
            {listado}
            """

            response = self._client().chat.completions.create(
                model="gpt-3.5-turbo",
                messages=[
                    {
                        "role": "system",
                        "content": (
                            "Eres un clasificador de soporte técnico. "
                            "Responde solo con JSON válido."
                        )
                    },
                    {"role": "user", "content": prompt}
                ],
                max_tokens=500,
                temperature=0.1
            )

            contenido = (response.choices[0].message.content or "").strip()
            inicio = contenido.find("[")
            fin = contenido.rfind("]")
            if inicio != -1 and fin > inicio:
                contenido = contenido[inicio:fin + 1]

            resultado = json.loads(contenido)
            if isinstance(resultado, dict):
                resultado = next(
                    (
                        valor for valor in resultado.values()
                        if isinstance(valor, list)
                    ),
                    []
                )
            if not isinstance(resultado, list) or len(resultado) != len(textos_unicos):
                return ["otros"] * len(preguntas)

            categorias_unicas = []
            for categoria in resultado:
                if isinstance(categoria, dict):
                    categoria = categoria.get("categoria", "otros")
                categoria = str(categoria).strip().lower()
                categorias_unicas.append(
                    categoria if categoria in categorias else "otros"
                )

            return [
                categorias_unicas[indice_por_texto[texto]]
                if texto else "otros"
                for texto in textos
            ]

        except Exception:
            return ["otros"] * len(preguntas)

    def clasificar_pregunta(self, pregunta):
        """
        Clasifica una sola pregunta usando el flujo por lote.
        """
        return self.clasificar_preguntas([pregunta])[0]