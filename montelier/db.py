"""Acceso a la base del cliente. SIEMPRE en solo lectura.

Tres capas, por si una falla:
1. La conexión se abre con URI `mode=ro`: SQLite rechaza cualquier escritura
   ("attempt to write a readonly database").
2. `PRAGMA query_only = ON`: la conexión no puede ejecutar sentencias que modifiquen.
3. Un autorizador que solo permite lecturas (SELECT, lectura de columnas y funciones).
"""
import os
import sqlite3
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
RUTA_BD = Path(os.environ.get("MONTELIER_BD", RAIZ / "datos" / "montelier.db"))

_PERMITIDAS = {
    sqlite3.SQLITE_SELECT,
    sqlite3.SQLITE_READ,
    sqlite3.SQLITE_FUNCTION,
    getattr(sqlite3, "SQLITE_RECURSIVE", 33),
}


def _solo_lectura(accion, arg1, arg2, nombre_bd, disparador):
    if accion in _PERMITIDAS:
        return sqlite3.SQLITE_OK
    # PRAGMA query_only lo leemos nosotros al abrir; cualquier otro pragma, fuera.
    if accion == sqlite3.SQLITE_PRAGMA and arg1 == "query_only" and arg2 is None:
        return sqlite3.SQLITE_OK
    return sqlite3.SQLITE_DENY


def conectar(ruta=None) -> sqlite3.Connection:
    ruta = Path(ruta or RUTA_BD)
    if not ruta.exists():
        raise FileNotFoundError(f"No existe la base de datos: {ruta}")
    con = sqlite3.connect(f"{ruta.resolve().as_uri()}?mode=ro", uri=True, check_same_thread=False)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA query_only = ON")
    con.set_authorizer(_solo_lectura)
    return con
