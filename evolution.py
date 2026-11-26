"""Évolution d'un arbre entre campagnes de mesure : calculs purs.

Cœur de la refonte des comparaisons (`.claude/docs/comparaisons-plan.md`).
Deux réponses distinctes, jamais fusionnées :

- l'**état** à chaque date (t/R minimal, classe) ;
- la **dégradation** : a-t-elle progressé, où, de combien ?

La croissance de l'arbre n'est pas une évolution de la dégradation : la
progression se mesure dans un repère fixe (distance au centre du tronc),
sur le rayon de l'altération interne et le fond des dégradations externes
(`rayon − profondeur`). Hypothèse : croissance centrée.

Règles métier : seules les directions sondées aux deux dates concluent sur
l'altération interne ; aucune tolérance de mesure (trop variable) ; du bois
dégradé ne redevient pas sain (à vérifier) ; une dégradation externe
recouverte est un progrès ; des hauteurs de sondage différentes interdisent
de conclure.

Aucun texte destiné à l'utilisateur ici : des valeurs et des codes, que
l'interface et les exports mettent en mots.
"""

from __future__ import annotations

from dataclasses import replace
from enum import Enum
from typing import TYPE_CHECKING, List, NamedTuple, Optional, Sequence, Tuple

import angle_units
from diagnostic import (
    _synthesis_row_for_section,
    compute_alteration_par_grade,
    degradation_externe_par_grade,
    prbs_par_grade,
    rayon_par_grade,
)
from dialogs_shared import annees_entre, normaliser_date
from geometry import GRADES, WIND_LABELS

if TYPE_CHECKING:
    from model import Arbre, Brin, DegradationExterne

# Résolution d'affichage (0,1 cm) : en deçà, deux valeurs sont identiques.
# Ce n'est PAS une tolérance de mesure.
EPS_CM = 0.05

# Intervalle minimal (années) pour qu'un taux annualisé soit pertinent.
TAUX_ANNEES_MIN = 0.5


class Conclusion(Enum):
    """Réponse à « la dégradation a-t-elle progressé ? »."""
    PROGRESSION = "progression"
    A_VERIFIER = "a_verifier"          # bois dégradé redevenu sain
    NON_COMPARABLE = "non_comparable"  # hauteurs, référence ou rayon manquant
    NON_EVALUABLE = "non_evaluable"    # aucune direction sondée aux 2 dates
    RECOUVREMENT = "recouvrement"      # plaie externe recouverte : progrès
    STABLE = "stable"                  # pas de progression constatée


# Du plus préoccupant au plus rassurant : agrégat d'une cépée.
_PRIORITE = tuple(Conclusion)


class Alerte(Enum):
    HAUTEURS_DIFFERENTES = "hauteurs_differentes"
    BRIN_SANS_REFERENCE = "brin_sans_reference"
    BRIN_DISPARU = "brin_disparu"
    RAYON_MANQUANT = "rayon_manquant"
    DIAMETRE_EN_BAISSE = "diametre_en_baisse"
    CAVITE_EN_RECUL = "cavite_en_recul"
    EXTERNE_DISPARUE = "externe_disparue"
    VALEUR_RECONDUITE = "valeur_reconduite"
    DIRECTION_NON_RESONDEE = "direction_non_resondee"


class DirectionDelta(NamedTuple):
    """Évolution d'une direction entre deux campagnes (appariée par grade).
    `delta` = PRBS courante − PRBS de référence : il inclut la croissance et
    ne dit donc PAS à lui seul si la dégradation a progressé."""
    grade: int
    direction: str
    prbs_ref: float
    prbs_cur: float
    delta: float
    compart_ref: str
    compart_cur: str
    # Direction réellement sondée aux DEUX campagnes (sinon, au moins une
    # des deux PRBS est extrapolée).
    mesuree_2_dates: bool = False
    # Avancée de l'altération interne (rayon courant − référence, cm) ;
    # n'a de valeur de constat que si `mesuree_2_dates`.
    prog_interne: float = 0.0
    # Avancée du fond de la dégradation externe vers le centre (cm) ;
    # négatif = recouvrement par du bois neuf.
    prog_externe: float = 0.0
    # Dégradation externe en recul sans que le rayon ait augmenté.
    externe_disparue: bool = False
    # PRBS saisie identique aux deux dates alors que le rayon a changé.
    reconduite: bool = False
    # Variation du rayon local (cm).
    croissance: float = 0.0
    # Sondée à la référence mais pas à la date courante.
    non_resondee: bool = False
    # Altération (mesurée) ou dégradation externe : la direction est évaluée.
    evaluee: bool = False

    @property
    def progression(self) -> float:
        """Bois sain **constaté** perdu depuis la référence (cm, ≥ 0)."""
        interne = self.prog_interne if self.mesuree_2_dates else 0.0
        return max(0.0, interne) + max(0.0, self.prog_externe)

    @property
    def recouvrement(self) -> float:
        """Dégradation externe recouverte (cm, ≥ 0)."""
        if self.externe_disparue:
            return 0.0
        return max(0.0, -self.prog_externe)

    @property
    def cavite_en_recul(self) -> bool:
        return self.mesuree_2_dates and self.prog_interne < -EPS_CM

    @property
    def anomalie(self) -> bool:
        return self.cavite_en_recul or self.externe_disparue

    @property
    def compart_aggravee(self) -> bool:
        """Compartimentation perdue : active en référence → absente."""
        return self.compart_ref == "active" and self.compart_cur == "absente"


