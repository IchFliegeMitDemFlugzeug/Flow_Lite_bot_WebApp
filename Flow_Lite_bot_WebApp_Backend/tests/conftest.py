"""Настраивает путь импорта для тестов backend."""

from __future__ import annotations

import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parent.parent  # Абсолютный путь до каталога backend
if str(BACKEND_ROOT) not in sys.path:  # Гарантируем доступность локальных модулей
    sys.path.insert(0, str(BACKEND_ROOT))

