"""Scénarios d'arbre partagés entre les tests golden PIL et Tk.

Quatre cas canoniques qui couvrent le pipeline de rendu :

1. `nu`             — arbre brut sans écorce, sondage ni contrefort.
2. `avec_ecorce`    — épaisseur d'écorce + 2 sondages opposés.
3. `contreforts`    — 2 contreforts adjacents qui doivent fusionner en
                       une seule cloche (verrou anti-encoche en V).
4. `degradation_sur_contrefort` — dégradation externe qui traverse un
                       contrefort et doit y mordre.

Module privé (préfixe `_`) : pas destiné à être importé en dehors de
`tests/`.
"""

from __future__ import annotations

from model import Arbre, Contrefort, DegradationExterne, Sondage

SCENARIOS = ("nu", "avec_ecorce", "contreforts",
             "degradation_sur_contrefort")


def build_arbre(scenario: str) -> Arbre:
    """Construit l'`Arbre` pour le scénario nommé.

    Référence partagée par les tests golden : si la définition change
    ici, les fixtures PIL ET Tk doivent être régénérées.
    """
    if scenario == "nu":
        return Arbre(numero_arbre="1", essence="Platane",
                     rayon_tronc_cm=20.0, port_arbre="libre")

    if scenario == "avec_ecorce":
        a = Arbre(numero_arbre="2", essence="Chêne",
                  rayon_tronc_cm=20.0, port_arbre="libre",
                  epaisseur_ecorce_cm=1.5, meche_cm=40.0)
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(numero=2, grade=200,
                                    bois_sain_cm=12.0, bois_altere_cm=8.0))
        return a

    if scenario == "contreforts":
        a = Arbre(numero_arbre="3", essence="Hêtre",
                  rayon_tronc_cm=20.0, port_arbre="libre",
                  epaisseur_ecorce_cm=1.0)
        a.contreforts.append(Contrefort(numero=1, grade_centre=75,
                                          largeur_grades=50,
                                          longueur_cm=8.0))
        a.contreforts.append(Contrefort(numero=2, grade_centre=100,
                                          largeur_grades=50,
                                          longueur_cm=10.0))
        return a

    if scenario == "degradation_sur_contrefort":
        a = Arbre(numero_arbre="4", essence="Frêne",
                  rayon_tronc_cm=20.0, port_arbre="semi-libre",
                  epaisseur_ecorce_cm=1.0)
        a.contreforts.append(Contrefort(numero=1, grade_centre=100,
                                          largeur_grades=100,
                                          longueur_cm=10.0))
        a.degradations_externes.append(
            DegradationExterne(numero=1, grade_debut=75, grade_fin=125,
                                profondeur_cm=4.0))
        return a

    raise ValueError(f"scenario inconnu : {scenario!r}")
