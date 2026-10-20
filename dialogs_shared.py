"""Helpers purs extraits de `dialogs.py`.

Fonctions de parsing, de validation et de formatage qui n'ont aucune
dépendance Tk — testables en isolation et réutilisables par les panes
sans importer l'ensemble des dialogues modaux.
"""

from __future__ import annotations

import re
from datetime import date
from typing import List, Optional

import angle_units
from geometry import DIRECTION_LABELS, GRADES
from i18n import _, untranslate_value
from model import DegradationExterne
from palette import COLOR_ACCENT, COLOR_MUTED, COLOR_WARN

# --- Compartimentation (sondages) ----------------------------------------
# Valeurs modèle canoniques (français, stockées telles quelles dans le
# fichier). L'ordre n'est pas imposé : chaque combobox passe le sien.
COMPART_FR = ["non renseignée", "active", "absente"]
# Valeur « non renseignée » et son libellé d'affichage : un tiret fin
# (demi-cadratin U+2013), neutre quelle que soit la langue.
COMPART_NR = "non renseignée"
COMPART_NR_LABEL = "–"

# SOURCE UNIQUE des symboles de compartimentation. Le MÊME glyphe est
# affiché à la saisie (combobox « ✓ active ») et dans tous les exports
# (cellule XLSX/HTML/PDF, symbole seul + légende). Coche et croix **fines**
# (U+2713 / U+2717, présentes dans DejaVu → rendu PDF garanti) : traits
# légers, plus dans l'esprit épuré du logiciel que les « ballot » épais
# (U+2714 / U+2718) d'avant, tout en gardant des formes bien distinctes.
# Couleurs = accent vert Pénétromètre Silvavenir / rouge alerte / gris muted palette (hex
# avec « # » : PIL & CSS ; openpyxl attend sans « # » → `.lstrip("#")` côté
# export).
COMPART_GLYPH = {
    "active": "✓",
    "absente": "✗",
    "non renseignée": COMPART_NR_LABEL,
}
COMPART_COLOR = {
    "active": "#2D7A3E",
    "absente": "#C0392B",
    "non renseignée": "#55605A",
}


def compart_glyph(value_fr: str) -> str:
    """Symbole d'un état de compartimentation (repli neutre « — »)."""
    return COMPART_GLYPH.get((value_fr or "").lower().strip(),
                             COMPART_NR_LABEL)


def compart_color(value_fr: str) -> str:
    """Couleur (hex `#RRGGBB`) associée au symbole (repli neutre gris)."""
    return COMPART_COLOR.get((value_fr or "").lower().strip(),
                             COMPART_COLOR[COMPART_NR])


def compart_visual(value_fr: str) -> tuple[str, str]:
    """`(glyphe, couleur_hex)` — pratique pour les exports qui posent les
    deux d'un coup."""
    return compart_glyph(value_fr), compart_color(value_fr)


def compart_label(value_fr: str) -> str:
    """Libellé affiché d'une compartimentation : tiret long seul pour
    « non renseignée », sinon « ✔/✘ » + le mot traduit (i18n)."""
    if value_fr == COMPART_NR:
        return COMPART_NR_LABEL
    return f"{compart_glyph(value_fr)} {_(value_fr)}"


def compart_choices(order: Optional[List[str]] = None) -> List[str]:
    """Valeurs affichables d'un combobox de compartimentation, dans
    l'ordre demandé (défaut : `COMPART_FR`)."""
    return [compart_label(v) for v in (order or COMPART_FR)]


def compart_from_label(display: str) -> str:
    """Valeur modèle depuis le libellé affiché (inverse de
    `compart_label`). Retire un éventuel glyphe de tête (« ✔ active » →
    « active »), tolère l'ancien libellé traduit de « non renseignée » et
    les valeurs inconnues (renvoyées telles quelles)."""
    d = (display or "").strip()
    for g in COMPART_GLYPH.values():
        if g != COMPART_NR_LABEL and d.startswith(g):
            d = d[len(g):].strip()
            break
    if d in ("", COMPART_NR_LABEL, _(COMPART_NR)):
        return COMPART_NR
    return untranslate_value(d, COMPART_FR)


def angle_head() -> str:
    """En-tête de colonne « Grade » / « Degrés » selon l'unité d'angle."""
    return _("Degrés") if angle_units.est_degre() else _("Grade")


def largeur_head() -> str:
    """En-tête « Largeur (gr) » / « Largeur (°) »."""
    return _("Largeur (°)") if angle_units.est_degre() else _("Largeur (gr)")


