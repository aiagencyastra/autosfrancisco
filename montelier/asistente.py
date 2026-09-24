"""Asistente de consultas: Claude + herramientas sobre la base en solo lectura."""
import json
import os
from datetime import date, timedelta

import anthropic

from . import herramientas
from .db import conectar

MODELO = os.environ.get("MODELO", "claude-opus-5")
MAX_VUELTAS = 8
DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
         "septiembre", "octubre", "noviembre", "diciembre"]

INSTRUCCIONES = """Eres el asistente interno de Montelier, empresa de transporte y montaje de \
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
- Si la pregunta es ambigua (por ejemplo, varios clientes con un nombre parecido), pregunta."""


def contexto_fechas(hoy: date) -> str:
    lunes = hoy - timedelta(days=hoy.weekday())
    inicio_mes = hoy.replace(day=1)
    fin_mes = (inicio_mes + timedelta(days=32)).replace(day=1) - timedelta(days=1)
    return (f"Hoy es {DIAS[hoy.weekday()]} {hoy.day} de {MESES[hoy.month - 1]} de {hoy.year} "
            f"({hoy.isoformat()}). Esta semana va del {lunes.isoformat()} al "
            f"{(lunes + timedelta(days=6)).isoformat()}. Este mes va del {inicio_mes.isoformat()} "
            f"al {fin_mes.isoformat()}.")


def _texto(contenido) -> str:
    return "\n".join(b.text for b in contenido if b.type == "text").strip()


def responder(historial: list[dict], cliente: anthropic.Anthropic | None = None,
              hoy: date | None = None, ruta_bd=None) -> dict:
    """historial: [{"rol": "usuario"|"asistente", "texto": "..."}], el último es la pregunta.

    Devuelve {"texto": ..., "consultas": [nombres de herramientas usadas]}.
    """
    cliente = cliente or anthropic.Anthropic()
    hoy = hoy or date.today()
    mensajes = [{"role": "user" if m["rol"] == "usuario" else "assistant", "content": m["texto"]}
                for m in historial if m.get("texto")]
    sistema = f"{INSTRUCCIONES}\n\n{contexto_fechas(hoy)}"
    consultas = []
    con = conectar(ruta_bd)
    try:
        for _ in range(MAX_VUELTAS):
            respuesta = cliente.beta.messages.create(
                model=MODELO,
                max_tokens=16000,
                system=sistema,
                tools=herramientas.DEFINICIONES,
                messages=mensajes,
                thinking={"type": "adaptive"},
                output_config={"effort": "low"},
                # Si el modelo declina por sus filtros de seguridad, la API reintenta con otro modelo
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            if respuesta.stop_reason == "refusal":
                return {"texto": "No puedo responder a eso. Prueba a preguntarlo de otra forma.",
                        "consultas": consultas}
            if respuesta.stop_reason != "tool_use":
                return {"texto": _texto(respuesta.content) or "No tengo respuesta para eso.",
                        "consultas": consultas}

            mensajes.append({"role": "assistant", "content": respuesta.content})
            resultados = []
            for bloque in respuesta.content:
                if bloque.type != "tool_use":
                    continue
                consultas.append(bloque.name)
                try:
                    datos = herramientas.ejecutar(con, bloque.name, bloque.input)
                    resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                       "content": json.dumps(_limpiar(datos), ensure_ascii=False)})
                except herramientas.ErrorHerramienta as e:
                    resultados.append({"type": "tool_result", "tool_use_id": bloque.id,
                                       "content": f"Error: {e}", "is_error": True})
            mensajes.append({"role": "user", "content": resultados})
        return {"texto": "Me he liado con esta consulta. ¿Me la puedes preguntar de otra forma?",
                "consultas": consultas}
    finally:
        con.close()


def _limpiar(datos):
    """Quita los campos internos (los que empiezan por _) antes de enviarlos al modelo."""
    if isinstance(datos, dict):
        return {k: _limpiar(v) for k, v in datos.items() if not k.startswith("_")}
    if isinstance(datos, list):
        return [_limpiar(v) for v in datos]
    return datos
