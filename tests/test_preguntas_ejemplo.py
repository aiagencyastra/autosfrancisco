"""Las 4 preguntas de ejemplo: lo que devuelven las herramientas coincide con una
consulta directa a la base (SQL propio + IVA calculado aparte, en céntimos enteros)."""
import os
import sqlite3
from datetime import timedelta

import pytest

from conftest import HOY_FIJO
from montelier import herramientas
from montelier.asistente import contexto_fechas
from montelier.db import conectar
from montelier.dinero import formato_eur

INICIO_MES = HOY_FIJO.replace(day=1).isoformat()                       # 2026-09-01
FIN_MES = "2026-09-30"
LUNES = (HOY_FIJO - timedelta(days=HOY_FIJO.weekday())).isoformat()    # 2026-09-21
DOMINGO = (HOY_FIJO + timedelta(days=6 - HOY_FIJO.weekday())).isoformat()


def centimos(valor):
    return int(round((valor or 0) * 100))


def iva_centimos(base_cent):
    """21% con redondeo mitad hacia arriba, solo con enteros (independiente de dinero.py)."""
    return (base_cent * 21 + 50) // 100


def totales_directos(filas):
    base = iva = 0
    for tra, mon in filas:
        b = centimos(tra) + centimos(mon)
        base += b
        iva += iva_centimos(b)
    return {"n": len(filas), "base": formato_eur(base / 100), "iva": formato_eur(iva / 100),
            "total": formato_eur((base + iva) / 100)}


@pytest.fixture
def con(bd_fija):
    c = conectar(bd_fija)
    yield c
    c.close()


@pytest.fixture
def directa(bd_fija):
    c = sqlite3.connect(bd_fija)
    yield c
    c.close()


def test_contexto_de_fechas_para_el_modelo():
    texto = contexto_fechas(HOY_FIJO)
    assert "jueves 24 de septiembre de 2026" in texto
    assert f"del {LUNES} al {DOMINGO}" in texto
    assert f"del {INICIO_MES} al {FIN_MES}" in texto


def test_pregunta_1_facturas_de_este_mes(con, directa):
    """¿Cuántas facturas llevamos este mes y por cuánto?"""
    r = herramientas.facturas_por_periodo(con, INICIO_MES, FIN_MES)
    filas = directa.execute(
        "SELECT importe_transporte, importe_montaje FROM facturas "
        "WHERE emitida = 1 AND fecha >= ? AND fecha <= ?", (INICIO_MES, FIN_MES)).fetchall()
    esperado = totales_directos(filas)
    assert r["resumen"]["numero"] == esperado["n"] == 3
    assert r["resumen"]["base_sin_iva"] == esperado["base"] == "1.665,00 €"
    assert r["resumen"]["iva_21"] == esperado["iva"] == "349,65 €"
    assert r["resumen"]["total_con_iva"] == esperado["total"] == "2.014,65 €"
    sin_emitir = directa.execute("SELECT COUNT(*) FROM facturas WHERE emitida = 0 AND fecha "
                                 "BETWEEN ? AND ?", (INICIO_MES, FIN_MES)).fetchone()[0]
    assert r["aceptadas_sin_emitir_en_periodo"] == sin_emitir == 3


def test_pregunta_2_pendientes_de_cobro(con, directa):
    """¿Qué facturas están pendientes de cobro?"""
    r = herramientas.facturas_pendientes_cobro(con)
    filas = directa.execute("SELECT id, importe_transporte, importe_montaje FROM facturas "
                            "WHERE emitida = 1 AND estado = 'pendiente' ORDER BY fecha, id").fetchall()
    esperado = totales_directos([f[1:] for f in filas])
    assert [f["factura_id"] for f in r["facturas"]] == [f[0] for f in filas]
    assert r["resumen"]["numero"] == esperado["n"] == 4
    assert r["resumen"]["total_con_iva"] == esperado["total"] == "3.121,80 €"
    for fila, factura in zip(filas, r["facturas"]):
        assert factura["total"] == totales_directos([fila[1:]])["total"]


def test_pregunta_3_peticiones_sin_presupuestar_esta_semana(con, directa):
    """¿Me queda alguna petición por presupuestar esta semana?"""
    r = herramientas.peticiones_sin_presupuestar(con, LUNES, DOMINGO)
    filas = directa.execute("SELECT id FROM peticiones WHERE presupuestada = 0 AND "
                            "fecha_peticion >= ? AND fecha_peticion <= ? ORDER BY fecha_peticion, id",
                            (LUNES, DOMINGO)).fetchall()
    assert [p["id"] for p in r["peticiones"]] == [f[0] for f in filas]
    assert r["numero"] == 4
    # La de la semana pasada sin presupuestar no entra
    total_sin_presupuestar = directa.execute(
        "SELECT COUNT(*) FROM peticiones WHERE presupuestada = 0").fetchone()[0]
    assert total_sin_presupuestar == 5