def largeur_grades_saisie(texte: str) -> int:
    """Largeur saisie dans l'unité courante → **grades** entiers (vide ou
    nul → 25 gr, le pas minimal)."""
    raw = to_float(texte)
    return int(round(angle_units.depuis_unite(raw))) if raw else 25


def largeur_label(multiple: bool = False) -> str:
    """Libellé du champ de largeur angulaire d'un dialogue."""
    if angle_units.est_degre():
        return (_("Largeur en degrés (multiple de 22,5)") if multiple
                else _("Largeur en degrés"))
    return (_("Largeur en grades (multiple de 25)") if multiple
            else _("Largeur en grades"))


def grade_choices() -> list[str]:
    """Libellés des 16 directions, format `"100 gr — E"` (ou `"90° — E"`
    selon l'unité d'angle choisie, cf. `angle_units`).

    Public (avec `find_grade_choice` / `parse_grade`) car réutilisé par
    les combobox de saisie en place de `pane_degradations`."""
    out = []
    for g in GRADES:
        lbl = DIRECTION_LABELS.get(g, "")
        out.append(angle_units.fmt(g) + (f" — {lbl}" if lbl else ""))
    return out


def find_grade_choice(choices: list[str], grade_value: int) -> str:
    """Renvoie l'entrée de `choices` qui commence par la valeur d'angle de
    `grade_value` (dans l'unité courante)."""
    prefix = angle_units.fmt(grade_value)
    for c in choices:
        if c == prefix or c.startswith(prefix + " "):
            return c
    return choices[0]


def parse_grade(s: str) -> int:
    """Extrait le **grade** entier d'une chaîne `"100 gr — E"` ou
    `"90° — E"` (le suffixe présent prime sur l'unité courante)."""
    v = angle_units.parse(s.split("—")[0])
    if v is None:
        raise ValueError(s)
    return int(round(v))


def message_chevauchement(other: DegradationExterne,
                          shared: List[int]) -> str:
    """Texte d'avertissement quand un arc candidat chevauche `other`
    (cf. `model.degradations_chevauchements`). Partagé entre le dialogue
    `edit_degradation` et la saisie en place de `pane_degradations`."""
    labels = ", ".join(angle_units.fmt(g) for g in shared[:4])
    if len(shared) > 4:
        labels += ", …"
    return (f"La dégradation n°\u00a0{other.numero} ({angle_units.fmt(other.grade_debut)} → "
            f"{angle_units.fmt(other.grade_fin)}) couvre déjà les directions "
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
    return _(ZONE_ECORCE_BOIS) if comprend_ecorce else _(ZONE_BOIS_SEUL)


def zone_degradee_choices() -> "tuple[str, str]":
    """Libellés traduits pour le combobox « Zone dégradée » — à appeler à
    la construction du widget (pas au niveau module : la langue n'est
    connue qu'après `i18n.setup_language()`, cf. `ZONE_DEGRADEE_CHOICES`
    qui reste la forme française canonique pour toute comparaison)."""
    return (zone_degradee_label(True), zone_degradee_label(False))


def zone_degradee_to_bool(label: str) -> bool:
    """Inverse de `zone_degradee_label` : libellé (traduit) → `comprend_ecorce`."""
    return label == _(ZONE_ECORCE_BOIS)


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


# --- Indicateur d'enregistrement (barre d'état) --------------------------
# SOURCE UNIQUE du texte/couleur/activation du bouton « Enregistrer » —
# partagée par la barre d'état principale (`penetrometre._update_save_indicator`)
# et le pied de la fenêtre de comparaison (`comparaison.open_comparison`),
# pour que les deux bandeaux affichent TOUJOURS le même indicateur pour un
# même état, sans dupliquer la logique texte/couleur.
def save_state_label(*, dirty: bool, has_file: bool) -> tuple[str, str, bool]:
    """Texte, couleur (hex) et activation du bouton pour l'indicateur
    d'enregistrement, selon l'état `dirty`/`has_file` (mission jamais
    enregistrée). Renvoie `(texte, couleur, bouton_actif)`."""
    if dirty:
        return _("● Modifications non enregistrées"), COLOR_WARN, True
    if has_file:
        return _("✓ Enregistré"), COLOR_ACCENT, False
    # Mission neuve jamais enregistrée : rien à perdre, mais le bouton
    # reste actif (premier « Enregistrer sous… »).
    return _("Mission non enregistrée"), COLOR_MUTED, True


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
