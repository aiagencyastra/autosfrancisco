from decimal import Decimal

import pytest

from montelier.dinero import desglose, formato_eur, redondear, sumar_desgloses


def test_iva_basico():
    d = desglose(1000, None)
    assert d["base"] == Decimal("1000.00")
    assert d["iva"] == Decimal("210.00")
    assert d["total"] == Decimal("1210.00")


def test_transporte_mas_montaje():
    d = desglose(460.00, 1234.55)
    assert d["base"] == Decimal("1694.55")
    assert d["iva"] == Decimal("355.86")      # 355,8555 -> 355,86
    assert d["total"] == Decimal("2050.41")


@pytest.mark.parametrize("base, iva", [
    ("0.50", "0.11"),     # 0,105 -> 0,11 (con float y round() saldría 0,10)
    ("10.05", "2.11"),    # 2,1105
    ("2.50", "0.53"),     # 0,525 -> redondeo comercial hacia arriba
    ("0.02", "0.00"),     # 0,0042
    ("12.50", "2.63"),    # 2,625
])
def test_redondeo_mitad_hacia_arriba(base, iva):
    assert desglose(Decimal(base))["iva"] == Decimal(iva)


def test_floats_de_la_base_no_arrastran_error():
    # 0.1 + 0.2 en float es 0.30000000000000004
    d = desglose(0.1, 0.2)
    assert d["base"] == Decimal("0.30")
    assert d["iva"] == Decimal("0.06")


def test_montaje_nulo_cuenta_como_cero():
    assert desglose(285, None)["montaje"] == Decimal("0.00")
    assert desglose(285, None)["total"] == Decimal("344.85")


def test_total_es_base_mas_iva_siempre():
    for centimos in range(0, 100_000, 7):
        d = desglose(Decimal(centimos) / 100)
        assert d["total"] == d["base"] + d["iva"]
        assert d["iva"] == d["iva"].quantize(Decimal("0.01"))


def test_suma_de_facturas_suma_ivas_redondeados():
    total = sumar_desgloses([desglose("0.50"), desglose("0.50")])
    # cada factura 0,11 de IVA -> 0,22 (no 0,21 que saldría de redondear la suma de bases)
    assert total["iva"] == Decimal("0.22")
    assert total["total"] == Decimal("1.22")


@pytest.mark.parametrize("valor, texto", [
    (1210, "1.210,00 €"),
    (0, "0,00 €"),
    (5.5, "5,50 €"),
    (999.999, "1.000,00 €"),
    (1234567.891, "1.234.567,89 €"),
    (Decimal("-45.10"), "-45,10 €"),
    (None, "0,00 €"),
])
def test_formato_espanol(valor, texto):
    assert formato_eur(valor) == texto


def test_redondear():
    assert redondear("2.675") == Decimal("2.68")   # float 2.675 es 2.67499999...
    assert redondear(2.675) == Decimal("2.68")
