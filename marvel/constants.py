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
