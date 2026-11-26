"""Comparaison inter-missions (ré-inspection) : calculs purs.

Extrait de `diagnostic.py` (2026-08-25) : sous-domaine à part — la
comparaison de deux campagnes d'un même arbre — déjà séparé côté UI
(`comparaison.py`/`comparaison_render.py` existent), pas seulement côté
calcul. Dépend de `diagnostic.py` pour trois helpers réutilisés tels
quels (`prbs_par_grade`, `_synthesis_row_for_section`,
`_synthesis_genet_row`, `_GRAVITE_CLASSE`) — même principe que
`dialogs_saisie.py` import `_make_modal` depuis `dialogs.py`.

Toutes les fonctions exposées sont **pures**, comme dans `diagnostic.py`.

**Principe** : la croissance de l'arbre n'est pas une évolution de la
dégradation. La progression se mesure dans un repère fixe (distance au
centre du tronc) : rayon de l'altération interne, et fond des dégradations
externes (`rayon − profondeur`). Le t/R minimal décrit l'état mécanique,
à part. Aucune tolérance de mesure n'est supposée : les écarts sont
rapportés tels quels (au dixième de cm affiché).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, NamedTuple, Optional, Tuple

import angle_units
from diagnostic import (
    _GRAVITE_CLASSE,
    MissionSynthesisRow,
    _synthesis_genet_row,
    _synthesis_row_for_section,
    compute_alteration_par_grade,
    degradation_externe_par_grade,
    prbs_par_grade,
    rayon_par_grade,
)
from geometry import GRADES, WIND_LABELS

if TYPE_CHECKING:
    from model import Arbre, Brin  # noqa: F401


class ArbreCompareSummary(NamedTuple):
    """Résumé court d'un arbre pour la comparaison d'inspections
    (campagnes successives) — agrégat genet, règle de fiabilité respectée
    (`classe`/`tR_min_pct` = `None` si < 3 sondages ; pour une cépée,
    `tR_min_pct` est celui du pire brin)."""
    classe: Optional[str]
    tR_min_pct: Optional[float]
    n_sondees: int
    rayon_cm: float
    fiable: bool


def _tR_min_publie(row: MissionSynthesisRow) -> Optional[float]:
    """t/R minimal de la ligne de synthèse, masqué comme la classe quand le
    diagnostic n'est pas publiable (< 3 sondages)."""
    return row.tR_min_pct if row.classe_globale is not None else None


def arbre_compare_summary(arbre: "Arbre") -> ArbreCompareSummary:
    """Résumé court d'un arbre (réutilise la ligne de synthèse genet)."""
    if len(arbre.brins) <= 1:
        row = _synthesis_row_for_section(
            arbre.numero_arbre, arbre.essence, arbre.port_arbre,
            arbre.brin_courant)
    else:
        row = _synthesis_genet_row(arbre)
    return ArbreCompareSummary(
        classe=row.classe_globale, tR_min_pct=_tR_min_publie(row),
        n_sondees=row.n_sondees, rayon_cm=row.rayon_cm, fiable=row.fiable)


def evolution_classe(reference: Optional[str],
                     courant: Optional[str]) -> Optional[int]:
    """Compare deux classes globales (campagne de référence → courante) :
    `-1` amélioration, `0` stable, `+1` aggravation, `None` si l'une des
    deux classes n'est pas publiée. Sévérité Vert < Orange < Rouge."""
    if reference is None or courant is None:
        return None
    gr = _GRAVITE_CLASSE.get(reference, 0)
    gc = _GRAVITE_CLASSE.get(courant, 0)
    return (gc > gr) - (gc < gr)


def evolution_tr(detail: "ComparaisonDetail") -> Optional[int]:
    """Évolution du **t/R minimal** (référence → courant) : `+1` perte
    (le t/R baisse), `-1` gain, `0` stable, `None` si l'un des deux n'est
    pas publié. « Stable » = même t/R **au pourcentage affiché** (0,1 %) :
    deux arbres d'une même classe n'ont pas le même t/R, c'est donc lui
    — et non la classe — qui dit si l'arbre a perdu ou gagné de la paroi."""
    if detail.tR_min_ref is None or detail.tR_min_cur is None:
        return None
    ref = round(detail.tR_min_ref, 1)
    cur = round(detail.tR_min_cur, 1)
    return (cur < ref) - (cur > ref)


