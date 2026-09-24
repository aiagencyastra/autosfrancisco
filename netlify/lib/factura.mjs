// Pestaña Facturas: facturas aceptadas sin emitir, detalle y PDF (como montelier/facturacion.py).
import { PDFDocument, StandardFonts, rgb } from "pdf-lib";
import { conectar } from "./base.mjs";
import { desglose, desgloseFormateado } from "./dinero.mjs";

const SQL_DETALLE = `
  SELECT f.id, f.fecha, f.importe_transporte, f.importe_montaje, f.estado, f.emitida,
         p.id AS presupuesto_id, p.tipo_servicio, p.dias_montaje, p.fecha AS fecha_presupuesto,
         p.direccion AS direccion_servicio, p.comentario,
         c.id AS cliente_id, c.nombre, c.email, c.telefono, c.direccion AS direccion_cliente
  FROM facturas f JOIN presupuestos p ON p.id = f.presupuesto_id JOIN clientes c ON c.id = p.cliente_id`;

function aDict(f) {
  return {
    id: f.id, fecha: f.fecha, presupuesto_id: f.presupuesto_id,
    servicio: f.tipo_servicio === "transporte_montaje" ? "Transporte y montaje" : "Transporte",
    dias_montaje: f.dias_montaje, descripcion: f.comentario, direccion_servicio: f.direccion_servicio,
    cliente: { id: f.cliente_id, nombre: f.nombre, email: f.email, telefono: f.telefono, direccion: f.direccion_cliente },
    importes: desgloseFormateado(desglose(f.importe_transporte, f.importe_montaje)),
    tiene_montaje: f.importe_montaje != null,
  };
}

// Facturas de presupuestos aceptados que aún no están emitidas en la base del cliente
export function facturasPorEmitir(ruta) {
  const db = conectar(ruta);
  try {
    return db.prepare(`${SQL_DETALLE} WHERE f.emitida = 0 AND p.estado = 'aceptado' ORDER BY f.fecha, f.id`).all().map(aDict);
  } finally { db.close(); }
}

export function detalleFactura(id, ruta) {
  const db = conectar(ruta);
  try {
    const fila = db.prepare(`${SQL_DETALLE} WHERE f.id = ?`).get(id);
    return fila ? aDict(fila) : null;
  } finally { db.close(); }
}

// ---------------------------------------------------------------- PDF
const MM = 72 / 25.4;
const AZUL = rgb(0x12 / 255, 0x35 / 255, 0x5b / 255);
const GRIS = rgb(0x5b / 255, 0x65 / 255, 0x73 / 255);
const LINEA = rgb(0xd5 / 255, 0xda / 255, 0xe1 / 255);
const FONDO = rgb(0xf3 / 255, 0xf5 / 255, 0xf8 / 255);
const NEGRO = rgb(0, 0, 0);
const BLANCO = rgb(1, 1, 1);
const fechaEs = (iso) => iso.split("-").reverse().join("/");
const ref = (n) => String(n).padStart(4, "0");

