"""
Import de données terrain depuis un fichier CSV.

Format accepté : une ligne par sondage (N° arbre, Grade, PRBS), ou une
ligne par arbre sans sondages (N° arbre, Essence, Rayon…). Les lignes
d'un même N° sont regroupées en un seul `Arbre`.

Délimiteur détecté automatiquement (`;`, `,`, tabulation).

Module pur (stdlib, sans Tkinter ni PIL). Utilisé par `dialogs_import`
et `app_fichier.action_import_csv`.
"""

from __future__ import annotations

import csv
import io
import logging
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence, Tuple

if TYPE_CHECKING:
    from model import Arbre

log = logging.getLogger("penetrometre")

# ------------------------------------------------------------------
# Champs cibles du modèle disponibles pour le mapping
# ------------------------------------------------------------------

CHAMPS_CIBLES: Dict[str, str] = {
    "numero_arbre":        "N° arbre (requis)",
    "essence":             "Essence",
    "port_arbre":          "Port arbre",
    "rayon_tronc_cm":      "Rayon (cm)",
    "epaisseur_ecorce_cm": "Épaisseur écorce (cm)",
    "hauteur_sondage_cm":  "Hauteur de sondage (cm)",
    "grade_sondage":       "Grade sondage (gr)",
    "prbs_cm":             "PRBS sondage (cm)",
}

_CHAMP_IGNORE = ""   # sentinel → colonne ignorée

# Correspondances automatiques : clé = variante normalisée du nom de
# colonne CSV (minuscule, sans accents, espaces → underscore).
_AUTO_MAP: Dict[str, str] = {
    # N° arbre
    "n_arbre":        "numero_arbre",
    "n_arbre_":       "numero_arbre",
    "num":            "numero_arbre",
    "numero":         "numero_arbre",
    "no":             "numero_arbre",
    "n":              "numero_arbre",
    "arbre":          "numero_arbre",
    "id":             "numero_arbre",
    "inventaire":     "numero_arbre",
    # Essence
    "essence":        "essence",
    "espece":         "essence",
    "espece_":        "essence",
    # Port
    "port":           "port_arbre",
    "port_arbre":     "port_arbre",
    # Rayon
    "rayon":          "rayon_tronc_cm",
    "rayon_cm":       "rayon_tronc_cm",
    "r_cm":           "rayon_tronc_cm",
    "r":              "rayon_tronc_cm",
    # Écorce
    "ecorce":         "epaisseur_ecorce_cm",
    "ep_ecorce":      "epaisseur_ecorce_cm",
    "ecorce_cm":      "epaisseur_ecorce_cm",
    # Hauteur sondage
    "h_sondage":      "hauteur_sondage_cm",
    "hauteur_sondage":"hauteur_sondage_cm",
    "h_s":            "hauteur_sondage_cm",
    # Grade
    "grade":          "grade_sondage",
    "grade_gr":       "grade_sondage",
    "gr":             "grade_sondage",
    "direction":      "grade_sondage",
    "azimut":         "grade_sondage",
    # PRBS
    "prbs":           "prbs_cm",
    "prbs_cm":        "prbs_cm",
    "bois_sain":      "prbs_cm",
    "sain":           "prbs_cm",
    "bois_sain_cm":   "prbs_cm",
    "paroi":          "prbs_cm",
    "paroi_cm":       "prbs_cm",
}


def _norm_col(name: str) -> str:
    """Normalise un nom de colonne pour l'auto-map."""
    import unicodedata
    s = unicodedata.normalize("NFD", name.lower().strip())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return (s.replace(" ", "_").replace("(", "").replace(")", "")
             .replace("°", "").replace(".", "").replace("/", "_")
             .strip("_"))


def detect_delimiter(raw: str) -> str:
    """Détecte le délimiteur (`;`, `,`, tabulation) sur les 4 premières lignes."""
    sample = "\n".join(raw.splitlines()[:4])
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
        return dialect.delimiter
    except csv.Error:
        return ";"


def read_csv(path: str) -> Tuple[str, List[str], List[Dict[str, str]]]:
    """Lit un fichier CSV et renvoie (délimiteur, en-têtes, lignes).

    Essaie UTF-8 puis cp1252 (Excel français)."""
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            with open(path, encoding=enc, newline="") as f:
                raw = f.read()
            break
        except UnicodeDecodeError:
            continue
    else:
        raise ValueError("Impossible de décoder le fichier CSV.")

    delim = detect_delimiter(raw)
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    rows = list(reader)
    headers = list(reader.fieldnames or [])
    return delim, headers, rows


