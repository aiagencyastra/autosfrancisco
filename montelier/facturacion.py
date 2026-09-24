"""Pestaña Facturas: facturas aceptadas sin emitir, vista previa, PDF y estado de la demo.

Nunca escribe en la base del cliente. Lo que se "emite" o "envía" en la demo se
guarda en datos/estado_demo.json.
"""
import json
import threading
from datetime import date, datetime
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import Flowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from .db import RUTA_BD, conectar
from .dinero import desglose, desglose_formateado

EMPRESA = {
    "nombre": "MONTELIER",
    "razon_social": "Montelier (razón social pendiente)",
    "nif": "pendiente",
    "direccion": "pendiente",
    "email": "pendiente",
    "telefono": "pendiente",
}

_bloqueo = threading.Lock()


# ---------------------------------------------------------------- lectura (base del cliente)

SQL_DETALLE = """
    SELECT f.id, f.fecha, f.importe_transporte, f.importe_montaje, f.estado, f.emitida,
           p.id AS presupuesto_id, p.tipo_servicio, p.dias_montaje, p.fecha AS fecha_presupuesto,
           p.direccion AS direccion_servicio, p.comentario,
           c.id AS cliente_id, c.nombre, c.email, c.telefono, c.direccion AS direccion_cliente
    FROM facturas f
    JOIN presupuestos p ON p.id = f.presupuesto_id
    JOIN clientes c ON c.id = p.cliente_id
"""


def _a_dict(fila) -> dict:
    d = desglose(fila["importe_transporte"], fila["importe_montaje"])
    return {
        "id": fila["id"],
        "fecha": fila["fecha"],
        "presupuesto_id": fila["presupuesto_id"],
        "servicio": "Transporte y montaje" if fila["tipo_servicio"] == "transporte_montaje" else "Transporte",
        "dias_montaje": fila["dias_montaje"],
        "descripcion": fila["comentario"],
        "direccion_servicio": fila["direccion_servicio"],
        "cliente": {"id": fila["cliente_id"], "nombre": fila["nombre"], "email": fila["email"],
                    "telefono": fila["telefono"], "direccion": fila["direccion_cliente"]},
        "importes": desglose_formateado(d),
        "tiene_montaje": fila["importe_montaje"] is not None,
    }


def facturas_por_emitir(ruta_bd=None) -> list[dict]:
    """Facturas de presupuestos aceptados que aún no están emitidas en la base del cliente."""
    con = conectar(ruta_bd)
    try:
        filas = con.execute(SQL_DETALLE + """ WHERE f.emitida = 0 AND p.estado = 'aceptado'
                                             ORDER BY f.fecha, f.id""").fetchall()
        return [_a_dict(f) for f in filas]
    finally:
        con.close()


def detalle_factura(factura_id: int, ruta_bd=None) -> dict | None:
    con = conectar(ruta_bd)
    try:
        fila = con.execute(SQL_DETALLE + " WHERE f.id = ?", (factura_id,)).fetchone()
        return _a_dict(fila) if fila else None
    finally:
        con.close()


# ---------------------------------------------------------------- estado propio de la demo

def ruta_estado() -> Path:
    return RUTA_BD.with_name("estado_demo.json")


def carpeta_pdfs() -> Path:
    carpeta = RUTA_BD.with_name("pdfs")
    carpeta.mkdir(parents=True, exist_ok=True)
    return carpeta


def leer_estado() -> dict:
    ruta = ruta_estado()
    if ruta.exists():
        return json.loads(ruta.read_text(encoding="utf-8"))
    return {"emitidas": {}, "enviadas": {}, "registro": []}


def _guardar_estado(estado: dict):
    ruta = ruta_estado()
    temporal = ruta.with_suffix(".tmp")
    temporal.write_text(json.dumps(estado, ensure_ascii=False, indent=2), encoding="utf-8")
    temporal.replace(ruta)


def registrar(texto: str, tipo: str = "info") -> dict:
    with _bloqueo:
        estado = leer_estado()
        entrada = {"hora": datetime.now().strftime("%H:%M:%S"), "texto": texto, "tipo": tipo}
        estado["registro"].append(entrada)
        _guardar_estado(estado)
        return entrada