def comparer_directions(ref_b: "Brin", cur_b: "Brin") -> List[DirectionDelta]:
    """Les 16 directions d'un brin entre deux campagnes. Liste vide si l'un
    des rayons n'est pas renseigné."""
    if ref_b.rayon_tronc_cm <= 0 or cur_b.rayon_tronc_cm <= 0:
        return []
    ref_sond = {s.grade: s for s in ref_b.sondages}
    cur_sond = {s.grade: s for s in cur_b.sondages}
    prbs_r, prbs_c = prbs_par_grade(ref_b), prbs_par_grade(cur_b)
    ray_r, ray_c = rayon_par_grade(ref_b), rayon_par_grade(cur_b)
    alt_r = compute_alteration_par_grade(ref_b)
    alt_c = compute_alteration_par_grade(cur_b)
    ext_r = degradation_externe_par_grade(ref_b)
    ext_c = degradation_externe_par_grade(cur_b)

    out: List[DirectionDelta] = []
    for i, g in enumerate(GRADES):
        s_r, s_c = ref_sond.get(g), cur_sond.get(g)
        croissance = ray_c[i] - ray_r[i]
        # Dégradation externe : position de son fond depuis le centre.
        if ext_r[i] <= 0:
            prog_ext = ext_c[i]      # nouvelle (ou aucune)
        else:
            prog_ext = (ray_r[i] - ext_r[i]) - (ray_c[i] - ext_c[i])
        mesuree = s_r is not None and s_c is not None
        out.append(DirectionDelta(
            grade=g, direction=WIND_LABELS.get(g, angle_units.fmt(g)),
            prbs_ref=prbs_r[i], prbs_cur=prbs_c[i],
            delta=prbs_c[i] - prbs_r[i],
            compart_ref=s_r.compartimentation if s_r else "",
            compart_cur=s_c.compartimentation if s_c else "",
            mesuree_2_dates=mesuree,
            prog_interne=alt_c[i] - alt_r[i],
            prog_externe=prog_ext,
            externe_disparue=prog_ext < -EPS_CM and croissance <= EPS_CM,
            reconduite=(
                s_r is not None and s_c is not None
                and abs(croissance) > EPS_CM
                and abs(s_c.bois_sain_cm - s_r.bois_sain_cm) <= EPS_CM),
            croissance=croissance,
            non_resondee=s_r is not None and s_c is None,
            evaluee=mesuree or ext_r[i] > 0 or ext_c[i] > 0))
    return out


def hauteurs_incompatibles(
        reference: "Arbre", courant: "Arbre") -> Optional[Tuple[float, float]]:
    """(h réf, h courant) si les deux hauteurs de sondage sont renseignées
    et différentes, sinon `None` (une hauteur non renseignée, 0, ne permet
    pas d'affirmer qu'elles diffèrent)."""
    h_ref, h_cur = reference.hauteur_sondage_cm, courant.hauteur_sondage_cm
    if h_ref > 0 and h_cur > 0 and abs(h_ref - h_cur) > EPS_CM:
        return (h_ref, h_cur)
    return None


def conclure(directions: Sequence[DirectionDelta],
             refus: bool = False) -> Conclusion:
    """Conclusion sur la dégradation. `refus` : comparaison interdite."""
    if refus or not directions:
        return Conclusion.NON_COMPARABLE
    if any(d.progression > EPS_CM for d in directions):
        return Conclusion.PROGRESSION
    if not any(d.mesuree_2_dates for d in directions):
        return Conclusion.NON_EVALUABLE
    if any(d.anomalie for d in directions):
        return Conclusion.A_VERIFIER
    if any(d.recouvrement > EPS_CM for d in directions):
        return Conclusion.RECOUVREMENT
    return Conclusion.STABLE


