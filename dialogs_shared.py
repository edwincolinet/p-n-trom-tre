"""Helpers purs extraits de `dialogs.py`.

Fonctions de parsing, de validation et de formatage qui n'ont aucune
dépendance Tk — testables en isolation et réutilisables par les panes
sans importer l'ensemble des dialogues modaux.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

from geometry import DIRECTION_LABELS, GRADES
from model import DegradationExterne


def grade_choices() -> list[str]:
    """Libellés des 16 directions, format `"100 gr — E"`.

    Public (avec `find_grade_choice` / `parse_grade`) car réutilisé par
    les combobox de saisie en place de `pane_degradations`."""
    out = []
    for g in GRADES:
        lbl = DIRECTION_LABELS.get(g, "")
        out.append(f"{g} gr" + (f" — {lbl}" if lbl else ""))
    return out


def find_grade_choice(choices: list[str], grade_value: int) -> str:
    """Renvoie l'entrée de `choices` qui commence par `<grade_value> gr`."""
    for c in choices:
        if c.startswith(f"{grade_value} gr"):
            return c
    return choices[0]


def parse_grade(s: str) -> int:
    """Extrait le grade entier d'une chaîne `"100 gr — E"` (tolère
    aussi l'ancien format `"100° — E"`)."""
    return int(s.replace("°", " ").split(" ")[0].strip())


def message_chevauchement(other: DegradationExterne,
                          shared: List[int]) -> str:
    """Texte d'avertissement quand un arc candidat chevauche `other`
    (cf. `model.degradations_chevauchements`). Partagé entre le dialogue
    `edit_degradation` et la saisie en place de `pane_degradations`."""
    labels = ", ".join(f"{g} gr" for g in shared[:4])
    if len(shared) > 4:
        labels += ", …"
    return (f"La dégradation n°{other.numero} ({other.grade_debut} gr → "
            f"{other.grade_fin} gr) couvre déjà les directions "
            f"{labels}.\n\nLes arcs ne doivent pas se chevaucher.")


# --- « Zone dégradée » d'une dégradation externe (comprend_ecorce) ------
# Source unique des libellés, partagée entre la grille (pane_degradations)
# et la modale (edit_degradation) : la case booléenne nue était illisible
# (sens et impact PRBS cachés dans un tooltip). Texte explicite à la place.
ZONE_ECORCE_BOIS = "Écorce + bois"   # comprend_ecorce = True (défaut)
ZONE_BOIS_SEUL = "Bois seul"         # comprend_ecorce = False
ZONE_DEGRADEE_CHOICES = (ZONE_ECORCE_BOIS, ZONE_BOIS_SEUL)
ZONE_DEGRADEE_AIDE = (
    "Zone dégradée — « Écorce + bois » : la zone part de la surface ; "
    "l'épaisseur d'écorce traversée n'est pas comptée comme bois perdu. "
    "« Bois seul » : l'écorce reste intacte, toute la profondeur est du "
    "bois sain perdu."
)

# --- Validités de suivi ---------------------------------------------------
# Durées proposées dans le combobox « Validité » du bloc Suivi.
SUIVI_VALIDITES = ("1 an", "2 ans", "3 ans", "4 ans", "5 ans")


def zone_degradee_label(comprend_ecorce: bool) -> str:
    """Libellé affiché pour l'état `comprend_ecorce` d'une dégradation."""
    return ZONE_ECORCE_BOIS if comprend_ecorce else ZONE_BOIS_SEUL


def zone_degradee_to_bool(label: str) -> bool:
    """Inverse de `zone_degradee_label` : libellé → `comprend_ecorce`."""
    return label == ZONE_ECORCE_BOIS


def _round_to_25(v: int, *, min_v: int = 0, max_v: int = 375,
                  wrap: bool = True) -> int:
    """Arrondit à 25 près. `wrap=True` ramène modulo 400 (pour les
    grades), `wrap=False` clamp dans `[min_v, max_v]` (pour les
    largeurs de contrefort)."""
    v = round(v / 25) * 25
    if wrap:
        return v % 400
    return max(min_v, min(max_v, v))


def validate_numeric(proposed: str) -> bool:
    """Validateur Tk (validate="key") pour les champs numériques
    positifs. Accepte : vide, chiffres, et au plus un séparateur
    décimal (`.` ou `,`). Refuse tout autre caractère à la frappe.

    Public car réutilisé par les onglets (`pane_identification`)."""
    if proposed == "":
        return True
    if proposed.count(",") + proposed.count(".") > 1:
        return False
    test = proposed.replace(",", ".", 1)
    try:
        float(test)
    except ValueError:
        return False
    return True


def to_float(s: str) -> float:
    """Convertit la saisie utilisateur en float, en acceptant la
    virgule comme séparateur décimal (format français). Chaîne vide
    → 0.0. Public car réutilisé par `pane_identification`."""
    s = (s or "").strip().replace(",", ".")
    if not s:
        return 0.0
    return float(s)


_DATE_SEP_RE = re.compile(r"[/\-.\s]+")


def normaliser_date(s: str) -> Optional[str]:
    """Normalise une date de relevé saisie librement en « JJ/MM/AAAA ».

    Accepte les séparateurs `/ - .` ou espace, l'année sur 2 ou 4
    chiffres, et l'ordre français (jour d'abord) **ou** ISO (année
    d'abord, détectée si le 1er champ a 4 chiffres ou vaut > 31). La
    validité réelle est vérifiée via `datetime.date` (rejette 31/02).

    Renvoie :
    - `""`     si la saisie est vide (date facultative) ;
    - la chaîne « JJ/MM/AAAA » normalisée si la date est valide ;
    - `None`   si la saisie est non vide et non interprétable (l'appelant
               rétablit alors la valeur précédente).

    Pure (testable) : pas de dépendance Tk.
    """
    s = (s or "").strip()
    if not s:
        return ""
    parts = _DATE_SEP_RE.split(s)
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        return None
    a, b, c = (int(p) for p in parts)
    # ISO (année en tête) si 1er champ sur 4 chiffres ou hors plage jour.
    if len(parts[0]) == 4 or a > 31:
        year, month, day = a, b, c
    else:
        day, month, year = a, b, c
    if year < 100:
        year += 2000
    try:
        d = date(year, month, day)
    except ValueError:
        return None
    return f"{d.day:02d}/{d.month:02d}/{d.year:04d}"


def annees_entre(date_a: str, date_b: str) -> Optional[float]:
    """Durée en années (float, base 365.25 j) entre deux dates saisies
    (normalisées par `normaliser_date`). `None` si l'une est vide ou
    illisible. Signé : négatif si `date_b` précède `date_a`. Sert au taux
    d'évolution « cm/an » de la comparaison inter-missions."""
    na, nb = normaliser_date(date_a), normaliser_date(date_b)
    if not na or not nb:
        return None
    ja, ma, aa = (int(x) for x in na.split("/"))
    jb, mb, ab = (int(x) for x in nb.split("/"))
    return (date(ab, mb, jb) - date(aa, ma, ja)).days / 365.25