# Résolution d'affichage (0,1 cm) : en deçà, deux valeurs sont identiques.
# Ce n'est PAS une tolérance de mesure (trop variable pour être fixée).
_EPS_CM = 0.05

# Nombre de directions citées en toutes lettres dans le verdict.
_MAX_DIRECTIONS_CITEES = 6


def directions_en_progression(
        detail: "ComparaisonDetail") -> List["DirectionDelta"]:
    """Directions où la dégradation a **progressé** (du plus au moins).
    Vide si la comparaison est refusée (hauteurs de sondage différentes)."""
    if detail.hauteurs_incompatibles:
        return []
    return sorted((d for d in detail.directions if d.progression > _EPS_CM),
                  key=lambda d: -d.progression)


def directions_a_verifier(
        detail: "ComparaisonDetail") -> List["DirectionDelta"]:
    """Directions où du bois dégradé semble redevenu sain — impossible en
    principe : mesure, saisie ou diamètre à contrôler."""
    if detail.hauteurs_incompatibles:
        return []
    return [d for d in detail.directions if d.anomalie]


def directions_recouvertes(
        detail: "ComparaisonDetail") -> List["DirectionDelta"]:
    """Directions où une dégradation externe a été recouverte (progrès)."""
    if detail.hauteurs_incompatibles:
        return []
    return [d for d in detail.directions if d.recouvrement > _EPS_CM]


def progression_evaluable(detail: "ComparaisonDetail") -> bool:
    """Vrai s'il existe de quoi conclure : hauteurs identiques et au moins
    une direction sondée aux deux dates."""
    return (not detail.hauteurs_incompatibles and bool(detail.directions)
            and detail.n_mesurees_2_dates != 0)


def evolution_degradation(detail: "ComparaisonDetail") -> Optional[int]:
    """`+1` dégradation en progression, `-1` recouvrement seul (progrès),
    `0` pas de progression constatée, `None` pas de conclusion possible
    (non comparable, non évaluable ou écarts à vérifier)."""
    if directions_en_progression(detail):
        return 1
    if not progression_evaluable(detail) or directions_a_verifier(detail):
        return None
    return -1 if directions_recouvertes(detail) else 0


def _n_directions(n: int) -> str:
    return f"{n} direction{'s' if n > 1 else ''}"


def _liste(directions: List["DirectionDelta"]) -> str:
    noms = [d.direction for d in directions[:_MAX_DIRECTIONS_CITEES]]
    if len(directions) > _MAX_DIRECTIONS_CITEES:
        noms.append("…")
    return ", ".join(noms)


def _ligne_tr(detail: "ComparaisonDetail") -> str:
    ref, cur = detail.tR_min_ref, detail.tR_min_cur
    if ref is None or cur is None:
        return (f"t/R minimal non publié (classe réf. "
                f"{detail.classe_ref or 'non publié'}, courant "
                f"{detail.classe_cur or 'non publié'}).")
    delta = round(cur, 1) - round(ref, 1)
    if delta:
        return f"t/R minimal : {ref:.1f} % → {cur:.1f} % ({delta:+.1f} pts)."
    return f"t/R minimal : inchangé ({cur:.1f} %)."


