"""Emisión y envío de facturas desde el chat: Claude prepara, Francisco aprueba con Sí/No."""
import hashlib

import pytest

from montelier import asistente, facturacion
from montelier.acciones_chat import AccionesChat
from montelier.db import RUTA_BD
from montelier.herramientas import ErrorHerramienta
from test_solo_lectura import ClaudeFalso, _bloque_herramienta, _bloque_texto


@pytest.fixture(autouse=True)
def demo_limpia():
    import app  # noqa: F401  (crea la base de la demo si no existe)
    facturacion.reiniciar_estado()
    yield
    facturacion.reiniciar_estado()


def huella():
    return hashlib.sha256(RUTA_BD.read_bytes()).hexdigest()


def test_facturas_por_emitir():
    datos, accion = AccionesChat().ejecutar("facturas_por_emitir", {})
    assert accion is None
    assert len(datos["pendientes_de_emitir"]) == 3
    assert datos["emitidas_hoy_en_la_demo"] == []
    assert all("€" in f["total"] for f in datos["pendientes_de_emitir"])


def test_claude_solo_pide_aprobacion_no_emite():
    antes = huella()
    factura_id = facturacion.facturas_por_emitir()[0]["id"]
    falso = ClaudeFalso([
        [_bloque_herramienta("t1", "pedir_aprobacion_emision", {"factura_id": factura_id})],
        [_bloque_texto("Te la dejo aquí para que la apruebes.")],
    ])
    r = asistente.responder([{"rol": "usuario", "texto": "Emite la factura"}], cliente=falso,
                            acciones=AccionesChat())
    assert r["texto"] == "Te la dejo aquí para que la apruebes."
    assert r["consultas"] == ["pedir_aprobacion_emision"]
    [accion] = r["acciones"]
    assert accion["tipo"] == "aprobacion" and accion["factura"]["id"] == factura_id
    assert accion["mensaje"].endswith("¿La emito?")
    estado = facturacion.leer_estado()
    assert estado["emitidas"] == {}                      # sin el Sí de Francisco no se emite
    assert estado["registro"][-1]["tipo"] == "whatsapp"
    assert huella() == antes                             # la base del cliente no cambia


def test_enviar_exige_factura_emitida():
    acciones = AccionesChat()
    factura_id = facturacion.facturas_por_emitir()[0]["id"]
    with pytest.raises(ErrorHerramienta, match="todavía no está emitida"):
        acciones.ejecutar("enviar_factura_cliente", {"factura_id": factura_id})
    facturacion.marcar_emitida(factura_id, "f.pdf")     # lo que hace el botón Sí
    datos, accion = acciones.ejecutar("enviar_factura_cliente", {"factura_id": factura_id})
    assert datos["enviada"] is True and accion["tipo"] == "enviada"
    assert str(factura_id) in facturacion.leer_estado()["enviadas"]
    with pytest.raises(ErrorHerramienta, match="ya está emitida"):
        acciones.ejecutar("pedir_aprobacion_emision", {"factura_id": factura_id})


@pytest.mark.parametrize("argumentos", [{"factura_id": 1}, {"factura_id": 999}, {}, {"factura_id": "x"}])
def test_facturas_que_no_se_pueden_emitir(argumentos):
    with pytest.raises(ErrorHerramienta):
        AccionesChat().ejecutar("pedir_aprobacion_emision", argumentos)


def test_error_de_accion_llega_al_modelo_como_error():
    falso = ClaudeFalso([
        [_bloque_herramienta("t1", "enviar_factura_cliente", {"factura_id": 12})],
        [_bloque_texto("Primero hay que emitirla.")],
    ])
    r = asistente.responder([{"rol": "usuario", "texto": "Envíala"}], cliente=falso, acciones=AccionesChat())
    resultado = falso.peticiones[1][-1]["content"][0]
    assert resultado["is_error"] and "no está emitida" in resultado["content"]
    assert r["acciones"] == []
