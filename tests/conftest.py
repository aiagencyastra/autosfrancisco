import os
import sys
import tempfile
from datetime import date
from pathlib import Path

import pytest

# La demo usa una base temporal durante las pruebas: nunca toca datos/montelier.db
_CARPETA = Path(tempfile.mkdtemp(prefix="montelier_pruebas_"))
os.environ["MONTELIER_BD"] = str(_CARPETA / "montelier.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import crear_base  # noqa: E402

HOY_FIJO = date(2026, 9, 24)  # jueves


@pytest.fixture
def bd_fija(tmp_path):
    """Base de ejemplo generada como si hoy fuera el 24/09/2026 (cifras conocidas)."""
    return crear_base.crear(tmp_path / "montelier.db", HOY_FIJO)
