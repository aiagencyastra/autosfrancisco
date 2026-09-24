"""PDF de factura y flujo de la pestaña Facturas (sin tocar la base del cliente)."""
import hashlib
from datetime import date

import pytest
from pypdf import PdfReader

from montelier import facturacion


def texto_pdf(ruta):
    return "\n".join(p.extract_text() for p in PdfReader(ruta).pages)


def test_pdf_de_cada_factura_por_emitir(bd_fija, tmp_path):
    facturas = facturacion.facturas_por_emitir(bd_fija)
    assert len(facturas) == 3
    for f in facturas:
        ruta = facturacion.generar_pdf(f, tmp_path / f"f{f['id']}.pdf", date(2026, 9, 24))
        assert ruta.read_bytes().startswith(b"%PDF")
        texto = texto_pdf(ruta)
        assert "MONTELIER" in texto
        assert "NIF: pendiente" in texto
        assert "Aquí irá el QR Verifactu" in texto and "del software de facturación" in texto
        assert f["cliente"]["nombre"] in texto
        for clave in ("transporte", "base", "iva", "total"):
            assert f["importes"][clave] in texto
        assert ("Montaje" in texto) == f["tiene_montaje"]
        assert "24/09/2026" in texto


def test_pdf_cifras_concretas(bd_fija, tmp_path):
    f = facturacion.detalle_factura(12, bd_fija)
    texto = texto_pdf(facturacion.generar_pdf(f, tmp_path / "f.pdf"))
    for cifra in ("460,00 €", "1.234,55 €", "1.694,55 €", "355,86 €", "2.050,41 €"):
        assert cifra in texto


def test_pdf_con_caracteres_especiales(tmp_path):
    f = {"id": 1, "presupuesto_id": 1, "fecha": "2026-09-01", "servicio": "Transporte",
         "dias_montaje": None, "descripcion": "Piano & sofá <grande> · 3º 2ª", "direccion_servicio": "Ñ",
         "cliente": {"nombre": "Ça & Cía", "direccion": "C/ Àngel", "email": "a@b.es", "telefono": "1"},
         "importes": {"transporte": "1,00 €", "montaje": "0,00 €", "base": "1,00 €", "iva": "0,21 €",
                      "total": "1,21 €"}, "tiene_montaje": False}
    texto = texto_pdf(facturacion.generar_pdf(f, tmp_path / "raro.pdf"))
    assert "Ça & Cía" in texto and "<grande>" in texto


# --------------------------------------------------------------- flujo web

@pytest.fixture
def web():
    import app as modulo
    facturacion.reiniciar_estado()
    modulo.app.testing = True
    yield modulo.app.test_client()
    facturacion.reiniciar_estado()


def test_flujo_emitir_y_enviar(web):
    from montelier.db import RUTA_BD
    huella = hashlib.sha256(RUTA_BD.read_bytes()).hexdigest()

    datos = web.get("/api/facturas").get_json()
    assert len(datos["pendientes"]) == 3 and datos["emitidas"] == []
    f = datos["pendientes"][0]

    assert web.post(f"/api/facturas/{f['id']}/enviar").status_code == 409  # sin emitir, no se envía

    msg = web.post(f"/api/facturas/{f['id']}/solicitar").get_json()["mensaje"]
    assert msg == f"Factura a {f['cliente']['nombre']}, {f['importes']['total']}. ¿La emito?"

    # Francisco dice que no: sigue pendiente
    assert web.post(f"/api/facturas/{f['id']}/aprobar", json={"aprobada": False}).get_json()["emitida"] is False
    assert len(web.get("/api/facturas").get_json()["pendientes"]) == 3

    # Se vuelve a pedir y Francisco dice que sí: PDF y pasa a emitidas
    web.post(f"/api/facturas/{f['id']}/solicitar")
    r = web.post(f"/api/facturas/{f['id']}/aprobar", json={"aprobada": True}).get_json()
    assert r["emitida"] is True
    pdf = web.get(r["pdf"])
    assert pdf.status_code == 200 and pdf.data.startswith(b"%PDF")

    r = web.post(f"/api/facturas/{f['id']}/enviar").get_json()
    assert r["enviada"] is True and r["email"] == f["cliente"]["email"]

    datos = web.get("/api/facturas").get_json()
    assert len(datos["pendientes"]) == 2
    assert datos["emitidas"][0]["enviada_demo"]["email"] == f["cliente"]["email"]
    tipos = [e["tipo"] for e in datos["registro"]]
    assert tipos == ["whatsapp", "no", "whatsapp", "ok", "envio"]

    # La base del cliente no se ha tocado: el estado va en un archivo aparte
    assert hashlib.sha256(RUTA_BD.read_bytes()).hexdigest() == huella
    assert facturacion.ruta_estado().exists()


def test_chat_sin_clave_da_mensaje_claro(web, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = web.post("/api/chat", json={"historial": [{"rol": "usuario", "texto": "hola"}]})
    assert r.status_code == 503 and "ANTHROPIC_API_KEY" in r.get_json()["error"]


def test_portada_y_config(web):
    assert web.get("/").status_code == 200
    cfg = web.get("/api/config").get_json()
    assert len(cfg["preguntas"]) == 4
