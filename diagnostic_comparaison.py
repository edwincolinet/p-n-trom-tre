"""Comparaison inter-missions (ré-inspection) : calculs purs.

Extrait de `diagnostic.py` (2026-08-25) : sous-domaine à part — la
comparaison de deux campagnes d'un même arbre — déjà séparé côté UI
(`comparaison.py`/`comparaison_render.py` existent), pas seulement côté
calcul. Dépend de `diagnostic.py` pour trois helpers réutilisés tels
quels (`prbs_par_grade`, `_synthesis_row_for_section`,
`_synthesis_genet_row`, `_GRAVITE_CLASSE`) — même principe que
`dialogs_saisie.py` import `_make_modal` depuis `dialogs.py`.

Toutes les fonctions exposées sont **pures**, comme dans `diagnostic.py`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List, NamedTuple, Optional, Tuple

from diagnostic import (
    _GRAVITE_CLASSE,
    _synthesis_genet_row,
    _synthesis_row_for_section,
    prbs_par_grade,
)
from geometry import DIRECTION_LABELS, GRADES

if TYPE_CHECKING:
    from model import Arbre, Brin  # noqa: F401


class ArbreCompareSummary(NamedTuple):
    """Résumé court d'un arbre pour la comparaison d'inspections
    (campagnes successives) — agrégat genet, règle de fiabilité respectée
    (`classe`/`tR_moyen_pct` = `None` si < 3 sondages ; `tR_moyen_pct`
    aussi `None` pour une cépée — la moyenne inter-brins n'a pas de sens)."""
    classe: Optional[str]
    tR_moyen_pct: Optional[float]
    n_sondees: int
    rayon_cm: float
    fiable: bool


def arbre_compare_summary(arbre: "Arbre") -> ArbreCompareSummary:
    """Résumé court d'un arbre (réutilise la ligne de synthèse genet)."""
    if len(arbre.brins) <= 1:
        row = _synthesis_row_for_section(
            arbre.numero_arbre, arbre.essence, arbre.port_arbre,
            arbre.brin_courant)
    else:
        row = _synthesis_genet_row(arbre)
    return ArbreCompareSummary(
        classe=row.classe_globale, tR_moyen_pct=row.tR_moyen_pct,
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


def verdict_evolution(detail: "ComparaisonDetail") -> str:
    """Phrase de verdict de la comparaison (classe + t/R moyen + taux de
    perte cm/an). Partagée par la fenêtre et l'export."""
    rc = detail.classe_ref or "non publié"
    cc = detail.classe_cur or "non publié"
    evo = evolution_classe(detail.classe_ref, detail.classe_cur)
    if evo is None:
        base = f"Évolution de classe non comparable (réf. {rc}, courant {cc})."
    elif evo > 0:
        base = f"⚠ Aggravation : classe {rc} → {cc}."
    elif evo < 0:
        base = f"✓ Amélioration : classe {rc} → {cc}."
    else:
        base = f"= Stable : classe {cc}."
    if detail.tR_moy_ref is not None and detail.tR_moy_cur is not None:
        delta = detail.tR_moy_cur - detail.tR_moy_ref
        fl = "↑" if delta > 0 else ("↓" if delta < 0 else "→")
        base += (f"   t/R moyen : {detail.tR_moy_ref:.1f} % → "
                 f"{detail.tR_moy_cur:.1f} % ({fl} {abs(delta):.1f} pts)")
    if detail.perte_moy_par_dir is not None and detail.perte_moy_par_dir > 0.05:
        base += (f"   Perte de bois sain : "
                 f"{detail.perte_moy_par_dir:.1f} cm/direction")
        if detail.taux_cm_an is not None:
            base += f" (≈ {detail.taux_cm_an:.2f} cm/an)"
        base += "."
    return base


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

    Les **16 directions** sont comparées via la PRBS **extrapolée**
    (`prbs_par_grade` : rayon − altération interne extrapolée − dégradation
    externe) → on exploite l'extrapolation au lieu de se limiter aux
    directions sondées. `perte_moy_par_dir` = bois sain perdu **moyen par
    direction** (cm, positif = perte). `taux_cm_an` n'est calculé que si
    l'intervalle ≥ `_TAUX_ANNEES_MIN` (sinon `None` → non pertinent)."""
    annees: Optional[float]
    directions: List[DirectionDelta]
    prbs_moy_ref: Optional[float]
    prbs_moy_cur: Optional[float]
    perte_moy_par_dir: Optional[float]
    taux_cm_an: Optional[float]
    pire: Optional[DirectionDelta]
    compart_aggravees: int
    compart_changees: int
    classe_ref: Optional[str]
    classe_cur: Optional[str]
    tR_moy_ref: Optional[float]
    tR_moy_cur: Optional[float]
    # Rayon du tronc (cm) de chaque campagne — un arbre croît en diamètre
    # avec le temps. Surfacé dans le tableau (ligne « Diamètre ») et déjà
    # pris en compte dans les calculs (chaque PRBS/t/R utilise SON rayon).
    rayon_ref: Optional[float] = None
    rayon_cur: Optional[float] = None


def _comparaison_core(ref_b: Optional["Brin"], cur_b: "Brin",
                      annees: Optional[float], s_ref: ArbreCompareSummary,
                      s_cur: ArbreCompareSummary) -> ComparaisonDetail:
    """Cœur de la comparaison sur **deux brins** (réf → courant) + des
    résumés (classe/t/R) déjà calculés au bon niveau (genet OU brin). Les
    16 directions sont comparées via la PRBS extrapolée. `ref_b=None` (pas
    d'homologue de référence) ⟹ directions vides, classe_ref = `None`."""
    ref_comp = ({s.grade: s.compartimentation for s in ref_b.sondages}
                if ref_b is not None else {})
    cur_comp = {s.grade: s.compartimentation for s in cur_b.sondages}

    directions: List[DirectionDelta] = []
    if (ref_b is not None and ref_b.rayon_tronc_cm > 0
            and cur_b.rayon_tronc_cm > 0):
        prbs_r = prbs_par_grade(ref_b)   # PRBS extrapolée 16 dir.
        prbs_c = prbs_par_grade(cur_b)
        for i, g in enumerate(GRADES):
            directions.append(DirectionDelta(
                grade=g, direction=DIRECTION_LABELS.get(g, f"{g} gr"),
                prbs_ref=prbs_r[i], prbs_cur=prbs_c[i],
                delta=prbs_c[i] - prbs_r[i],
                compart_ref=ref_comp.get(g, ""),
                compart_cur=cur_comp.get(g, "")))

    prbs_moy_ref: Optional[float] = None
    prbs_moy_cur: Optional[float] = None
    perte_moy: Optional[float] = None
    pire: Optional[DirectionDelta] = None
    if directions:
        n = len(directions)
        prbs_moy_ref = sum(d.prbs_ref for d in directions) / n
        prbs_moy_cur = sum(d.prbs_cur for d in directions) / n
        # Perte moyenne PAR DIRECTION (cm, positif = bois sain perdu).
        perte_moy = sum(d.prbs_ref - d.prbs_cur for d in directions) / n
        pire_c = min(directions, key=lambda d: d.delta)
        if pire_c.delta < 0:          # aggravation réelle → « pire » direction
            pire = pire_c

    taux_cm_an: Optional[float] = None
    if (perte_moy is not None and annees is not None
            and annees >= _TAUX_ANNEES_MIN):
        taux_cm_an = perte_moy / annees

    return ComparaisonDetail(
        annees=annees, directions=directions,
        prbs_moy_ref=prbs_moy_ref, prbs_moy_cur=prbs_moy_cur,
        perte_moy_par_dir=perte_moy, taux_cm_an=taux_cm_an, pire=pire,
        compart_aggravees=sum(1 for d in directions if d.compart_aggravee),
        compart_changees=sum(1 for d in directions
                             if d.compart_ref != d.compart_cur),
        classe_ref=s_ref.classe, classe_cur=s_cur.classe,
        tR_moy_ref=s_ref.tR_moyen_pct, tR_moy_cur=s_cur.tR_moyen_pct,
        rayon_ref=(ref_b.rayon_tronc_cm if ref_b is not None
                   and ref_b.rayon_tronc_cm > 0 else None),
        rayon_cur=(cur_b.rayon_tronc_cm if cur_b.rayon_tronc_cm > 0 else None))


def comparaison_detaillee(reference: "Arbre", courant: "Arbre",
                          annees: Optional[float]) -> ComparaisonDetail:
    """Comparaison chiffrée référence → courant au niveau **genet** (brin
    courant pour les directions, classe globale genet). Inchangé. Pour le
    détail **par brin** d'une cépée, voir `comparaison_par_brin`."""
    return _comparaison_core(
        reference.brin_courant, courant.brin_courant, annees,
        arbre_compare_summary(reference), arbre_compare_summary(courant))


def _brin_compare_summary(brin: "Brin", port: str) -> ArbreCompareSummary:
    """Résumé court (classe/t/R) calculé **au niveau d'un brin** (pas du
    genet) — pour la comparaison brin-à-brin d'une cépée."""
    row = _synthesis_row_for_section("", "", port, brin)
    return ArbreCompareSummary(
        classe=row.classe_globale, tR_moyen_pct=row.tR_moyen_pct,
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
                    _comparaison_core(ref_b, cur_b, annees, s_ref, s_cur)))
    return out
