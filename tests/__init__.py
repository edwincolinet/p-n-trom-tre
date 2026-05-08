"""Suite de tests unitaires de l'application Pénétromètre.

Lancer depuis la racine du projet :

    python3 -m unittest discover tests

Le `sys.path` est complété ici pour que `import resistographe` fonctionne
même si on exécute pytest, unittest ou un fichier de tests isolément.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
