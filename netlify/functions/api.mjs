// API de la demo en Netlify (equivale a app.py). La base del cliente es de solo lectura;
// el estado de la demo (emitidas, enviadas, registro) se guarda en Netlify Blobs.
import { createHash, timingSafeEqual } from "node:crypto";
import Anthropic from "@anthropic-ai/sdk";
import { getStore } from "@netlify/blobs";
import { hoyEspana, rutaBase } from "../lib/base.mjs";
import { MAX_PASOS, MODELO, mensajesDesdeHistorial, paso } from "../lib/asistente.mjs";
import { detalleFactura, facturasPorEmitir, generarPdf } from "../lib/factura.mjs";

const CLIENTE_EJEMPLO = "Hotel Costa Daurada";
const PREGUNTAS = [
  "¿Cuántas facturas llevamos este mes y por cuánto?",
  "¿Qué facturas están pendientes de cobro?",
  "¿Me queda alguna petición por presupuestar esta semana?",
  `¿Qué le hemos presupuestado a ${CLIENTE_EJEMPLO}?`,
];
const MAX_ESTADO_CHAT = 300_000; // bytes

const json = (datos, estado = 200, cabeceras = {}) =>
  new Response(JSON.stringify(datos), { status: estado, headers: { "content-type": "application/json", ...cabeceras } });
const ref = (n) => String(n).padStart(4, "0");
const hora = () => new Intl.DateTimeFormat("es-ES", { timeZone: "Europe/Madrid", hour: "2-digit", minute: "2-digit",
                                                     second: "2-digit", hour12: false }).format(new Date());

// ---------------------------------------------------------------- contraseña de la demo (DEMO_CLAVE)
const huella = (t) => createHash("sha256").update(String(t)).digest();
function autorizado(req) {
  const clave = process.env.DEMO_CLAVE;
  if (!clave) return true;
  const cookie = (req.headers.get("cookie") || "").split(/;\s*/).find((c) => c.startsWith("demo_clave="));
  if (!cookie) return false;
  return timingSafeEqual(huella(decodeURIComponent(cookie.slice(11))), huella(clave));
}

// ---------------------------------------------------------------- estado de la demo
// CLAVE_ANTHROPIC: clave propia de Anthropic, va directa a api.anthropic.com. Sin ella se usa lo que
// ponga Netlify en ANTHROPIC_API_KEY/ANTHROPIC_BASE_URL (su AI Gateway, con límites de uso).
const clavePropia = () => process.env.CLAVE_ANTHROPIC;
const hayClave = () => Boolean(clavePropia() || process.env.ANTHROPIC_API_KEY);
const nuevoCliente = () => (clavePropia()
  ? new Anthropic({ apiKey: clavePropia(), authToken: null, baseURL: "https://api.anthropic.com" })
  : new Anthropic());

