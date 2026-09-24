# Demo Montelier

Demo local para la reunión de propuesta con Montelier (transporte y montaje).
**No es el producto final**: trabaja sobre una base SQLite de ejemplo que imita la estructura
de la suya, y todo lo que "sale" hacia fuera (WhatsApp, correo) está simulado.

Tiene dos pestañas:

- **Asistente**: chat con aspecto de WhatsApp. Francisco pregunta en lenguaje normal y Claude
  responde consultando la base con herramientas concretas. No inventa datos.
- **Facturas**: facturas aceptadas sin emitir, vista previa con IVA, aprobación por WhatsApp
  (simulada), PDF y envío al cliente (simulado).

## Arrancar

Requisitos: Python 3.10 o superior y conexión a internet (para la API de Anthropic).

```bash
./arrancar.sh          # macOS / Linux
arrancar.bat           # Windows
```

La primera vez crea el entorno, instala las dependencias (tarda un minuto) y crea el archivo `.env`.
Abre `.env`, pon la clave en `ANTHROPIC_API_KEY=` y vuelve a arrancar. Después, abre
**http://localhost:5050**.

Sin clave, la pestaña Facturas funciona entera y el Asistente avisa de que falta la clave.

Opcional en `.env`: `MODELO` (por defecto `claude-opus-5`) y `PUERTO` (por defecto 5050).

## Versión online (Netlify)

La misma demo está publicada en **https://montelier-demo-astra.netlify.app**, protegida con una
contraseña (variable `DEMO_CLAVE` en Netlify).

- Netlify no ejecuta Python, así que la versión online tiene el servidor en JavaScript
  (`netlify/`) con la misma lógica: misma base de ejemplo (`datos_ejemplo.json`), base en solo
  lectura, IVA calculado en el código y las mismas herramientas. La interfaz (`static/`) es la misma.
- La clave de Anthropic va en la variable de entorno `CLAVE_ANTHROPIC` del sitio en Netlify
  (Project configuration → Environment variables). Sin ella se usa el AI Gateway de Netlify,
  que tiene límites de uso.
- El estado de la pestaña Facturas se guarda en Netlify Blobs, no en la base.
- Pruebas de la versión online: `npm install && npm test`.
- Para volver a publicar: `npx netlify deploy --build --prod`.

## Datos de ejemplo

`crear_base.py` genera `datos/montelier.db` con 12 clientes (Barcelona y Tarragona),
25 presupuestos, 15 facturas de los últimos 3 meses (cobradas, pendientes y 3 aceptadas sin
emitir) y 8 peticiones (4 sin presupuestar esta semana y 1 de la semana pasada).

Las fechas se calculan respecto al día en que se arranca, así que "este mes" y "esta semana"
siempre tienen datos. La base se regenera sola si se arranca otro día; para forzarlo:
`.venv/bin/python crear_base.py --forzar`.

Todos los importes de la base van **sin IVA**. El IVA (21 %) se calcula siempre en el código
(`montelier/dinero.py`), con redondeo comercial a céntimos en cada factura, y nunca se guarda.

## Cómo está hecho

```
app.py                  servidor web (Flask) y API de la demo
crear_base.py           base SQLite de ejemplo
montelier/
  db.py                 conexión a la base, SIEMPRE en solo lectura
  dinero.py             IVA, redondeos y formato 1.210,00 €
  herramientas.py       herramientas que usa Claude para consultar
  asistente.py          conversación con Claude (API de Anthropic)
  facturacion.py        pestaña Facturas: vista previa, PDF y estado de la demo
static/                 interfaz (HTML, CSS y JS sin dependencias)
tests/                  pruebas
datos/                  (se crea al arrancar) base, estado de la demo y PDFs
```

**Solo lectura de verdad.** La base se abre con `mode=ro` a nivel de conexión SQLite, además
de `PRAGMA query_only` y un autorizador que solo deja leer. Cualquier `INSERT`, `UPDATE`,
`DELETE`, `DROP`, etc. da error aunque el modelo lo intente.