def marcar_emitida(factura_id: int, pdf: str):
    with _bloqueo:
        estado = leer_estado()
        estado["emitidas"][str(factura_id)] = {"fecha": date.today().isoformat(), "pdf": pdf}
        _guardar_estado(estado)


def marcar_enviada(factura_id: int, email: str):
    with _bloqueo:
        estado = leer_estado()
        estado["enviadas"][str(factura_id)] = {"hora": datetime.now().strftime("%H:%M"), "email": email}
        _guardar_estado(estado)


def reiniciar_estado():
    with _bloqueo:
        ruta_estado().unlink(missing_ok=True)
        for pdf in carpeta_pdfs().glob("*.pdf"):
            pdf.unlink()


# ---------------------------------------------------------------- PDF

AZUL = colors.HexColor("#12355B")
GRIS = colors.HexColor("#5B6573")
LINEA = colors.HexColor("#D5DAE1")
FONDO = colors.HexColor("#F3F5F8")


class Logo(Flowable):
    """Logo provisional: texto MONTELIER en un recuadro."""

    def __init__(self, ancho=62 * mm, alto=16 * mm):
        super().__init__()
        self.width, self.height = ancho, alto

    def draw(self):
        c = self.canv
        c.setFillColor(AZUL)
        c.roundRect(0, 0, self.width, self.height, 2 * mm, stroke=0, fill=1)
        c.setFillColor(colors.white)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(self.width / 2, self.height / 2 - 6, "MONTELIER")
        c.setFont("Helvetica", 6.5)
        c.drawCentredString(self.width / 2, 2.2 * mm, "TRANSPORTE Y MONTAJE · LOGO PROVISIONAL")


class RecuadroVerifactu(Flowable):
    def __init__(self, ancho=62 * mm, alto=30 * mm):
        super().__init__()
        self.width, self.height = ancho, alto

    def draw(self):
        c = self.canv
        c.setStrokeColor(GRIS)
        c.setDash(4, 3)
        c.rect(0, 0, self.width, self.height)
        c.setDash()
        c.setFillColor(GRIS)
        c.setFont("Helvetica", 8.5)
        for i, linea in enumerate(["Aquí irá el QR Verifactu", "del software de facturación"]):
            c.drawCentredString(self.width / 2, self.height / 2 + 4 - i * 11, linea)