def test_pregunta_4_presupuestos_de_un_cliente(con, directa):
    """¿Qué le hemos presupuestado a Hotel Costa Daurada?"""
    r = herramientas.detalle_cliente(con, "hotel costa daurada")
    filas = directa.execute(
        "SELECT p.id, p.estado, p.importe_transporte, p.importe_montaje FROM presupuestos p "
        "JOIN clientes c ON c.id = p.cliente_id WHERE c.nombre = 'Hotel Costa Daurada SA' "
        "ORDER BY p.fecha, p.id").fetchall()
    assert r["encontrado"] is True
    lista = r["presupuestos"]["lista"]
    assert [p["presupuesto_id"] for p in lista] == [f[0] for f in filas]
    assert sorted(p["estado"] for p in lista) == ["aceptado", "pendiente", "rechazado"]
    for fila, p in zip(filas, lista):
        assert p["total"] == totales_directos([fila[2:]])["total"]
    esperado = totales_directos([f[2:] for f in filas])
    assert r["presupuestos"]["resumen"]["base_sin_iva"] == esperado["base"] == "8.010,00 €"
    assert r["presupuestos"]["resumen"]["total_con_iva"] == esperado["total"]


def test_busqueda_de_cliente_sin_tildes_y_sin_resultados(con):
    assert herramientas.detalle_cliente(con, "galeria arte")["cliente"]["nombre"] == "Galería Arte Born SL"
    assert herramientas.detalle_cliente(con, "Pepito Pérez")["encontrado"] is False
    varios = herramientas.detalle_cliente(con, "SL")
    assert varios["encontrado"] is False and len(varios["coincidencias"]) > 1


def test_periodo_sin_datos_devuelve_cero(con):
    r = herramientas.facturas_por_periodo(con, "2020-01-01", "2020-01-31")
    assert r["resumen"]["numero"] == 0
    assert r["resumen"]["total_con_iva"] == "0,00 €"
    assert r["facturas"] == []


def test_datos_de_ejemplo_segun_lo_pedido(directa):
    uno = lambda sql: directa.execute(sql).fetchone()[0]  # noqa: E731
    assert uno("SELECT COUNT(*) FROM clientes") == 12
    assert uno("SELECT COUNT(*) FROM presupuestos") == 25
    assert uno("SELECT COUNT(*) FROM facturas") == 15
    assert uno("SELECT COUNT(*) FROM peticiones") == 8
    assert uno("SELECT COUNT(*) FROM facturas WHERE estado = 'cobrada'") > 0
    assert uno("SELECT COUNT(*) FROM facturas WHERE emitida = 1 AND estado = 'pendiente'") > 0
    assert uno("SELECT COUNT(*) FROM facturas f JOIN presupuestos p ON p.id = f.presupuesto_id "
               "WHERE f.emitida = 0 AND p.estado = 'aceptado'") == 3
    assert uno("SELECT MIN(fecha) FROM facturas") >= "2026-07-01"
    assert uno("SELECT COUNT(*) FROM facturas f JOIN presupuestos p ON p.id = f.presupuesto_id "
               "WHERE p.estado <> 'aceptado'") == 0


# --------------------------------------------------------------- con Claude de verdad (opcional)

@pytest.mark.skipif(not os.environ.get("ANTHROPIC_API_KEY"), reason="Sin ANTHROPIC_API_KEY")
@pytest.mark.parametrize("pregunta, cifra", [
    ("¿Cuántas facturas llevamos este mes y por cuánto?", "2.014,65"),
    ("¿Qué facturas están pendientes de cobro?", "3.121,80"),
    ("¿Me queda alguna petición por presupuestar esta semana?", "Centro Médico Rambla"),
    ("¿Qué le hemos presupuestado a Hotel Costa Daurada?", "4.888,40"),
])
def test_claude_responde_con_las_cifras_de_la_base(bd_fija, pregunta, cifra):
    from montelier.asistente import responder
    r = responder([{"rol": "usuario", "texto": pregunta}], hoy=HOY_FIJO, ruta_bd=bd_fija)
    assert r["consultas"], "Debe consultar la base"
    assert cifra in r["texto"], r["texto"]
