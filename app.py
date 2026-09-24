"""Servidor de la demo de Montelier.  Arranque:  ./arrancar.sh  (o  python app.py)"""
import os
from datetime import date

import anthropic
from dotenv import load_dotenv
from flask import Flask, abort, jsonify, request, send_file, send_from_directory

load_dotenv()

import crear_base  # noqa: E402  (después de load_dotenv por si MONTELIER_BD viene del .env)
from montelier import asistente, facturacion  # noqa: E402
from montelier.db import RUTA_BD  # noqa: E402

CLIENTE_EJEMPLO = "Hotel Costa Daurada"
PREGUNTAS = [
    "¿Cuántas facturas llevamos este mes y por cuánto?",
    "¿Qué facturas están pendientes de cobro?",
    "¿Me queda alguna petición por presupuestar esta semana?",
    f"¿Qué le hemos presupuestado a {CLIENTE_EJEMPLO}?",
]

app = Flask(__name__, static_folder="static", static_url_path="/static")


def preparar_base():
    hoy = date.today()
    if crear_base.necesita_regenerar(RUTA_BD, hoy):
        crear_base.crear(RUTA_BD, hoy)
        facturacion.reiniciar_estado()


@app.get("/")
def inicio():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/api/config")
def config():
    return jsonify(preguntas=PREGUNTAS, hay_clave=bool(os.environ.get("ANTHROPIC_API_KEY")),
                   modelo=asistente.MODELO)


# ---------------------------------------------------------------- Asistente

@app.post("/api/chat")
def chat():
    historial = (request.get_json(silent=True) or {}).get("historial") or []
    if not historial or historial[-1].get("rol") != "usuario":
        return jsonify(error="Falta la pregunta"), 400
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify(error="Falta la clave de Anthropic: ponla en ANTHROPIC_API_KEY dentro del "
                             "archivo .env y reinicia la demo."), 503
    try:
        return jsonify(asistente.responder(historial[-20:]))
    except anthropic.AuthenticationError:
        mensaje = "La clave de Anthropic no es válida. Revisa ANTHROPIC_API_KEY en el archivo .env."
    except anthropic.RateLimitError:
        mensaje = "Demasiadas consultas seguidas. Espera unos segundos y vuelve a probar."
    except anthropic.APIConnectionError:
        mensaje = "No hay conexión con la API de Anthropic. Revisa la conexión a internet."
    except anthropic.APIStatusError as e:
        mensaje = f"La API de Anthropic ha devuelto un error ({e.status_code})."
    except anthropic.AnthropicError as e:
        # p. ej. falta la clave en el .env
        mensaje = f"No se puede conectar con Claude: {e}"
    return jsonify(error=mensaje), 502


# ---------------------------------------------------------------- Facturas

def _con_estado(factura: dict, estado: dict) -> dict:
    clave = str(factura["id"])
    return {**factura, "emitida_demo": estado["emitidas"].get(clave),
            "enviada_demo": estado["enviadas"].get(clave)}


@app.get("/api/facturas")
def listar_facturas():
    estado = facturacion.leer_estado()
    todas = [_con_estado(f, estado) for f in facturacion.facturas_por_emitir()]
    return jsonify(pendientes=[f for f in todas if not f["emitida_demo"]],
                   emitidas=[f for f in todas if f["emitida_demo"]],
                   registro=estado["registro"][-50:])


def _factura_o_404(factura_id: int) -> dict:
    factura = facturacion.detalle_factura(factura_id)
    if not factura:
        abort(404)
    return _con_estado(factura, facturacion.leer_estado())


@app.get("/api/facturas/<int:factura_id>")
def ver_factura(factura_id):
    return jsonify(_factura_o_404(factura_id))


@app.post("/api/facturas/<int:factura_id>/solicitar")
def solicitar_aprobacion(factura_id):
    factura = _factura_o_404(factura_id)
    mensaje = f"Factura a {factura['cliente']['nombre']}, {factura['importes']['total']}. ¿La emito?"
    facturacion.registrar(f"WhatsApp a Francisco (simulado): «{mensaje}»", "whatsapp")
    return jsonify(mensaje=mensaje)


@app.post("/api/facturas/<int:factura_id>/aprobar")
def aprobar(factura_id):
    factura = _factura_o_404(factura_id)
    nombre = factura["cliente"]["nombre"]
    if not (request.get_json(silent=True) or {}).get("aprobada"):
        facturacion.registrar(f"Francisco responde «No»: la factura a {nombre} no se emite.", "no")
        return jsonify(emitida=False)
    archivo = f"factura_F-{factura_id:04d}.pdf"
    facturacion.generar_pdf(factura, facturacion.carpeta_pdfs() / archivo)
    facturacion.marcar_emitida(factura_id, archivo)
    facturacion.registrar(f"Francisco responde «Sí». Factura F-{factura_id:04d} a {nombre} emitida "
                          f"por {factura['importes']['total']} (PDF generado).", "ok")
    return jsonify(emitida=True, pdf=f"/api/facturas/{factura_id}/pdf")


@app.get("/api/facturas/<int:factura_id>/pdf")
def descargar_pdf(factura_id):
    emitida = facturacion.leer_estado()["emitidas"].get(str(factura_id))
    if not emitida:
        abort(404)
    ruta = facturacion.carpeta_pdfs() / emitida["pdf"]
    if not ruta.exists():
        abort(404)
    return send_file(ruta, mimetype="application/pdf", download_name=emitida["pdf"])


@app.post("/api/facturas/<int:factura_id>/enviar")
def enviar(factura_id):
    factura = _factura_o_404(factura_id)
    if not factura["emitida_demo"]:
        return jsonify(error="Primero hay que emitir la factura"), 409
    email = factura["cliente"]["email"]
    facturacion.marcar_enviada(factura_id, email)
    facturacion.registrar(f"Envío simulado de F-{factura_id:04d} a {email} con el PDF adjunto "
                          f"(no se ha mandado ningún correo real).", "envio")
    return jsonify(enviada=True, email=email)


@app.post("/api/demo/reiniciar")
def reiniciar():
    facturacion.reiniciar_estado()
    return jsonify(ok=True)


preparar_base()

if __name__ == "__main__":
    puerto = int(os.environ.get("PUERTO", 5050))
    print(f"\n  Demo Montelier lista en  http://localhost:{puerto}\n")
    app.run(host="127.0.0.1", port=puerto, debug=False, threaded=True)
