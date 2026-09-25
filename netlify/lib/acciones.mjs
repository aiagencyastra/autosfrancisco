// Facturación desde el chat (como montelier/acciones_chat.py). Claude NO puede emitir: solo pide
// la aprobación; la factura se emite cuando Francisco pulsa «Sí» en la tarjeta del chat.
// El estado va en Netlify Blobs, nunca en la base del cliente.
import { ErrorHerramienta } from "./herramientas.mjs";
import { detalleFactura, facturasPorEmitir } from "./factura.mjs";

export const DEFINICIONES = [
  { name: "facturas_por_emitir",
    description: "Facturas de presupuestos aceptados que aún no se han emitido, con cliente, servicio y base, " +
      "IVA 21% y total ya calculados. Incluye también las emitidas hoy desde la demo y si ya se han enviado al cliente.",
    input_schema: { type: "object", properties: {} } },
  { name: "pedir_aprobacion_emision",
    description: "Prepara la emisión de UNA factura aceptada sin emitir: muestra a Francisco en el chat la factura " +
      "(base, IVA y total) con los botones Sí / No. Tú no puedes emitirla: se emite solo si Francisco pulsa Sí. " +
      "Después de llamarla, contesta con una frase corta; la tarjeta ya enseña los importes.",
    input_schema: { type: "object", properties: { factura_id: { type: "integer" } }, required: ["factura_id"] } },
  { name: "enviar_factura_cliente",
    description: "Envía al cliente, por correo, una factura YA EMITIDA con su PDF adjunto (en la demo el envío es " +
      "simulado). Úsala solo si Francisco lo pide.",
    input_schema: { type: "object", properties: { factura_id: { type: "integer" } }, required: ["factura_id"] } },
];
export const NOMBRES = new Set(DEFINICIONES.map((d) => d.name));

const ref = (n) => String(n).padStart(4, "0");

// estadoDemo: { leer(), registrar(estado, texto, tipo), hora() } — lo aporta la API
export function crearAcciones({ ruta, estadoDemo }) {
  const idDe = (args) => {
    const id = Number(args?.factura_id);
    if (!Number.isInteger(id)) throw new ErrorHerramienta("Falta 'factura_id' (número de la factura)");
    return id;
  };
  const factura = (id) => {
    const f = detalleFactura(id, ruta);
    if (!f || !facturasPorEmitir(ruta).some((x) => x.id === id)) {
      throw new ErrorHerramienta(`La factura ${id} no está entre las aceptadas pendientes de emitir`);
    }
    return f;
  };

  async function ejecutar(nombre, args) {
    const estado = await estadoDemo.leer();
    if (nombre === "facturas_por_emitir") {
      const pendientes = [], emitidas = [];
      for (const f of facturasPorEmitir(ruta)) {
        const datos = { factura_id: f.id, cliente: f.cliente.nombre, servicio: f.servicio, descripcion: f.descripcion,
                        fecha_servicio: f.fecha, ...f.importes };
        if (estado.emitidas[f.id]) emitidas.push({ ...datos, enviada_al_cliente: estado.enviadas[f.id] ? "sí" : "no" });
        else pendientes.push(datos);
      }
      return [{ pendientes_de_emitir: pendientes, emitidas_hoy_en_la_demo: emitidas }, null];
    }
    if (nombre === "pedir_aprobacion_emision") {
      const id = idDe(args);
      const f = factura(id);
      if (estado.emitidas[id]) throw new ErrorHerramienta(`La factura ${id} ya está emitida`);
      const mensaje = `Factura a ${f.cliente.nombre}, ${f.importes.total}. ¿La emito?`;
      await estadoDemo.registrar(estado, `WhatsApp a Francisco: «${mensaje}»`, "whatsapp");
      return [{ estado: "esperando la respuesta de Francisco (botones Sí / No en el chat)", factura_id: id,
                cliente: f.cliente.nombre, ...f.importes }, { tipo: "aprobacion", mensaje, factura: f }];
    }
    if (nombre === "enviar_factura_cliente") {
      const id = idDe(args);
      const f = factura(id);
      if (!estado.emitidas[id]) {
        throw new ErrorHerramienta(`La factura ${id} todavía no está emitida: primero hay que pedir la aprobación ` +
                                   "y que Francisco pulse Sí");
      }
      const email = f.cliente.email;
      estado.enviadas[id] = { hora: estadoDemo.hora().slice(0, 5), email };
      await estadoDemo.registrar(estado, `Envío simulado de F-${ref(id)} a ${email} con el PDF adjunto ` +
                                         "(no se ha mandado ningún correo real).", "envio");
      return [{ enviada: true, email, aviso: "Envío simulado en la demo" }, { tipo: "enviada", factura_id: id, email }];
    }
    throw new ErrorHerramienta(`Herramienta desconocida: ${nombre}`);
  }
  return { definiciones: DEFINICIONES, nombres: NOMBRES, ejecutar };
}
