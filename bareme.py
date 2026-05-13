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

PORTS_ARBRE = ["libre", "semi-libre", "architecturé", "traumatique"]

# Groupes de barèmes PRBS (Silvavenir) :
#   - libre + semi-libre :        Vert > 30 %, Orange 15-30 %, Rouge < 15 %
#   - architecturé + traumatique : Vert > 20 %, Orange 10-20 %, Rouge < 10 %
PORTS_GROUPE_LIBRE = ("libre", "semi-libre")
PORTS_GROUPE_STRICT = ("architecturé", "traumatique")


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
    - libre / semi-libre :         Vert > 30 %, Orange 15-30 %, Rouge < 15 %
    - architecturé / traumatique : Vert > 20 %, Orange 10-20 %, Rouge < 10 %

    Convention de bornes : seuil haut strict (`>`), seuil bas inclusif
    (`>=`). Donc pile 30 % en port libre est Orange, pile 15 % est
    Orange, 14,9 % est Rouge.

    Renvoie le label de classe (`Vert`, `Orange` ou `Rouge`). La couleur
    hexa associée est une convention de présentation et vit côté UI.
    """
    p = port_arbre.lower().strip()
    seuils = (0.20, 0.10) if p in PORTS_GROUPE_STRICT else (0.30, 0.15)
    if ratio_tR > seuils[0]:
        return CLASSE_VERT
    elif ratio_tR >= seuils[1]:
        return CLASSE_ORANGE
    else:
        return CLASSE_ROUGE