def verdict_lignes(detail: "ComparaisonDetail") -> Tuple[str, str]:
    """Verdict en deux niveaux : un **titre** sur la progression de la
    dégradation (lisible d'un coup d'œil par le client) et une ligne de
    **détail** (t/R minimal = état mécanique, directions concernées).

    La croissance du tronc n'entre pas dans le titre : une cavité qui
    s'étend reste une progression même si la paroi, elle, s'épaissit."""
    if detail.hauteurs_incompatibles:
        h_ref, h_cur = detail.hauteurs_incompatibles
        return ("? NON COMPARABLE — hauteurs de sondage différentes",
                f"Sondage à {h_ref:g} cm (référence) et à {h_cur:g} cm "
                f"(courant) : aucune conclusion sur l'évolution.")
    if not detail.directions:
        return ("? NON COMPARABLE — mesures insuffisantes", _ligne_tr(detail))

    progression = directions_en_progression(detail)
    a_verifier = directions_a_verifier(detail)
    recouvertes = directions_recouvertes(detail)
    if progression:
        titre = (f"▲ DÉGRADATION EN PROGRESSION — "
                 f"{_n_directions(len(progression))}")
    elif not progression_evaluable(detail):
        titre = ("? PROGRESSION NON ÉVALUABLE — aucune direction sondée "
                 "aux deux dates")
    elif a_verifier:
        titre = (f"? À VÉRIFIER — bois dégradé en recul sur "
                 f"{_n_directions(len(a_verifier))}")
    elif recouvertes:
        titre = (f"✓ PROGRÈS — dégradation externe recouverte sur "
                 f"{_n_directions(len(recouvertes))}")
    else:
        titre = "= PAS DE PROGRESSION CONSTATÉE"

    parts = [_ligne_tr(detail)]
    if progression:
        pire = progression[0]
        parts.append(f"Progression la plus forte : {pire.direction} "
                     f"({pire.progression:+.1f} cm).")
    if a_verifier:
        parts.append(f"À vérifier (bois dégradé en recul) : "
                     f"{_liste(a_verifier)}.")
    if recouvertes:
        parts.append(f"Recouvrement : {_liste(recouvertes)}.")
    reconduites = [d for d in detail.directions if d.reconduite]
    if reconduites:
        parts.append(f"PRBS identique malgré un diamètre différent "
                     f"(re-mesurée ?) : {_liste(reconduites)}.")
    if detail.n_mesurees_2_dates is not None:
        parts.append(f"Sondées aux deux dates : "
                     f"{detail.n_mesurees_2_dates}/16 directions.")
    return titre, "   ".join(parts)


def verdict_evolution(detail: "ComparaisonDetail") -> str:
    """Verdict complet (titre + détail, sur deux lignes). Partagé par la
    fenêtre et l'export — cf. `verdict_lignes`."""
    return "\n".join(verdict_lignes(detail))


class DirectionDelta(NamedTuple):
    """Évolution d'une direction sondée dans les DEUX campagnes (appariée
    par grade). `delta` = PRBS courante − PRBS de référence (négatif = bois
    sain perdu = aggravation)."""
    grade: int
    direction: str
    prbs_ref: float
    prbs_cur: float
    delta: float
    compart_ref: str
    compart_cur: str
    # Direction réellement sondée aux DEUX campagnes (sinon, au moins une
    # des deux PRBS est extrapolée : l'écart peut être du bruit
    # d'interpolation plutôt qu'une évolution mesurée).
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
    def anomalie(self) -> bool:
        interne = self.mesuree_2_dates and self.prog_interne < -_EPS_CM
        return interne or self.externe_disparue

    @property
    def compart_aggravee(self) -> bool:
        """Compartimentation perdue : active en référence → absente."""
        return self.compart_ref == "active" and self.compart_cur == "absente"


# Intervalle minimal (années) pour qu'un taux annualisé soit pertinent.
# En dessous (ré-inspection rapprochée), `perte / annees` explose et n'a
# pas de sens — on n'affiche alors que la perte absolue par direction.
_TAUX_ANNEES_MIN = 0.5


class ComparaisonDetail(NamedTuple):
    """Comparaison chiffrée de deux inspections d'un même arbre (campagne
    de référence → courante). Fonction pure `comparaison_detaillee`.

    Les **16 directions** sont détaillées, mais seules celles **sondées aux
    deux dates** concluent sur l'altération interne (les dégradations
    externes, observées, comptent partout). `progression_moy` = avancée
    moyenne de la dégradation sur les directions évaluées (cm).
    `taux_cm_an` n'est calculé que si l'intervalle ≥ `_TAUX_ANNEES_MIN`
    (sinon `None` → non pertinent)."""
    annees: Optional[float]
    directions: List[DirectionDelta]
    progression_moy: Optional[float]
    taux_cm_an: Optional[float]
    pire: Optional[DirectionDelta]
    compart_aggravees: int
    compart_changees: int
    classe_ref: Optional[str]
    classe_cur: Optional[str]
    tR_min_ref: Optional[float]
    tR_min_cur: Optional[float]
    # Rayon du tronc (cm) de chaque campagne — un arbre croît en diamètre
    # avec le temps. Surfacé dans le tableau (ligne « Diamètre ») et déjà
    # pris en compte dans les calculs (chaque PRBS/t/R utilise SON rayon).
    rayon_ref: Optional[float] = None
    rayon_cur: Optional[float] = None
    # Nombre de directions (sur 16) sondées aux deux campagnes ; `None` =
    # non calculé. Les autres sont comparées sur des valeurs extrapolées.
    n_mesurees_2_dates: Optional[int] = None
    # (référence, courant) en cm si les hauteurs de sondage diffèrent :
    # la comparaison refuse alors de conclure.
    hauteurs_incompatibles: Optional[Tuple[float, float]] = None


