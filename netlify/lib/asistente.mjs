// Asistente de consultas: Claude + herramientas sobre la base en solo lectura (como montelier/asistente.py).
import Anthropic from "@anthropic-ai/sdk";
import { conectar, diaSemana, hoyEspana, sumarDias } from "./base.mjs";
import { ErrorHerramienta, DEFINICIONES, ejecutar } from "./herramientas.mjs";

export const MODELO = process.env.MODELO || "claude-opus-5";
const MAX_VUELTAS = 8;
const DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"];
const MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre",
               "octubre", "noviembre", "diciembre"];

const INSTRUCCIONES = `Eres el asistente interno de Montelier, empresa de transporte y montaje de \
mobiliario (Barcelona y Tarragona). Hablas con Francisco, el responsable, por un chat tipo WhatsApp.

Reglas:
- Solo das datos que salgan de las herramientas. Nunca inventes ni estimes cifras, clientes o fechas.
- Si una herramienta no devuelve datos, dilo claramente ("No hay facturas pendientes de cobro").
- No hagas cuentas tú: usa los totales que devuelven las herramientas, que ya llevan el IVA calculado.
- Importes en formato español, tal cual vienen de las herramientas (1.210,00 €). Di si son con o sin IVA.
- Respuestas cortas, en castellano, tono cercano y directo, como un mensaje de WhatsApp. \
Para resaltar usa *asteriscos*; para listas, líneas que empiecen por "• ". Nada de tablas ni títulos.
- Usa consulta_sql solo si ninguna otra herramienta sirve. La base es de solo lectura: \
si te piden cambiar datos, explica que desde aquí solo se puede consultar.
- Si la pregunta es ambigua (por ejemplo, varios clientes con un nombre parecido), pregunta.`;

export function contextoFechas(hoy) {
  const [anio, mes, dia] = hoy.split("-").map(Number);
  const lunes = sumarDias(hoy, -diaSemana(hoy));
  const inicioMes = `${hoy.slice(0, 7)}-01`;
  const finMes = new Date(Date.UTC(anio, mes, 0)).toISOString().slice(0, 10);
  return `Hoy es ${DIAS[diaSemana(hoy)]} ${dia} de ${MESES[mes - 1]} de ${anio} (${hoy}). ` +
    `Esta semana va del ${lunes} al ${sumarDias(lunes, 6)}. Este mes va del ${inicioMes} al ${finMes}.`;
}

const texto = (contenido) => contenido.filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();

export const mensajesDesdeHistorial = (historial) => historial.filter((m) => m && m.texto)
  .map((m) => ({ role: m.rol === "usuario" ? "user" : "assistant", content: String(m.texto) }));

// Un paso de la conversación: una llamada a Claude y, si pide herramientas, su ejecución.
// En Netlify cada función tiene pocos segundos, así que el navegador encadena los pasos.
// Devuelve {fin: true, texto} o {fin: false, mensajes, consultas}.
export async function paso(mensajes, { cliente = new Anthropic(), hoy = hoyEspana(), ruta } = {}) {
  const respuesta = await cliente.beta.messages.create({
    model: MODELO,
    max_tokens: 16000,
    system: `${INSTRUCCIONES}\n\n${contextoFechas(hoy)}`,
    tools: DEFINICIONES,
    messages: mensajes,
    thinking: { type: "adaptive" },
    output_config: { effort: "low" },
    // Si el modelo declina por sus filtros de seguridad, la API reintenta con otro modelo
    betas: ["server-side-fallback-2026-07-01"],
    fallbacks: "default",
  });
  if (respuesta.stop_reason === "refusal") {
    return { fin: true, texto: "No puedo responder a eso. Prueba a preguntarlo de otra forma." };
  }
  if (respuesta.stop_reason !== "tool_use") {
    return { fin: true, texto: texto(respuesta.content) || "No tengo respuesta para eso." };
  }
  const consultas = [];
  const resultados = [];
  const db = conectar(ruta);
  try {
    for (const bloque of respuesta.content) {
      if (bloque.type !== "tool_use") continue;
      consultas.push(bloque.name);
      try {
        const datos = ejecutar(db, bloque.name, bloque.input);
        resultados.push({ type: "tool_result", tool_use_id: bloque.id, content: JSON.stringify(datos) });
      } catch (e) {
        if (!(e instanceof ErrorHerramienta)) throw e;
        resultados.push({ type: "tool_result", tool_use_id: bloque.id, content: `Error: ${e.message}`, is_error: true });
      }
    }
  } finally {
    db.close();
  }
  return { fin: false, consultas,
           mensajes: [...mensajes, { role: "assistant", content: respuesta.content }, { role: "user", content: resultados }] };
}

export const MAX_PASOS = MAX_VUELTAS;

// Conversación completa en una sola llamada (para pruebas y uso local)
export async function responder(historial, opciones = {}) {
  let mensajes = mensajesDesdeHistorial(historial);
  const consultas = [];
  for (let vuelta = 0; vuelta < MAX_VUELTAS; vuelta++) {
    const r = await paso(mensajes, opciones);
    if (r.fin) return { texto: r.texto, consultas };
    consultas.push(...r.consultas);
    mensajes = r.mensajes;
  }
  return { texto: "Me he liado con esta consulta. ¿Me la puedes preguntar de otra forma?", consultas };
}
