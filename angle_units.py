"""
Unité d'affichage des angles : grades (défaut) ou degrés.

**Affichage et saisie uniquement.** Le modèle, les fichiers de mission, la
géométrie et le diagnostic restent TOUJOURS en grades (0 à 375 par pas de
25, 400 gr = 360°) : changer d'unité ne modifie aucune donnée ni aucun
fichier, c'est une préférence de poste (`app_settings.SettingsStore`).

Module pur (stdlib) : facteur de process, comme `ui_fonts.set_ui_scale`,
fixé au démarrage puis à chaud par `App.action_set_angle_unit`. Toute
chaîne d'angle montrée à l'utilisateur ou écrite dans un export passe par
`fmt` / `nombre` / `suffixe` — jamais de « gr » écrit en dur.

Conventions : grade → « 100 gr » (pas de symbole °, cf. CLAUDE.md) ;
degré → « 90° » ; 25 gr = 22,5° (une décimale au plus : 22.5°).
"""

from __future__ import annotations

GRADE = "grade"
DEGRE = "degre"
UNITES = (GRADE, DEGRE)

# 400 gr = 360° → 1 gr = 0,9°.
DEGRES_PAR_GRADE = 0.9

_unite = GRADE


def set_unite(unite: str) -> None:
    """Fixe l'unité (valeur inconnue → grades)."""
    global _unite
    _unite = unite if unite in UNITES else GRADE


def get_unite() -> str:
    return _unite


def est_degre() -> bool:
    return _unite == DEGRE


def vers_unite(grades: float) -> float:
    """Convertit une valeur en grades vers l'unité d'affichage."""
    return grades * DEGRES_PAR_GRADE if est_degre() else float(grades)


def depuis_unite(valeur: float) -> float:
    """Convertit une valeur saisie (unité d'affichage) en grades."""
    return valeur / DEGRES_PAR_GRADE if est_degre() else float(valeur)


def suffixe() -> str:
    """« gr » ou « ° » (sans espace pour le degré)."""
    return "°" if est_degre() else " gr"


def nombre(grades: float) -> str:
    """Valeur seule, dans l'unité courante : « 100 » / « 90 » / « 22.5 »."""
    v = round(vers_unite(grades), 1)
    return f"{v:g}"


def valeur(grades: float) -> "int | float":
    """Valeur numérique pour une cellule de tableur : entier en grades
    (comme avant), décimale (≤ 1 chiffre) en degrés."""
    return int(grades) if not est_degre() else round(grades * DEGRES_PAR_GRADE, 1)


def titre_colonne() -> str:
    """En-tête de colonne d'export : « Grade (gr) » / « Angle (°) »."""
    return "Angle (°)" if est_degre() else "Grade (gr)"


def fmt(grades: float) -> str:
    """Valeur + unité : « 100 gr » / « 90° »."""
    return nombre(grades) + suffixe()


def pas_saisie() -> float:
    """Pas de saisie d'un angle dans l'unité courante (25 gr = 22,5°)."""
    return vers_unite(25)


def parse(texte: str) -> "float | None":
    """Lit un angle saisi/affiché dans l'unité courante ; renvoie des
    **grades**. Accepte `,` ou `.`, un suffixe « gr » ou « ° » (le suffixe
    présent prime sur l'unité courante : « 90° » vaut 100 gr même en mode
    grades). `None` si illisible."""
    t = (texte or "").strip().replace(",", ".")
    if not t:
        return None
    en_degres = est_degre()
    if t.endswith("°"):
        en_degres, t = True, t[:-1]
    elif t.lower().endswith("gr"):
        en_degres, t = False, t[:-2]
    try:
        v = float(t.strip())
    except ValueError:
        return None
    return v / DEGRES_PAR_GRADE if en_degres else v
