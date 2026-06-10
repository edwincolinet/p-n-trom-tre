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

from model import Arbre, Brin, Contrefort, DegradationExterne, Sondage

SCENARIOS = ("nu", "avec_ecorce", "contreforts",
             "degradation_sur_contrefort", "ovale", "cepee",
             "cepee_rotation")


def build_arbre(scenario: str) -> Arbre:
    """Construit l'`Arbre` pour le scénario nommé.

    Référence partagée par les tests golden : si la définition change
    ici, les fixtures PIL ET Tk doivent être régénérées.
    """
    if scenario == "nu":
        a = Arbre(numero_arbre="1", essence="Platane", port_arbre="libre")
        a.rayon_tronc_cm = 20.0
        return a

    if scenario == "avec_ecorce":
        a = Arbre(numero_arbre="2", essence="Chêne", port_arbre="libre",
                  meche_cm=40.0)
        a.rayon_tronc_cm = 20.0
        a.epaisseur_ecorce_cm = 1.5
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=15.0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(numero=2, grade=200,
                                    bois_sain_cm=12.0, bois_altere_cm=8.0))
        return a

    if scenario == "contreforts":
        a = Arbre(numero_arbre="3", essence="Hêtre", port_arbre="libre")
        a.rayon_tronc_cm = 20.0
        a.epaisseur_ecorce_cm = 1.0
        a.contreforts.append(Contrefort(numero=1, grade_centre=75,
                                          largeur_grades=50,
                                          longueur_cm=8.0))
        a.contreforts.append(Contrefort(numero=2, grade_centre=100,
                                          largeur_grades=50,
                                          longueur_cm=10.0))
        return a

    if scenario == "degradation_sur_contrefort":
        a = Arbre(numero_arbre="4", essence="Frêne", port_arbre="semi-libre")
        a.rayon_tronc_cm = 20.0
        a.epaisseur_ecorce_cm = 1.0
        a.contreforts.append(Contrefort(numero=1, grade_centre=100,
                                          largeur_grades=100,
                                          longueur_cm=10.0))
        a.degradations_externes.append(
            DegradationExterne(numero=1, grade_debut=75, grade_fin=125,
                                profondeur_cm=4.0))
        return a

    if scenario == "ovale":
        # Section elliptique : grand axe N-S (demi = 30), petit axe E-O
        # (demi = 18). Exerce les chemins ovales de TOUTES les couches :
        # bois, écorce, cernes, ticks, cardinales, contrefort sur ellipse,
        # pastilles de sondage rapportées au rayon local.
        a = Arbre(numero_arbre="5", essence="Peuplier", port_arbre="libre")
        a.rayon_tronc_cm = 30.0
        a.rayon_petit_axe_cm = 18.0
        a.orientation_grade = 0
        a.epaisseur_ecorce_cm = 1.0
        # PRBS cohérente avec le rayon LOCAL (altéré = R_local − sain) :
        a.sondages.append(Sondage(numero=1, grade=0,
                                    bois_sain_cm=22.0, bois_altere_cm=8.0))
        a.sondages.append(Sondage(numero=2, grade=100,
                                    bois_sain_cm=10.0, bois_altere_cm=8.0))
        a.contreforts.append(Contrefort(numero=1, grade_centre=200,
                                          largeur_grades=75, longueur_cm=8.0))
        return a

    if scenario == "cepee":
        # Cépée à 2 brins : « a » circulaire centré, « b » ovale décalé à
        # l'Est. Exerce le cadrage multi-brins (`brins_layout`), la boussole
        # globale, les labels de brin, et un brin ovale + contrefort hors
        # centre. La géométrie/mesures vivent sur chaque `Brin` ; le port et
        # la mèche restent genet-level (partagés).
        return Arbre(
            numero_arbre="6", essence="Charme", port_arbre="libre",
            meche_cm=40.0,
            brins=[
                Brin(label="a", rayon_tronc_cm=16.0, epaisseur_ecorce_cm=1.0,
                     sondages=[
                         Sondage(numero=1, grade=0,
                                 bois_sain_cm=12.0, bois_altere_cm=4.0),
                         Sondage(numero=2, grade=200,
                                 bois_sain_cm=9.0, bois_altere_cm=7.0)]),
                Brin(label="b", pos_x_cm=48.0, pos_y_cm=0.0,
                     rayon_tronc_cm=18.0, rayon_petit_axe_cm=11.0,
                     orientation_grade=100, epaisseur_ecorce_cm=1.0,
                     sondages=[
                         Sondage(numero=1, grade=100,
                                 bois_sain_cm=8.0, bois_altere_cm=3.0)],
                     contreforts=[
                         Contrefort(numero=1, grade_centre=200,
                                    largeur_grades=75, longueur_cm=7.0)]),
            ])

    if scenario == "cepee_rotation":
        # Cépée à 2 brins avec ROTATION (`rotation_grades`) : « a » circulaire
        # pivoté de 50 gr (le cercle est invariant, mais cavité/sondages
        # pivotent), « b » ovale pivoté de 100 gr (la forme, le sondage et le
        # contrefort pivotent ensemble). Verrouille le rendu des brins pivotés
        # (Étape 4 — reliquat rotation).
        return Arbre(
            numero_arbre="7", essence="Frêne", port_arbre="libre",
            meche_cm=40.0,
            brins=[
                Brin(label="a", rayon_tronc_cm=16.0, epaisseur_ecorce_cm=1.0,
                     rotation_grades=50,
                     sondages=[
                         Sondage(numero=1, grade=0,
                                 bois_sain_cm=12.0, bois_altere_cm=4.0),
                         Sondage(numero=2, grade=200,
                                 bois_sain_cm=9.0, bois_altere_cm=7.0)]),
                Brin(label="b", pos_x_cm=48.0, pos_y_cm=0.0,
                     rayon_tronc_cm=18.0, rayon_petit_axe_cm=11.0,
                     orientation_grade=100, epaisseur_ecorce_cm=1.0,
                     rotation_grades=100,
                     sondages=[
                         Sondage(numero=1, grade=100,
                                 bois_sain_cm=8.0, bois_altere_cm=3.0)],
                     contreforts=[
                         Contrefort(numero=1, grade_centre=200,
                                    largeur_grades=75, longueur_cm=7.0)]),
            ])

    raise ValueError(f"scenario inconnu : {scenario!r}")
