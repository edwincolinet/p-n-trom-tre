"""
Barème métier Silvavenir : classification d'un sondage en
Vert / Orange / Rouge selon le ratio t/R et le port de l'arbre.

Module isolé de Tkinter, de PIL et de la géométrie pure. Ne contient
QUE la règle métier — la couleur hexa associée à chaque classe est
une convention de présentation et vit côté UI dans `palette.py`.
"""

from __future__ import annotations

# ----------------------------------------------------------------------
# Ports d'arbre + groupes de barème
# ----------------------------------------------------------------------

PORTS_ARBRE = ["libre", "semi-libre", "délaissé",
               "architecturé", "traumatique"]

# Groupes de barèmes PRBS :
#   - libre + semi-libre + délaissé : Vert > 30 %, Orange 15-30 %, Rouge < 15 %
#   - architecturé + traumatique :    Vert > 20 %, Orange 10-20 %, Rouge < 10 %
PORTS_GROUPE_LIBRE = ("libre", "semi-libre", "délaissé")
PORTS_GROUPE_STRICT = ("architecturé", "traumatique")

# ----------------------------------------------------------------------
# Seuils personnalisables (modifiés par set_seuils au démarrage)
# ----------------------------------------------------------------------

# Valeurs par défaut (ratios t/R, 0–1).
SEUILS_DEFAUT: dict[str, tuple[float, float]] = {
    "libre":  (0.30, 0.15),   # (seuil_vert, seuil_orange)
    "strict": (0.20, 0.10),
}

# Seuils courants (initialisés aux défauts, remplacés par set_seuils).
_seuils: dict[str, tuple[float, float]] = dict(SEUILS_DEFAUT)


def get_seuils() -> dict[str, tuple[float, float]]:
    """Seuils courants : {'libre': (seuil_vert, seuil_orange), 'strict': …}."""
    return dict(_seuils)


def set_seuils(libre: tuple[float, float],
               strict: tuple[float, float]) -> None:
    """Applique des seuils personnalisés (persistés par bareme_store)."""
    _seuils["libre"] = libre
    _seuils["strict"] = strict


def normaliser_port(value: object) -> str:
    """Normalise une valeur de port en sa forme canonique.

    - Strip + lower sur la chaîne d'entrée.
    - Si la valeur ne correspond à aucun port connu : renvoie la chaîne
      vide. Le caller (typiquement `Chantier.from_dict`) doit alors
      décider du fallback à appliquer.

    Sans cette normalisation, un port inattendu (faute de frappe dans
    un fichier édité à la main, ancien libellé non couvert par la
    migration) retomberait silencieusement dans la branche par défaut
    de `classer_prbs` (= groupe libre), faussant le diagnostic légal
    sans signal pour l'utilisateur.
    """
    if not isinstance(value, str):
        return ""
    p = value.lower().strip()
    return p if p in PORTS_ARBRE else ""


# ----------------------------------------------------------------------
# Labels de classe
# ----------------------------------------------------------------------
#
# Source unique des labels canoniques. La couche UI s'en sert comme clés
# du dict `COULEUR_CLASSE` (dans `palette.py`).

CLASSE_VERT = "Vert"
CLASSE_ORANGE = "Orange"
CLASSE_ROUGE = "Rouge"


# ----------------------------------------------------------------------
# Règle de classification
# ----------------------------------------------------------------------

def classer_prbs(ratio_tR: float, port_arbre: str) -> str:
    """Classe un sondage selon son ratio t/R et le port de l'arbre.

    Seuils Silvavenir :
    - libre / semi-libre / délaissé : Vert > 30 %, Orange 15-30 %, Rouge < 15 %
    - architecturé / traumatique :    Vert > 20 %, Orange 10-20 %, Rouge < 10 %

    Convention de bornes : seuil haut strict (`>`), seuil bas inclusif
    (`>=`). Donc pile 30 % en port libre est Orange, pile 15 % est
    Orange, 14,9 % est Rouge.

    Renvoie le label de classe (`Vert`, `Orange` ou `Rouge`). La couleur
    hexa associée est une convention de présentation et vit côté UI.
    """
    p = port_arbre.lower().strip()
    seuil_vert, seuil_orange = (
        _seuils["strict"] if p in PORTS_GROUPE_STRICT else _seuils["libre"])
    if ratio_tR > seuil_vert:
        return CLASSE_VERT
    elif ratio_tR >= seuil_orange:
        return CLASSE_ORANGE
    else:
        return CLASSE_ROUGE