**Herramientas del asistente:** facturas por periodo (número, base, IVA y total), facturas
pendientes de cobro, presupuestos por estado, ficha de un cliente, peticiones sin presupuestar
entre dos fechas y, como último recurso, una consulta SQL libre de solo lectura. Las
herramientas devuelven los importes ya calculados y formateados, así que el modelo no hace cuentas.

**Pestaña Facturas.** No escribe en la base del cliente: lo que se emite o envía en la demo se
guarda en `datos/estado_demo.json` y los PDF en `datos/pdfs/`. El botón "Reiniciar demo" lo
deja todo como al principio.

**El PDF** lleva un logo provisional (MONTELIER), NIF y dirección como "pendiente", y un
recuadro con el texto "Aquí irá el QR Verifactu del software de facturación". No se simula
ningún QR ni número de Verifactu, y el número de factura queda como "lo asignará el software
de facturación".

## Pruebas

```bash
.venv/bin/python -m pytest
```

Cubren:

- el cálculo del IVA y los redondeos;
- que la base no se puede modificar (desde la conexión, desde la herramienta SQL y desde el
  bucle completo del asistente con un Claude simulado);
- que las cifras de las 4 preguntas de ejemplo coinciden con una consulta SQL directa a la base;
- que el PDF se genera y contiene lo que debe;
- el flujo emitir → aprobar → enviar sin tocar la base.

Si hay `ANTHROPIC_API_KEY` en el entorno, se ejecutan además 4 pruebas que hacen las preguntas
de ejemplo a Claude de verdad y comprueban la cifra en la respuesta. Sin clave, se saltan.

## Guion de 5 minutos

1. **(0:00) Contexto, 20 s.** "Esto funciona sobre una copia de ejemplo con la misma estructura
   que vuestra base. Solo lee: no puede cambiar nada."
2. **(0:20) Asistente, pregunta 1.** Pulsa *¿Cuántas facturas llevamos este mes y por cuánto?*
   Señala el total con y sin IVA, y el panel de la derecha, donde se ilumina la consulta usada.
3. **(1:00) Pregunta 2.** *¿Qué facturas están pendientes de cobro?* Sale la lista con los días
   que han pasado desde cada factura. "Esto es lo que hoy miráis a mano."
4. **(1:30) Pregunta 3.** *¿Me queda alguna petición por presupuestar esta semana?* Salen las
   4 de esta semana y no la de la semana pasada, porque entiende las fechas.
5. **(2:00) Pregunta 4 y una libre.** *¿Qué le hemos presupuestado a Hotel Costa Daurada?* y
   después pregunta por un cliente que no existe ("¿Y a Muebles Pérez?") para enseñar que dice
   que no hay datos. Si hay tiempo: "Borra la factura 3". Responde que solo puede consultar.
6. **(3:00) Pestaña Facturas.** Enseña las 3 aceptadas sin emitir. Abre una: base, IVA 21 %,
   total, datos del cliente y desglose transporte / montaje.
7. **(3:30) Emitir.** Pulsa *Emitir factura* y aparece el WhatsApp a Francisco:
   "Factura a …, … €. ¿La emito?". Pulsa **Sí**. "No sale nada sin que tú lo apruebes."
8. **(4:00) PDF y envío.** *Ver PDF*: logo, desglose y el recuadro reservado para el QR
   Verifactu del software de facturación. Vuelve y pulsa *Enviar al cliente*; enseña el
   registro de actividad.
9. **(4:40) Cierre.** Qué falta para producción: acceso a su base real, WhatsApp real, datos
   fiscales e integración con su software de facturación para Verifactu.

Antes de la reunión: arranca la demo, haz una pregunta de prueba (así confirmas que la clave
funciona) y pulsa *Reiniciar demo* en la pestaña Facturas.