export function crearApi({ almacen, hoy = hoyEspana, clienteClaude = nuevoCliente } = {}) {
  const store = () => almacen ?? getStore({ name: "montelier-demo", consistency: "strong" });

  async function leerEstado() {
    const estado = await store().get("estado", { type: "json" });
    // Base nueva cada día: el estado de otro día ya no aplica
    if (!estado || estado.fecha_base !== hoy()) return { fecha_base: hoy(), emitidas: {}, enviadas: {}, registro: [] };
    return estado;
  }
  const guardar = (estado) => store().setJSON("estado", estado);
  async function registrar(estado, texto, tipo = "info") {
    estado.registro.push({ hora: hora(), texto, tipo });
    estado.registro = estado.registro.slice(-200);
    await guardar(estado);
  }
  const conEstado = (f, e) => ({ ...f, emitida_demo: e.emitidas[f.id] ?? null, enviada_demo: e.enviadas[f.id] ?? null });

  // ---------------------------------------------------------------- rutas
  return async function manejar(req) {
    const url = new URL(req.url);
    const ruta = url.pathname.replace(/^\/api/, "").replace(/\/+$/, "");
    const metodo = req.method;
    const cuerpo = async () => { try { return await req.json(); } catch { return {}; } };

    if (ruta === "/config" && metodo === "GET") {
      return json({ preguntas: PREGUNTAS, hay_clave: hayClave(), modelo: MODELO,
                    requiere_clave: Boolean(process.env.DEMO_CLAVE), autorizado: autorizado(req) });
    }
    if (ruta === "/entrar" && metodo === "POST") {
      const { clave } = await cuerpo();
      const esperada = process.env.DEMO_CLAVE;
      if (!esperada || timingSafeEqual(huella(clave ?? ""), huella(esperada))) {
        return json({ ok: true }, 200, esperada ? { "set-cookie":
          `demo_clave=${encodeURIComponent(esperada)}; Path=/; Max-Age=2592000; HttpOnly; Secure; SameSite=Lax` } : {});
      }
      return json({ error: "Contraseña incorrecta" }, 401);
    }
    if (!autorizado(req)) return json({ error: "Hace falta la contraseña de la demo", requiere_clave: true }, 401);

    const baseDatos = rutaBase(hoy());

    // ---------------- Asistente
    if (ruta === "/chat" && metodo === "POST") {
      const { historial = [], estado = null } = await cuerpo();
      if (!hayClave()) {
        return json({ error: "Falta la clave de Anthropic: hay que añadir CLAVE_ANTHROPIC en las variables de entorno de Netlify." }, 503);
      }
      let mensajes, pasos = 0;
      if (estado) {
        if (JSON.stringify(estado).length > MAX_ESTADO_CHAT || !Array.isArray(estado.mensajes)) {
          return json({ error: "Conversación demasiado larga. Recarga la página." }, 400);
        }
        mensajes = estado.mensajes;
        pasos = Number(estado.pasos) || 0;
      } else {
        const ultimo = historial.at(-1);
        if (!ultimo || ultimo.rol !== "usuario") return json({ error: "Falta la pregunta" }, 400);
        mensajes = mensajesDesdeHistorial(historial.slice(-20));
      }
      if (pasos >= MAX_PASOS) return json({ texto: "Me he liado con esta consulta. ¿Me la puedes preguntar de otra forma?", consultas: [] });
      try {
        const r = await paso(mensajes, { cliente: clienteClaude(), hoy: hoy(), ruta: baseDatos });
        if (r.fin) return json({ texto: r.texto, consultas: [] });
        return json({ continuar: true, consultas: r.consultas, estado: { mensajes: r.mensajes, pasos: pasos + 1 } });
      } catch (e) {
        console.error("Error de la API de Anthropic:", e?.status, e?.message, e?.cause?.message);
        if (e instanceof Anthropic.AuthenticationError) return json({ error: "La clave de Anthropic no es válida." }, 502);
        if (e instanceof Anthropic.RateLimitError) {
          return json({ error: "Demasiadas consultas seguidas. Espera unos segundos y vuelve a probar.", detalle: String(e.message).slice(0, 300) }, 502);
        }
        if (e instanceof Anthropic.APIConnectionError) {
          return json({ error: "No hay conexión con la API de Anthropic.", detalle: String(e.cause?.message || e.message).slice(0, 300) }, 502);
        }
        if (e instanceof Anthropic.APIError) {
          return json({ error: `La API de Anthropic ha devuelto un error (${e.status}).`, detalle: String(e.message).slice(0, 300) }, 502);
        }
        throw e;
      }
    }

    // ---------------- Facturas
    if (ruta === "/facturas" && metodo === "GET") {
      const estado = await leerEstado();
      const todas = facturasPorEmitir(baseDatos).map((f) => conEstado(f, estado));
      return json({ pendientes: todas.filter((f) => !f.emitida_demo), emitidas: todas.filter((f) => f.emitida_demo),
                    registro: estado.registro.slice(-50) });
    }
    if (ruta === "/demo/reiniciar" && metodo === "POST") {
      await guardar({ fecha_base: hoy(), emitidas: {}, enviadas: {}, registro: [] });
      return json({ ok: true });
    }

    const m = ruta.match(/^\/facturas\/(\d+)(?:\/(solicitar|aprobar|pdf|enviar))?$/);
    if (!m) return json({ error: "No encontrado" }, 404);
    const id = Number(m[1]);
    const accion = m[2];
    const base = detalleFactura(id, baseDatos);
    if (!base) return json({ error: "No existe esa factura" }, 404);
    const estado = await leerEstado();
    const factura = conEstado(base, estado);
    const nombre = factura.cliente.nombre;

    if (!accion && metodo === "GET") return json(factura);
    if (accion === "solicitar" && metodo === "POST") {
      const mensaje = `Factura a ${nombre}, ${factura.importes.total}. ¿La emito?`;
      await registrar(estado, `WhatsApp a Francisco (simulado): «${mensaje}»`, "whatsapp");
      return json({ mensaje });
    }
    if (accion === "aprobar" && metodo === "POST") {
      if (!(await cuerpo()).aprobada) {
        await registrar(estado, `Francisco responde «No»: la factura a ${nombre} no se emite.`, "no");
        return json({ emitida: false });
      }
      estado.emitidas[id] = { fecha: hoy(), pdf: `factura_F-${ref(id)}.pdf` };
      await registrar(estado, `Francisco responde «Sí». Factura F-${ref(id)} a ${nombre} emitida por ` +
                              `${factura.importes.total} (PDF generado).`, "ok");
      return json({ emitida: true, pdf: `/api/facturas/${id}/pdf` });
    }
    if (accion === "pdf" && metodo === "GET") {
      const emitida = estado.emitidas[id];
      if (!emitida) return json({ error: "La factura no está emitida" }, 404);
      return new Response(await generarPdf(factura, emitida.fecha), { headers: {
        "content-type": "application/pdf", "content-disposition": `inline; filename="${emitida.pdf}"` } });
    }
    if (accion === "enviar" && metodo === "POST") {
      if (!factura.emitida_demo) return json({ error: "Primero hay que emitir la factura" }, 409);
      const email = factura.cliente.email;
      estado.enviadas[id] = { hora: hora().slice(0, 5), email };
      await registrar(estado, `Envío simulado de F-${ref(id)} a ${email} con el PDF adjunto ` +
                              "(no se ha mandado ningún correo real).", "envio");
      return json({ enviada: true, email });
    }
    return json({ error: "No encontrado" }, 404);
  };
}

const manejar = crearApi();
export default (req) => manejar(req);
export const config = { path: "/api/*" };
