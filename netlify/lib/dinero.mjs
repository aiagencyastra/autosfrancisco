// IVA y formato de importes (misma lógica que montelier/dinero.py).
// Se trabaja en céntimos enteros para evitar errores de coma flotante.
// Todos los importes de la base van SIN IVA; el IVA (21 %) se calcula aquí y nunca se guarda.

export const aCentimos = (valor) => (valor == null ? 0 : Math.round(Number(String(valor)) * 100));

// 21 % con redondeo comercial (mitad hacia arriba) a céntimos
export const ivaCentimos = (base) => Math.sign(base) * Math.floor((Math.abs(base) * 21 + 50) / 100);

export function desglose(importeTransporte, importeMontaje = null) {
  const transporte = aCentimos(importeTransporte);
  const montaje = aCentimos(importeMontaje);
  const base = transporte + montaje;
  const iva = ivaCentimos(base);
  return { transporte, montaje, base, iva, total: base + iva };
}

export function sumarDesgloses(lista) {
  const total = { transporte: 0, montaje: 0, base: 0, iva: 0, total: 0 };
  for (const d of lista) for (const k of Object.keys(total)) total[k] += d[k];
  return total;
}

// 121000 céntimos -> "1.210,00 €"
export function formatoEur(centimos) {
  const signo = centimos < 0 ? "-" : "";
  const abs = Math.abs(Math.round(centimos));
  const entero = String(Math.floor(abs / 100)).replace(/\B(?=(\d{3})+(?!\d))/g, ".");
  return `${signo}${entero},${String(abs % 100).padStart(2, "0")} €`;
}

export const desgloseFormateado = (d) =>
  Object.fromEntries(Object.entries(d).map(([k, v]) => [k, formatoEur(v)]));
