import re # Expression regular para validar el formato del RUT

from django.core.exceptions import ValidationError


def validar_rut_chileno(rut):
    rut_normalizado = str(rut or "").replace(".", "").replace(" ", "").upper()
    # Validar el formato del RUT (sin puntos y con guion)
    # \d represneta cualquier digito del 0 al 9, {7,8} indica que debe tener entre 7 y 8 digitos, 
    # y [\dK] indica que el ultimo caracter puede ser un digito o la letra K
    if not re.fullmatch(r"\d{7,8}-[\dK]", rut_normalizado):
        raise ValidationError(
            "Ingresa un RUT válido con formato 12.345.678-5."
        )
    cuerpo, verificador = rut_normalizado.split("-")
    suma = 0
    multiplicador = 2

    for digito in reversed(cuerpo):
        suma += int(digito) * multiplicador
        multiplicador = 2 if multiplicador == 7 else multiplicador + 1

    resto = 11 - (suma % 11)
    verificador_calculado = (
        "0" if resto == 11 else "K" if resto == 10 else str(resto)
    )

    if verificador != verificador_calculado:
        raise ValidationError("El dígito verificador del RUT no es válido.")
