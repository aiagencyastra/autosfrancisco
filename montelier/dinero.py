"""Cálculo de IVA y formato de importes.

Todos los importes de la base van SIN IVA. El IVA se calcula siempre aquí,
con Decimal y redondeo comercial (mitad hacia arriba) a céntimos.
"""
from decimal import Decimal, ROUND_HALF_UP

TIPO_IVA = Decimal("0.21")
CENTIMO = Decimal("0.01")


def a_decimal(valor) -> Decimal:
    if valor is None:
        return Decimal("0.00")
    if isinstance(valor, Decimal):
        return valor
    # str() evita arrastrar el error binario del float (0.1 -> 0.1000000000000000055...)
    return Decimal(str(valor))


def redondear(valor) -> Decimal:
    return a_decimal(valor).quantize(CENTIMO, rounding=ROUND_HALF_UP)


def desglose(importe_transporte, importe_montaje=None) -> dict:
    """Base, IVA y total de una factura a partir de sus importes sin IVA."""
    transporte = redondear(importe_transporte)
    montaje = redondear(importe_montaje)
    base = transporte + montaje
    iva = redondear(base * TIPO_IVA)
    return {
        "transporte": transporte,
        "montaje": montaje,
        "base": base,
        "iva": iva,
        "total": base + iva,
    }


def sumar_desgloses(desgloses) -> dict:
    """Suma de varias facturas: el IVA total es la suma de los IVA de cada factura
    (ya redondeados), igual que en un libro de facturas emitidas."""
    total = {"transporte": Decimal("0.00"), "montaje": Decimal("0.00"),
             "base": Decimal("0.00"), "iva": Decimal("0.00"), "total": Decimal("0.00")}
    for d in desgloses:
        for clave in total:
            total[clave] += d[clave]
    return total


def formato_eur(valor) -> str:
    """1210 -> '1.210,00 €'"""
    cantidad = redondear(valor)
    signo = "-" if cantidad < 0 else ""
    entero, decimales = f"{abs(cantidad):.2f}".split(".")
    grupos = []
    while len(entero) > 3:
        grupos.insert(0, entero[-3:])
        entero = entero[:-3]
    grupos.insert(0, entero)
    return f"{signo}{'.'.join(grupos)},{decimales} €"


def desglose_formateado(d: dict) -> dict:
    return {clave: formato_eur(valor) for clave, valor in d.items()}