def progression_moyenne(
        directions: Sequence[DirectionDelta]) -> Optional[float]:
    """Avancée moyenne de la dégradation sur les directions évaluées (cm)."""
    evaluees = [d for d in directions if d.evaluee]
    if not evaluees:
        return None
    return sum(d.progression for d in evaluees) / len(evaluees)


def taux_annuel(valeur_cm: Optional[float],
                annees: Optional[float]) -> Optional[float]:
    """cm/an, seulement si l'intervalle est assez long pour avoir un sens."""
    if valeur_cm is None or annees is None or annees < TAUX_ANNEES_MIN:
        return None
    return valeur_cm / annees


def degradations_reference_recalees(
        ref_b: "Brin", cur_b: "Brin") -> "List[DegradationExterne]":
    """Dégradations externes de référence replacées dans le repère fixe,
    pour le dessin : leur profondeur est mesurée depuis la surface de
    l'époque ; on y ajoute la croissance pour que le fond reste à la même
    distance du centre. Une dégradation limitée à l'écorce est laissée telle
    quelle. La référence n'est pas modifiée."""
    croissance = cur_b.rayon_tronc_cm - ref_b.rayon_tronc_cm
    out: "List[DegradationExterne]" = []
    for deg in ref_b.degradations_externes:
        if deg.profondeur_bois_cm(ref_b.ep_a_grade(deg.grade_debut)) > 0:
            deg = replace(deg, profondeur_cm=max(
                0.0, deg.profondeur_cm + croissance))
        out.append(deg)
    return out


# ----------------------------------------------------------------------
# Intervalle entre deux campagnes, puis suivi sur N campagnes
# ----------------------------------------------------------------------

class Campagne(NamedTuple):
    """Un relevé daté d'un arbre (JJ/MM/AAAA, `""` si inconnue)."""
    date: str
    arbre: "Arbre"


class Etat(NamedTuple):
    """État mécanique à une date. `classe`/`tR_min_pct` = `None` tant que le
    diagnostic n'est pas publiable (< 3 sondages)."""
    classe: Optional[str]
    tR_min_pct: Optional[float]


def etat_brin(brin: "Brin", port: str) -> Etat:
    row = _synthesis_row_for_section("", "", port, brin)
    if row.classe_globale is None:
        return Etat(None, None)
    return Etat(row.classe_globale, row.tR_min_pct)


class EvolutionBrin(NamedTuple):
    index_ref: Optional[int]
    index_cur: Optional[int]       # None : brin disparu depuis la référence
    directions: List[DirectionDelta]
    conclusion: Conclusion
    alertes: Tuple[Alerte, ...]
    etat_ref: Etat
    etat_cur: Etat
    progression_max: Optional[float]
    progression_moy: Optional[float]
    taux_cm_an: Optional[float]    # sur la progression moyenne


class Intervalle(NamedTuple):
    date_ref: str
    date_cur: str
    annees: Optional[float]
    brins: List[EvolutionBrin]
    conclusion: Conclusion
    hauteurs: Optional[Tuple[float, float]]   # renseigné si différentes


def appariement_par_defaut(reference: "Arbre",
                           courant: "Arbre") -> List[Optional[int]]:
    """Pour chaque brin courant, l'index du brin de référence.

    Même nombre de brins : appariement par rang. Sinon **aucun** : supprimer
    ou ajouter un brin décale rangs et libellés, un appariement deviné
    comparerait deux tiges différentes. L'appelant fournit alors le sien."""
    if len(reference.brins) == len(courant.brins):
        return list(range(len(courant.brins)))
    return [None] * len(courant.brins)


def _alertes(directions: Sequence[DirectionDelta]) -> List[Alerte]:
    tests = (
        (Alerte.DIAMETRE_EN_BAISSE, lambda d: d.croissance < -EPS_CM),
        (Alerte.CAVITE_EN_RECUL, lambda d: d.cavite_en_recul),
        (Alerte.EXTERNE_DISPARUE, lambda d: d.externe_disparue),
        (Alerte.VALEUR_RECONDUITE, lambda d: d.reconduite),
        (Alerte.DIRECTION_NON_RESONDEE, lambda d: d.non_resondee),
    )
    return [alerte for alerte, test in tests if any(map(test, directions))]


