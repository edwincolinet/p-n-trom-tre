"""
Réglages d'interface persistés.

Petit magasin autonome (composition, pas de couplage à `App`), sur le
modèle de `app_recent.RecentFilesStore`. Détient pour l'instant un seul
réglage : `ui_scale`, le facteur d'agrandissement du texte de
l'interface (accessibilité — laptops de terrain en plein soleil, écrans
HiDPI). Persisté dans `~/.penetrometre/settings.json`.

Tolérant par construction : toute erreur d'I/O (fichier absent, JSON
corrompu) est journalisée et n'interrompt jamais l'app — au pire on
repart sur les valeurs par défaut.

Module pur (JSON + dict), testable sans Tk.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path

log = logging.getLogger("penetrometre")

# Facteur d'échelle du texte. 1.0 = taille native (DPI système). Bornes
# volontairement modestes : au-delà, les libellés débordent des cases de
# saisie à largeur fixe. Presets exposés dans le menu « Affichage ».
UI_SCALE_MIN = 0.8
UI_SCALE_MAX = 1.6
UI_SCALE_DEFAULT = 1.0


class SettingsStore:
    """Réglages d'interface persistés en JSON. Lecture/écriture tolérante."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._data: dict[str, object] = self._load()

    @property
    def ui_scale(self) -> float:
        """Facteur d'échelle du texte, borné à [MIN, MAX]."""
        raw = self._data.get("ui_scale", UI_SCALE_DEFAULT)
        try:
            val = float(raw)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return UI_SCALE_DEFAULT
        return max(UI_SCALE_MIN, min(UI_SCALE_MAX, val))

    def set_ui_scale(self, value: float) -> None:
        """Fixe et persiste le facteur d'échelle (borné)."""
        self._data["ui_scale"] = max(UI_SCALE_MIN, min(UI_SCALE_MAX, value))
        self._save()

    @property
    def high_contrast(self) -> bool:
        """Mode contraste élevé de l'UI (accessibilité plein soleil)."""
        return bool(self._data.get("high_contrast", False))

    def set_high_contrast(self, value: bool) -> None:
        """Fixe et persiste le mode contraste élevé."""
        self._data["high_contrast"] = bool(value)
        self._save()

    @property
    def angle_unit(self) -> str:
        """Unité d'affichage des angles : « grade » (défaut) ou « degre »
        (cf. `angle_units`). Valeur inconnue → grade."""
        raw = str(self._data.get("angle_unit", "grade"))
        return raw if raw in ("grade", "degre") else "grade"

    def set_angle_unit(self, value: str) -> None:
        """Fixe et persiste l'unité d'angle (grade/degre)."""
        self._data["angle_unit"] = value if value in ("grade", "degre") else "grade"
        self._save()

    def language(self) -> str:
        """Code de langue de l'interface (fr/en/it). Défaut : fr."""
        return str(self._data.get("language", "fr"))

    def set_language(self, value: str) -> None:
        self._data["language"] = str(value)
        self._save()

    def check_updates(self) -> bool:
        """Vérification automatique des mises à jour au démarrage (défaut : True)."""
        return bool(self._data.get("check_updates", True))

    def set_check_updates(self, value: bool) -> None:
        self._data["check_updates"] = bool(value)
        self._save()

    def update_folder(self) -> str:
        """Dossier partagé où chercher les installeurs plus récents
        (dépôt GitHub privé). Chaîne vide = non configuré."""
        v = self._data.get("update_folder", "")
        return v if isinstance(v, str) else ""

    def set_update_folder(self, value: str) -> None:
        self._data["update_folder"] = str(value)
        self._save()

    def get_sash_positions(self) -> list[int]:
        """Positions X (px) des poignées de la disposition 3 colonnes,
        ou `[]` si jamais réglées / valeur corrompue. Tolérant."""
        raw = self._data.get("sash_positions", [])
        if not isinstance(raw, list):
            return []
        out: list[int] = []
        for v in raw:
            try:
                out.append(int(v))
            except (TypeError, ValueError):
                return []
        return out

    def set_sash_positions(self, positions: list[int]) -> None:
        """Persiste les positions des poignées (réglage souris de la
        répartition liste / saisie / dessin)."""
        self._data["sash_positions"] = [int(p) for p in positions]
        self._save()

    @property
    def cabinet_name(self) -> str:
        """Nom du cabinet affiché dans les exports (pied de page)."""
        raw = self._data.get("cabinet_name", "")
        return str(raw) if raw else ""

    def set_cabinet_name(self, value: str) -> None:
        """Persiste le nom du cabinet."""
        self._data["cabinet_name"] = str(value)
        self._save()

    @property
    def logo_path(self) -> "str | None":
        """Chemin vers le logo du cabinet (copie locale dans ~/.penetrometre/)."""
        raw = self._data.get("logo_path")
        return str(raw) if raw else None

    def set_logo_path(self, value: "str | None") -> None:
        """Persiste le chemin du logo (None = pas de logo)."""
        if value is None:
            self._data.pop("logo_path", None)
        else:
            self._data["logo_path"] = str(value)
        self._save()

    def get_operateurs_history(self) -> "list[str]":
        """Noms d'opérateurs utilisés récemment (plus récent en premier, max 10)."""
        raw = self._data.get("operateurs_history", [])
        if not isinstance(raw, list):
            return []
        return [str(v) for v in raw if str(v).strip()]

    def push_operateur(self, name: str) -> None:
        """Ajoute un nom à l'historique opérateurs (dédupliqué, max 10)."""
        name = name.strip()
        if not name:
            return
        history = self.get_operateurs_history()
        if name in history:
            history.remove(name)
        history.insert(0, name)
        self._data["operateurs_history"] = history[:10]
        self._save()

    def get_urgences_custom(self) -> "list[str]":
        """Niveaux d'urgence personnalisés ajoutés par l'utilisateur."""
        raw = self._data.get("urgences_custom", [])
        if not isinstance(raw, list):
            return []
        return [str(v) for v in raw if str(v).strip()]

    def set_urgences_custom(self, values: "list[str]") -> None:
        """Persiste les niveaux d'urgence personnalisés (vides filtrés)."""
        self._data["urgences_custom"] = [str(v) for v in values
                                         if str(v).strip()]
        self._save()

    def get_suivi_custom(self) -> "list[str]":
        """Durées de suivi personnalisées ajoutées par l'utilisateur."""
        raw = self._data.get("suivi_custom", [])
        if not isinstance(raw, list):
            return []
        return [str(v) for v in raw if str(v).strip()]

    def set_suivi_custom(self, values: "list[str]") -> None:
        """Persiste les durées de suivi personnalisées (vides filtrées)."""
        self._data["suivi_custom"] = [str(v) for v in values
                                      if str(v).strip()]
        self._save()

    def _load(self) -> dict[str, object]:
        try:
            if self._path.exists():
                with open(self._path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    return data
        except Exception:
            log.exception("Lecture settings.json")
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp",
                                       prefix=self._path.stem + "_")
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(self._data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self._path)
            except BaseException:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass
                raise
        except Exception:
            log.exception("Écriture settings.json")