def hauteurs_incompatibles(
        reference: "Arbre", courant: "Arbre") -> Optional[Tuple[float, float]]:
    """(h réf, h courant) si les deux hauteurs de sondage sont renseignées
    et différentes, sinon `None` (une hauteur non renseignée, 0, ne permet
    pas d'affirmer qu'elles diffèrent)."""
    h_ref, h_cur = reference.hauteur_sondage_cm, courant.hauteur_sondage_cm
    if h_ref > 0 and h_cur > 0 and abs(h_ref - h_cur) > _EPS_CM:
        return (h_ref, h_cur)
    return None


def _comparaison_core(ref_b: Optional["Brin"], cur_b: "Brin",
                      annees: Optional[float], s_ref: ArbreCompareSummary,
                      s_cur: ArbreCompareSummary,
                      hauteurs: Optional[Tuple[float, float]] = None
                      ) -> ComparaisonDetail:
    """Cœur de la comparaison sur **deux brins** (réf → courant) + des
    résumés (classe/t/R) déjà calculés au bon niveau (genet OU brin). Les
    16 directions sont comparées via la PRBS extrapolée. `ref_b=None` (pas
    d'homologue de référence) ⟹ directions vides, classe_ref = `None`."""
    ref_sond = ({s.grade: s for s in ref_b.sondages}
                if ref_b is not None else {})
    cur_sond = {s.grade: s for s in cur_b.sondages}

    directions: List[DirectionDelta] = []
    evaluees: List[DirectionDelta] = []
    if (ref_b is not None and ref_b.rayon_tronc_cm > 0
            and cur_b.rayon_tronc_cm > 0):
        prbs_r = prbs_par_grade(ref_b)   # PRBS extrapolée 16 dir.
        prbs_c = prbs_par_grade(cur_b)
        ray_r, ray_c = rayon_par_grade(ref_b), rayon_par_grade(cur_b)
        alt_r = compute_alteration_par_grade(ref_b)
        alt_c = compute_alteration_par_grade(cur_b)
        ext_r = degradation_externe_par_grade(ref_b)
        ext_c = degradation_externe_par_grade(cur_b)
        for i, g in enumerate(GRADES):
            s_r, s_c = ref_sond.get(g), cur_sond.get(g)
            croissance = ray_c[i] - ray_r[i]
            # Dégradation externe : position de son fond depuis le centre.
            if ext_r[i] <= 0:
                prog_ext = ext_c[i]      # nouvelle (ou aucune)
            else:
                prog_ext = (ray_r[i] - ext_r[i]) - (ray_c[i] - ext_c[i])
            disparue = prog_ext < -_EPS_CM and croissance <= _EPS_CM
            d = DirectionDelta(
                grade=g, direction=WIND_LABELS.get(g, angle_units.fmt(g)),
                prbs_ref=prbs_r[i], prbs_cur=prbs_c[i],
                delta=prbs_c[i] - prbs_r[i],
                compart_ref=s_r.compartimentation if s_r else "",
                compart_cur=s_c.compartimentation if s_c else "",
                mesuree_2_dates=s_r is not None and s_c is not None,
                prog_interne=alt_c[i] - alt_r[i],
                prog_externe=prog_ext, externe_disparue=disparue,
                reconduite=(s_r is not None and s_c is not None
                            and abs(croissance) > _EPS_CM
                            and abs(s_c.bois_sain_cm - s_r.bois_sain_cm)
                            <= _EPS_CM))
            directions.append(d)
            if d.mesuree_2_dates or ext_r[i] > 0 or ext_c[i] > 0:
                evaluees.append(d)

    n_mesurees = (sum(1 for d in directions if d.mesuree_2_dates)
                  if directions else None)
    progression_moy: Optional[float] = None
    pire: Optional[DirectionDelta] = None
    if evaluees and hauteurs is None:
        progression_moy = sum(d.progression for d in evaluees) / len(evaluees)
        pire_c = max(evaluees, key=lambda d: d.progression)
        if pire_c.progression > _EPS_CM:
            pire = pire_c

    taux_cm_an: Optional[float] = None
    if (progression_moy is not None and annees is not None
            and annees >= _TAUX_ANNEES_MIN):
        taux_cm_an = progression_moy / annees

    return ComparaisonDetail(
        annees=annees, directions=directions,
        progression_moy=progression_moy, taux_cm_an=taux_cm_an, pire=pire,
        compart_aggravees=(sum(1 for d in directions if d.compart_aggravee)
                           if hauteurs is None else 0),
        compart_changees=sum(1 for d in directions
                             if d.compart_ref != d.compart_cur),
        classe_ref=s_ref.classe, classe_cur=s_cur.classe,
        tR_min_ref=s_ref.tR_min_pct, tR_min_cur=s_cur.tR_min_pct,
        rayon_ref=(ref_b.rayon_tronc_cm if ref_b is not None
                   and ref_b.rayon_tronc_cm > 0 else None),
        rayon_cur=(cur_b.rayon_tronc_cm if cur_b.rayon_tronc_cm > 0 else None),
        n_mesurees_2_dates=n_mesurees,
        hauteurs_incompatibles=hauteurs)