export async function generarPdf(factura, fechaEmision) {
  const pdf = await PDFDocument.create();
  pdf.setTitle(`Factura F-${ref(factura.id)} - ${factura.cliente.nombre}`);
  pdf.setAuthor("Montelier (demo)");
  const normal = await pdf.embedFont(StandardFonts.Helvetica);
  const negrita = await pdf.embedFont(StandardFonts.HelveticaBold);
  const cursiva = await pdf.embedFont(StandardFonts.HelveticaOblique);
  const pagina = pdf.addPage([595.28, 841.89]);
  const [ANCHO, ALTO] = [595.28, 841.89];
  const IZQ = 20 * MM, DER = ANCHO - 20 * MM;

  // Las fuentes estándar solo tienen WinAnsi: lo que no entre se sustituye por "?"
  const seguro = (fuente, t) => [...String(t ?? "")].map((c) => {
    try { fuente.encodeText(c); return c; } catch { return "?"; }
  }).join("");
  const escribir = (t, x, y, { fuente = normal, tam = 9, color = NEGRO, alinear = "izq" } = {}) => {
    t = seguro(fuente, t);
    const w = fuente.widthOfTextAtSize(t, tam);
    const px = alinear === "der" ? x - w : alinear === "centro" ? x - w / 2 : x;
    pagina.drawText(t, { x: px, y, size: tam, font: fuente, color });
  };
  const partir = (t, fuente, tam, ancho) => {
    const lineas = [];
    let actual = "";
    for (const palabra of seguro(fuente, t).split(" ")) {
      const prueba = actual ? `${actual} ${palabra}` : palabra;
      if (fuente.widthOfTextAtSize(prueba, tam) > ancho && actual) { lineas.push(actual); actual = palabra; }
      else actual = prueba;
    }
    if (actual) lineas.push(actual);
    return lineas;
  };

  // Cabecera: logo provisional y datos de la empresa
  let y = ALTO - 18 * MM;
  const logoW = 62 * MM, logoH = 16 * MM;
  pagina.drawRectangle({ x: IZQ, y: y - logoH, width: logoW, height: logoH, color: AZUL });
  escribir("MONTELIER", IZQ + logoW / 2, y - logoH / 2 - 3, { fuente: negrita, tam: 18, color: BLANCO, alinear: "centro" });
  escribir("TRANSPORTE Y MONTAJE · LOGO PROVISIONAL", IZQ + logoW / 2, y - logoH + 2.2 * MM,
           { tam: 6.5, color: BLANCO, alinear: "centro" });
  let yEmp = y - logoH - 6 * MM;
  escribir("Montelier (razón social pendiente)", IZQ, yEmp, { fuente: negrita, tam: 8.5, color: GRIS });
  for (const l of ["NIF: pendiente", "Dirección: pendiente", "Email: pendiente · Tel.: pendiente"]) {
    yEmp -= 11.5;
    escribir(l, IZQ, yEmp, { tam: 8.5, color: GRIS });
  }

  escribir("FACTURA", DER, y - 18, { fuente: negrita, tam: 20, color: AZUL, alinear: "der" });
  let yMeta = y - 18 - 6 * MM;
  const tNum = "lo asignará el software de facturación";
  escribir(tNum, DER, yMeta, { fuente: cursiva, alinear: "der" });
  escribir("Nº de factura: ", DER - cursiva.widthOfTextAtSize(seguro(cursiva, tNum), 9), yMeta, { alinear: "der" });
  for (const l of [`Referencia interna: F-${ref(factura.id)} · Presupuesto P-${ref(factura.presupuesto_id)}`,
                   `Fecha de emisión: ${fechaEs(fechaEmision)}`, `Fecha del servicio: ${fechaEs(factura.fecha)}`]) {
    yMeta -= 12;
    escribir(l, DER, yMeta, { alinear: "der" });
  }

  // Bloque cliente / servicio
  y = Math.min(yEmp, yMeta) - 10 * MM;
  const colW = 85 * MM, pad = 8;
  const cli = factura.cliente;
  const columnas = [
    ["FACTURAR A", cli.nombre, [cli.direccion, `${cli.email} · ${cli.telefono}`]],
    ["SERVICIO", factura.servicio, [factura.descripcion, `Lugar: ${factura.direccion_servicio}`]],
  ].map(([etq, titulo, resto]) => [etq, partir(titulo, negrita, 9, colW - 2 * pad),
                                   resto.flatMap((t) => partir(t, normal, 9, colW - 2 * pad))]);
  const altoBloque = pad * 2 + 10 + 12 * Math.max(...columnas.map(([, t, r]) => t.length + r.length));
  pagina.drawRectangle({ x: IZQ, y: y - altoBloque, width: colW * 2, height: altoBloque, color: FONDO,
                         borderColor: LINEA, borderWidth: 0.5 });
  pagina.drawLine({ start: { x: IZQ + colW, y }, end: { x: IZQ + colW, y: y - altoBloque }, thickness: 0.5, color: LINEA });
  columnas.forEach(([etq, titulo, resto], i) => {
    const x = IZQ + i * colW + pad;
    let yy = y - pad - 7;
    escribir(etq, x, yy, { fuente: negrita, tam: 7.5, color: GRIS });
    yy -= 3;
    for (const l of titulo) { yy -= 12; escribir(l, x, yy, { fuente: negrita }); }
    for (const l of resto) { yy -= 12; escribir(l, x, yy); }
  });

  // Tabla de importes
  y = y - altoBloque - 10 * MM;
  const imp = factura.importes;
  const conceptos = [["Transporte", imp.transporte]];
  if (factura.tiene_montaje) {
    const d = factura.dias_montaje;
    conceptos.push([`Montaje${d ? ` (${d} día${d === 1 ? "" : "s"})` : ""}`, imp.montaje]);
  }
  const FILA = 22;
  const celda = (izq, der, yy, opciones = {}) => {
    escribir(izq, IZQ + 6, yy + 7, opciones);
    escribir(der, DER - 6, yy + 7, { ...opciones, alinear: "der" });
  };
  y -= FILA;
  celda("Concepto", "Importe", y, { fuente: negrita, tam: 8.5, color: GRIS });
  pagina.drawLine({ start: { x: IZQ, y }, end: { x: DER, y }, thickness: 0.8, color: AZUL });
  for (const [i, [c, v]] of conceptos.entries()) {
    y -= FILA;
    celda(c, v, y, { tam: 9.5 });
    pagina.drawLine({ start: { x: IZQ, y }, end: { x: DER, y }, thickness: i === conceptos.length - 1 ? 0.8 : 0.4, color: LINEA });
  }
  for (const [c, v] of [["Base imponible", imp.base], ["IVA 21%", imp.iva]]) {
    y -= FILA;
    celda(c, v, y, { tam: 9.5, color: GRIS });
  }
  y -= FILA + 4;
  pagina.drawRectangle({ x: IZQ, y, width: DER - IZQ, height: FILA + 4, color: AZUL });
  celda("TOTAL", imp.total, y + 1, { fuente: negrita, tam: 12, color: BLANCO });

  // Recuadro reservado para el QR Verifactu (no se simula ningún QR ni número)
  y -= 12 * MM;
  const vW = 62 * MM, vH = 30 * MM;
  pagina.drawRectangle({ x: IZQ, y: y - vH, width: vW, height: vH, borderColor: GRIS, borderWidth: 1,
                         borderDashArray: [4, 3] });
  escribir("Aquí irá el QR Verifactu", IZQ + vW / 2, y - vH / 2 + 4, { tam: 8.5, color: GRIS, alinear: "centro" });
  escribir("del software de facturación", IZQ + vW / 2, y - vH / 2 - 7, { tam: 8.5, color: GRIS, alinear: "centro" });
  escribir("Importes en euros. Forma de pago: pendiente de definir.", IZQ + 70 * MM, y - 9, { tam: 8.5, color: GRIS });
  escribir("IBAN: pendiente.", IZQ + 70 * MM, y - 20.5, { tam: 8.5, color: GRIS });

  escribir("Documento de demostración · sin validez fiscal · datos de la empresa pendientes", ANCHO / 2, 12 * MM,
           { tam: 7.5, color: GRIS, alinear: "centro" });
  return Buffer.from(await pdf.save());
}