def generar_pdf(factura: dict, destino: Path, fecha_emision: date | None = None) -> Path:
    fecha_emision = fecha_emision or date.today()
    est = {
        "normal": ParagraphStyle("n", fontName="Helvetica", fontSize=9, leading=12, textColor=colors.black),
        "gris": ParagraphStyle("g", fontName="Helvetica", fontSize=8.5, leading=11.5, textColor=GRIS),
        "etiqueta": ParagraphStyle("e", fontName="Helvetica-Bold", fontSize=7.5, leading=10, textColor=GRIS),
        "titulo": ParagraphStyle("t", fontName="Helvetica-Bold", fontSize=20, leading=24,
                                 textColor=AZUL, alignment=TA_RIGHT),
        "der": ParagraphStyle("d", fontName="Helvetica", fontSize=9, leading=12, alignment=TA_RIGHT),
        "pie": ParagraphStyle("p", fontName="Helvetica", fontSize=7.5, leading=10,
                              textColor=GRIS, alignment=TA_CENTER),
    }
    P = Paragraph
    imp = factura["importes"]
    cli = factura["cliente"]

    def esc(texto):
        return (str(texto or "")).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    cabecera = Table([[
        [Logo(), Spacer(1, 3 * mm),
         P(f"<b>{EMPRESA['razon_social']}</b><br/>NIF: {EMPRESA['nif']}<br/>"
           f"Dirección: {EMPRESA['direccion']}<br/>Email: {EMPRESA['email']} · Tel.: {EMPRESA['telefono']}",
           est["gris"])],
        [P("FACTURA", est["titulo"]), Spacer(1, 2 * mm),
         P(f"Nº de factura: <i>lo asignará el software de facturación</i><br/>"
           f"Referencia interna: F-{factura['id']:04d} · Presupuesto P-{factura['presupuesto_id']:04d}<br/>"
           f"Fecha de emisión: {fecha_emision.strftime('%d/%m/%Y')}<br/>"
           f"Fecha del servicio: {date.fromisoformat(factura['fecha']).strftime('%d/%m/%Y')}",
           est["der"])],
    ]], colWidths=[95 * mm, 75 * mm])
    cabecera.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                  ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                  ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))

    datos_cliente = Table([[
        [P("FACTURAR A", est["etiqueta"]),
         P(f"<b>{esc(cli['nombre'])}</b><br/>{esc(cli['direccion'])}<br/>"
           f"{esc(cli['email'])} · {esc(cli['telefono'])}", est["normal"])],
        [P("SERVICIO", est["etiqueta"]),
         P(f"<b>{esc(factura['servicio'])}</b><br/>{esc(factura['descripcion'])}<br/>"
           f"Lugar: {esc(factura['direccion_servicio'])}", est["normal"])],
    ]], colWidths=[85 * mm, 85 * mm])
    datos_cliente.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BACKGROUND", (0, 0), (-1, -1), FONDO),
        ("BOX", (0, 0), (-1, -1), 0.5, LINEA),
        ("LINEAFTER", (0, 0), (0, 0), 0.5, LINEA),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))

    lineas = [["Concepto", "Importe"], ["Transporte", imp["transporte"]]]
    if factura["tiene_montaje"]:
        dias = factura["dias_montaje"]
        texto_dias = f" ({dias} día{'s' if dias != 1 else ''})" if dias else ""
        lineas.append([f"Montaje{texto_dias}", imp["montaje"]])
    n_conceptos = len(lineas)
    lineas += [["Base imponible", imp["base"]], ["IVA 21%", imp["iva"]], ["TOTAL", imp["total"]]]
    tabla = Table(lineas, colWidths=[130 * mm, 40 * mm])
    tabla.setStyle(TableStyle([
        ("FONT", (0, 0), (-1, -1), "Helvetica", 9.5),
        ("FONT", (0, 0), (-1, 0), "Helvetica-Bold", 8.5),
        ("TEXTCOLOR", (0, 0), (-1, 0), GRIS),
        ("LINEBELOW", (0, 0), (-1, 0), 0.8, AZUL),
        ("LINEBELOW", (0, 1), (-1, n_conceptos - 1), 0.4, LINEA),
        ("LINEABOVE", (0, n_conceptos), (-1, n_conceptos), 0.8, LINEA),
        ("TEXTCOLOR", (0, n_conceptos), (-1, n_conceptos + 1), GRIS),
        ("FONT", (0, -1), (-1, -1), "Helvetica-Bold", 12),
        ("TEXTCOLOR", (0, -1), (-1, -1), colors.white),
        ("BACKGROUND", (0, -1), (-1, -1), AZUL),
        ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]))

    pie = Table([[
        RecuadroVerifactu(),
        P("Importes en euros. Forma de pago: <i>pendiente de definir</i>.<br/>"
          "IBAN: <i>pendiente</i>.", est["gris"]),
    ]], colWidths=[70 * mm, 100 * mm])
    pie.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                             ("LEFTPADDING", (0, 0), (-1, -1), 0)]))

    def aviso(canvas, doc):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(GRIS)
        canvas.drawCentredString(A4[0] / 2, 12 * mm,
                                 "Documento de demostración · sin validez fiscal · "
                                 "datos de la empresa pendientes")
        canvas.restoreState()

    destino = Path(destino)
    destino.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(str(destino), pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=18 * mm, bottomMargin=20 * mm,
                            title=f"Factura F-{factura['id']:04d} - {cli['nombre']}",
                            author="Montelier (demo)")
    doc.build([cabecera, Spacer(1, 10 * mm), datos_cliente, Spacer(1, 10 * mm), tabla,
               Spacer(1, 12 * mm), pie], onFirstPage=aviso, onLaterPages=aviso)
    return destino