def comparaison_detaillee(reference: "Arbre", courant: "Arbre",
                          annees: Optional[float]) -> ComparaisonDetail:
    """Comparaison chiffrée référence → courant au niveau **genet** (brin
    courant pour les directions, classe globale genet). Inchangé. Pour le
    détail **par brin** d'une cépée, voir `comparaison_par_brin`."""
    return _comparaison_core(
        reference.brin_courant, courant.brin_courant, annees,
        arbre_compare_summary(reference), arbre_compare_summary(courant),
        hauteurs_incompatibles(reference, courant))


def _brin_compare_summary(brin: "Brin", port: str) -> ArbreCompareSummary:
    """Résumé court (classe/t/R) calculé **au niveau d'un brin** (pas du
    genet) — pour la comparaison brin-à-brin d'une cépée."""
    row = _synthesis_row_for_section("", "", port, brin)
    return ArbreCompareSummary(
        classe=row.classe_globale, tR_min_pct=_tR_min_publie(row),
        n_sondees=row.n_sondees, rayon_cm=row.rayon_cm, fiable=row.fiable)


def comparaison_par_brin(reference: "Arbre", courant: "Arbre",
                         annees: Optional[float]
                         ) -> List[Tuple[str, "Brin", Optional["Brin"],
                                         ComparaisonDetail]]:
    """Comparaison **brin-à-brin** d'une cépée, appariée par **index/label**
    (a↔a, b↔b…). Un brin courant sans homologue de référence (mission de
    référence plus courte, ou brins ré-ordonnés) est comparé à `None` →
    directions vides, classe_ref `None` (jamais d'appariement décalé
    silencieux). La classe/t/R sont calculés AU NIVEAU DU BRIN. Renvoie
    `[(label, cur_brin, ref_brin|None, detail)]`, un tuple par brin courant."""
    out: List[Tuple[str, "Brin", Optional["Brin"], ComparaisonDetail]] = []
    for i, cur_b in enumerate(courant.brins):
        ref_b = reference.brins[i] if i < len(reference.brins) else None
        label = cur_b.label or chr(ord("a") + i)
        s_cur = _brin_compare_summary(cur_b, courant.port_arbre)
        s_ref = (_brin_compare_summary(ref_b, reference.port_arbre)
                 if ref_b is not None
                 else ArbreCompareSummary(None, None, 0, 0.0, False))
        out.append((label, cur_b, ref_b,
                    _comparaison_core(
                        ref_b, cur_b, annees, s_ref, s_cur,
                        hauteurs_incompatibles(reference, courant))))
    return out