def _evolution_brin(reference: "Arbre", courant: "Arbre",
                    i_ref: Optional[int], i_cur: Optional[int],
                    annees: Optional[float], refus: bool) -> EvolutionBrin:
    ref_b = reference.brins[i_ref] if i_ref is not None else None
    cur_b = courant.brins[i_cur] if i_cur is not None else None
    directions: List[DirectionDelta] = []
    alertes: List[Alerte] = [Alerte.HAUTEURS_DIFFERENTES] if refus else []
    if ref_b is None:
        alertes.append(Alerte.BRIN_SANS_REFERENCE)
    elif cur_b is None:
        alertes.append(Alerte.BRIN_DISPARU)
    else:
        directions = comparer_directions(ref_b, cur_b)
        if not directions:
            alertes.append(Alerte.RAYON_MANQUANT)
    # Refus : aucune valeur d'évolution n'est restituée.
    if refus:
        directions = []
    else:
        alertes += _alertes(directions)
    moyenne = progression_moyenne(directions)
    maximum = max((d.progression for d in directions if d.evaluee),
                  default=None)
    vide = Etat(None, None)
    return EvolutionBrin(
        index_ref=i_ref, index_cur=i_cur, directions=directions,
        conclusion=conclure(directions, refus), alertes=tuple(alertes),
        etat_ref=(etat_brin(ref_b, reference.port_arbre)
                  if ref_b is not None else vide),
        etat_cur=(etat_brin(cur_b, courant.port_arbre)
                  if cur_b is not None else vide),
        progression_max=maximum, progression_moy=moyenne,
        taux_cm_an=taux_annuel(moyenne, annees))


def comparer_campagnes(
        reference: Campagne, courante: Campagne,
        appariement: Optional[Sequence[Optional[int]]] = None) -> Intervalle:
    """Évolution entre deux campagnes, brin par brin.

    `appariement[i]` = index du brin de référence du brin courant `i`
    (défaut : `appariement_par_defaut`). Les brins de référence non
    appariés sont rapportés comme disparus."""
    ref, cur = reference.arbre, courante.arbre
    if appariement is None:
        appariement = appariement_par_defaut(ref, cur)
    if len(appariement) != len(cur.brins):
        raise ValueError("appariement : une entrée par brin courant")
    utilises = [i for i in appariement if i is not None]
    if (len(set(utilises)) != len(utilises)
            or any(not 0 <= i < len(ref.brins) for i in utilises)):
        raise ValueError("appariement : index de référence invalide ou répété")

    annees = annees_entre(reference.date, courante.date)
    hauteurs = hauteurs_incompatibles(ref, cur)
    refus = hauteurs is not None
    brins = [_evolution_brin(ref, cur, i_ref, i_cur, annees, refus)
             for i_cur, i_ref in enumerate(appariement)]
    brins += [_evolution_brin(ref, cur, i_ref, None, annees, refus)
              for i_ref in range(len(ref.brins)) if i_ref not in utilises]
    return Intervalle(
        date_ref=reference.date, date_cur=courante.date, annees=annees,
        brins=brins,
        conclusion=min((b.conclusion for b in brins), key=_PRIORITE.index),
        hauteurs=hauteurs)


class Suivi(NamedTuple):
    """Histoire d'un arbre sur plusieurs campagnes."""
    campagnes: List[Campagne]            # ordre chronologique
    intervalles: List[Intervalle]        # entre campagnes consécutives
    # Première → dernière ; `None` avec moins de trois campagnes (ce serait
    # le seul intervalle).
    global_: Optional[Intervalle]


def _cle_date(date_normalisee: str) -> Tuple[int, int, int]:
    jour, mois, annee = (int(x) for x in date_normalisee.split("/"))
    return annee, mois, jour


def suivre(campagnes: Sequence[Campagne]) -> Suivi:
    """Met les campagnes en ordre chronologique et compare. Si une date
    manque ou est illisible, l'ordre fourni est conservé (on ne devine pas).
    L'appariement des brins est celui par défaut."""
    ordre = list(campagnes)
    datees = [(d, c) for c in ordre if (d := normaliser_date(c.date))]
    if len(datees) == len(ordre):
        ordre = [c for _d, c in sorted(datees, key=lambda x: _cle_date(x[0]))]
    intervalles = [comparer_campagnes(a, b) for a, b in zip(ordre, ordre[1:])]
    global_ = (comparer_campagnes(ordre[0], ordre[-1])
               if len(ordre) > 2 else None)
    return Suivi(ordre, intervalles, global_)
