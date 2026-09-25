"""Facturación desde el chat: herramientas que Claude puede usar para preparar la emisión
de una factura y para enviarla (simulado) al cliente.

Claude NO puede emitir: solo pide la aprobación. La factura se emite cuando Francisco pulsa
«Sí» en la tarjeta del chat (la misma ruta /aprobar que usa la pestaña Facturas).
Nada de esto escribe en la base del cliente: el estado va en el archivo propio de la demo.
"""
from . import facturacion
from .herramientas import ErrorHerramienta

DEFINICIONES = [
    {
        "name": "facturas_por_emitir",
        "description": "Facturas de presupuestos aceptados que aún no se han emitido, con cliente, "
                       "servicio y base, IVA 21% y total ya calculados. Incluye también las emitidas "
                       "hoy desde la demo y si ya se han enviado al cliente.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "pedir_aprobacion_emision",
        "description": "Prepara la emisión de UNA factura aceptada sin emitir: muestra a Francisco "
                       "en el chat la factura (base, IVA y total) con los botones Sí / No. Tú no "
                       "puedes emitirla: se emite solo si Francisco pulsa Sí. Después de llamarla, "
                       "contesta con una frase corta; la tarjeta ya enseña los importes.",
        "input_schema": {
            "type": "object",
            "properties": {"factura_id": {"type": "integer"}},
            "required": ["factura_id"],
        },
    },
    {
        "name": "enviar_factura_cliente",
        "description": "Envía al cliente, por correo, una factura YA EMITIDA con su PDF adjunto "
                       "(en la demo el envío es simulado). Úsala solo si Francisco lo pide.",
        "input_schema": {
            "type": "object",
            "properties": {"factura_id": {"type": "integer"}},
            "required": ["factura_id"],
        },
    },
]

NOMBRES = {d["name"] for d in DEFINICIONES}


def _id(argumentos) -> int:
    try:
        return int(argumentos["factura_id"])
    except (KeyError, TypeError, ValueError):
        raise ErrorHerramienta("Falta 'factura_id' (número de la factura)")


class AccionesChat:
    def __init__(self, ruta_bd=None):
        self.ruta_bd = ruta_bd

    def ejecutar(self, nombre: str, argumentos: dict):
        """Devuelve (datos para el modelo, acción para la interfaz o None)."""
        if nombre == "facturas_por_emitir":
            return self._por_emitir(), None
        if nombre == "pedir_aprobacion_emision":
            return self._pedir_aprobacion(_id(argumentos))
        if nombre == "enviar_factura_cliente":
            return self._enviar(_id(argumentos))
        raise ErrorHerramienta(f"Herramienta desconocida: {nombre}")

    def _factura(self, factura_id: int) -> dict:
        factura = facturacion.detalle_factura(factura_id, self.ruta_bd)
        if not factura or factura_id not in {f["id"] for f in facturacion.facturas_por_emitir(self.ruta_bd)}:
            raise ErrorHerramienta(f"La factura {factura_id} no está entre las aceptadas pendientes de emitir")
        return factura

    def _por_emitir(self) -> dict:
        estado = facturacion.leer_estado()
        pendientes, emitidas = [], []
        for f in facturacion.facturas_por_emitir(self.ruta_bd):
            datos = {"factura_id": f["id"], "cliente": f["cliente"]["nombre"], "servicio": f["servicio"],
                     "descripcion": f["descripcion"], "fecha_servicio": f["fecha"], **f["importes"]}
            if str(f["id"]) in estado["emitidas"]:
                datos["enviada_al_cliente"] = "sí" if str(f["id"]) in estado["enviadas"] else "no"
                emitidas.append(datos)
            else:
                pendientes.append(datos)
        return {"pendientes_de_emitir": pendientes, "emitidas_hoy_en_la_demo": emitidas}

    def _pedir_aprobacion(self, factura_id: int):
        factura = self._factura(factura_id)
        if str(factura_id) in facturacion.leer_estado()["emitidas"]:
            raise ErrorHerramienta(f"La factura {factura_id} ya está emitida")
        mensaje = f"Factura a {factura['cliente']['nombre']}, {factura['importes']['total']}. ¿La emito?"
        facturacion.registrar(f"WhatsApp a Francisco: «{mensaje}»", "whatsapp")
        datos = {"estado": "esperando la respuesta de Francisco (botones Sí / No en el chat)",
                 "factura_id": factura_id, "cliente": factura["cliente"]["nombre"], **factura["importes"]}
        return datos, {"tipo": "aprobacion", "mensaje": mensaje, "factura": factura}

    def _enviar(self, factura_id: int):
        factura = self._factura(factura_id)
        if str(factura_id) not in facturacion.leer_estado()["emitidas"]:
            raise ErrorHerramienta(f"La factura {factura_id} todavía no está emitida: primero hay que "
                                   "pedir la aprobación y que Francisco pulse Sí")
        email = factura["cliente"]["email"]
        facturacion.marcar_enviada(factura_id, email)
        facturacion.registrar(f"Envío simulado de F-{factura_id:04d} a {email} con el PDF adjunto "
                              "(no se ha mandado ningún correo real).", "envio")
        return ({"enviada": True, "email": email, "aviso": "Envío simulado en la demo"},
                {"tipo": "enviada", "factura_id": factura_id, "email": email})
