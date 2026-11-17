# Valores de "tipo" tomados de los responses reales de MCU API
# (campo "type": movie / tvshow / character). Etiquetas en espanol
# para la interfaz.
TIPOS_ELEMENTO = [
    ('movie', 'Pelicula'),
    ('tvshow', 'Serie'),
    ('character', 'Personaje'),
]

# URL base de MCU API. Se define aqui como referencia documentada;
# el cliente HTTP se implementara en la Fase B2.
MCUAPI_BASE_URL = 'https://mcuapi.up.railway.app/api/v1'
