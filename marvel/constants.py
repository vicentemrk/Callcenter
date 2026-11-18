# Valores de "tipo" tomados de los responses reales de MCU API
# (campo "type": movie / tvshow). Etiquetas en espanol para la interfaz.
# Los personajes se sacaron del catalogo: solo se alimentan peliculas y
# series, porque este catalogo respalda los tickets del Call Center.
TIPOS_ELEMENTO = [
    ('movie', 'Pelicula'),
    ('tvshow', 'Serie'),
]

# URL base de MCU API. Se define aqui como referencia documentada;
# el cliente HTTP se implementa en mcu_client.py.
MCUAPI_BASE_URL = 'https://mcuapi.up.railway.app/api/v1'

# ---------------------------------------------------------------------------
# Resenas (Bloque 5B): reglas aprobadas por el propietario.
# - Solo movie/tvshow (los personajes ya no existen en el catalogo).
# - Calificacion obligatoria 1..5; sin comentario adicional.
# - Referencia tematica obligatoria: 10..200 caracteres tras limpiar
#   espacios de los extremos (no vale texto de solo espacios).
# ---------------------------------------------------------------------------
TIPOS_RESEÑABLES = {'movie', 'tvshow'}

CALIFICACION_MINIMA = 1
CALIFICACION_MAXIMA = 5

REFERENCIA_MINIMA = 10
REFERENCIA_MAXIMA = 200