def auto_map(headers: Sequence[str]) -> Dict[str, str]:
    """Propose un mapping automatique CSV→champ modèle."""
    result: Dict[str, str] = {}
    used: set[str] = set()
    for h in headers:
        key = _norm_col(h)
        champ = _AUTO_MAP.get(key, _CHAMP_IGNORE)
        if champ and champ not in used:
            result[h] = champ
            used.add(champ)
        else:
            result[h] = _CHAMP_IGNORE
    return result


def build_arbres(
        rows: List[Dict[str, str]],
        mapping: Dict[str, str],
) -> Tuple[List["Arbre"], List[str]]:
    """Construit des `Arbre` à partir des lignes CSV et du mapping.

    Renvoie `(arbres, avertissements)`. Les lignes invalides sont ignorées
    (avertissements), les arbres valides retournés dans l'ordre de première
    apparition de leur N°.

    Si les colonnes Grade et PRBS sont mappées : une ligne = un sondage,
    plusieurs lignes par arbre sont regroupées.
    Si ces colonnes sont absentes : une ligne = un arbre sans sondage.
    """
    from model import Arbre, Sondage

    # Colonne source pour chaque champ cible
    def _col(champ: str) -> Optional[str]:
        for csv_col, target in mapping.items():
            if target == champ:
                return csv_col
        return None

    col_num   = _col("numero_arbre")
    col_ess   = _col("essence")
    col_port  = _col("port_arbre")
    col_ray   = _col("rayon_tronc_cm")
    col_ecor  = _col("epaisseur_ecorce_cm")
    col_hs    = _col("hauteur_sondage_cm")
    col_grade = _col("grade_sondage")
    col_prbs  = _col("prbs_cm")

    if not col_num:
        return [], ["La colonne N° arbre est requise."]

    has_sondages = bool(col_grade and col_prbs)

    arbres_map: Dict[str, Arbre] = {}    # N° → Arbre (ordre d'insertion préservé)
    avertissements: List[str] = []

    def _float(row: Dict[str, str], col: Optional[str]) -> Optional[float]:
        if not col:
            return None
        raw = row.get(col, "").replace(",", ".").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _str(row: Dict[str, str], col: Optional[str]) -> str:
        if not col:
            return ""
        return row.get(col, "").strip()

    for i, row in enumerate(rows, 1):
        num = _str(row, col_num)
        if not num:
            continue

        if num not in arbres_map:
            a = Arbre(numero_arbre=num)
            if col_ess:
                a.essence = _str(row, col_ess)
            if col_port:
                from bareme import normaliser_port
                a.port_arbre = normaliser_port(_str(row, col_port)) or "libre"
            b = a.brins[0]
            if col_ray:
                v = _float(row, col_ray)
                if v and v > 0:
                    b.rayon_tronc_cm = v
            if col_ecor:
                v = _float(row, col_ecor)
                if v is not None and v >= 0:
                    b.epaisseur_ecorce_cm = v
            if col_hs:
                v = _float(row, col_hs)
                if v is not None and v >= 0:
                    a.hauteur_sondage_cm = v
            arbres_map[num] = a

        if has_sondages:
            a = arbres_map[num]
            b = a.brins[0]
            grade_raw = _float(row, col_grade)
            prbs_raw  = _float(row, col_prbs)
            if grade_raw is None or prbs_raw is None:
                avertissements.append(
                    f"Ligne {i} : Grade ou PRBS manquant — ignorée.")
                continue
            grade = int(round(grade_raw))
            if grade % 25 != 0 or not (0 <= grade <= 375):
                avertissements.append(
                    f"Ligne {i} : grade {grade} invalide "
                    f"(multiple de 25, 0–375) — ignorée.")
                continue
            # Unicité : un seul sondage par grade
            if any(s.grade == grade for s in b.sondages):
                avertissements.append(
                    f"Ligne {i} : doublon grade {grade} pour arbre {num} "
                    f"— premier sondage conservé.")
                continue
            R = b.rayon_tronc_cm
            sain = max(0.0, min(float(prbs_raw), R if R > 0 else float(prbs_raw)))
            num_s = len(b.sondages) + 1
            b.sondages.append(Sondage(numero=num_s, grade=grade,
                                      bois_sain_cm=sain))

    # Trier les sondages par grade dans chaque arbre
    for a in arbres_map.values():
        a.brins[0].sondages.sort(key=lambda s: s.grade)
        a.brins[0].renumeroter_sondages()

    return list(arbres_map.values()), avertissements
