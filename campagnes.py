"""Historique des relevés d'un arbre (modèle) : archiver, importer une
ancienne mission, fournir la série à `evolution`. Pur, sans UI.

L'arbre d'une mission est le relevé **courant** ; ses relevés antérieurs
sont figés dans `Arbre.campagnes`.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Dict, List, NamedTuple, Optional, Sequence

from dialogs_shared import annees_entre, normaliser_date
from evolution import (
    Campagne,
    Conclusion,
    appariement_par_defaut,
    comparer_campagnes,
    hauteurs_incompatibles,
)
from geometry import GRADES
from model import Releve

if TYPE_CHECKING:
    from model import Arbre, Brin, Chantier, DegradationExterne


def _cle(releve: Releve) -> "tuple[int, str]":
    """Tri chronologique ; les dates illisibles d'abord, dans leur ordre."""
    d = normaliser_date(releve.date)
    if not d:
        return (0, "")
    jour, mois, annee = d.split("/")
    return (1, f"{annee}{mois}{jour}")


def _figer(arbre: "Arbre") -> "Arbre":
    """Copie indépendante de l'arbre, mêmes identifiants, sans historique."""
    historique, arbre.campagnes = arbre.campagnes, []
    try:
        return copy.deepcopy(arbre)
    finally:
        arbre.campagnes = historique


def _ajouter(arbre: "Arbre", releves: Sequence[Releve]) -> None:
    """Insère des relevés, tous ou aucun : deux relevés d'une même date
    seraient indiscernables."""
    dates = [normaliser_date(r.date) for r in arbre.campagnes]
    for r in releves:
        d = normaliser_date(r.date)
        if d and d in dates:
            raise ValueError(f"Un relevé du {d} existe déjà pour cet arbre.")
        dates.append(d)
    arbre.campagnes = sorted([*arbre.campagnes, *releves], key=_cle)


def archiver(arbre: "Arbre", date: str, operateur: str = "",
             bareme_seuils: "Optional[List[Dict[str, Any]]]" = None
             ) -> Releve:
    """Fige l'état courant de l'arbre dans son historique. L'arbre courant
    n'est pas modifié."""
    releve = Releve(date=date, operateur=operateur,
                    bareme_seuils=copy.deepcopy(bareme_seuils or []),
                    arbre=_figer(arbre))
    _ajouter(arbre, [releve])
    return releve


def proposer_appariement(courante: "Chantier",
                         ancienne: "Chantier") -> List[Optional[int]]:
    """Pour chaque arbre de la mission courante, l'index de son homologue
    dans l'ancienne (`None` sinon) : par identifiant, puis par numéro s'il
    est unique des deux côtés. Proposition à valider par l'expert."""
    par_id = {a.id: i for i, a in enumerate(ancienne.arbres)}
    out: List[Optional[int]] = [par_id.get(a.id) for a in courante.arbres]
    pris = {i for i in out if i is not None}

    def numeros(arbres: "Sequence[Arbre]") -> List[str]:
        return [a.numero_arbre.strip().lower() for a in arbres]

    cur, anc = numeros(courante.arbres), numeros(ancienne.arbres)
    for k, numero in enumerate(cur):
        if (out[k] is None and numero and cur.count(numero) == 1
                and anc.count(numero) == 1 and anc.index(numero) not in pris):
            out[k] = anc.index(numero)
    return out


def importer(arbre: "Arbre", ancien: "Arbre", date: str,
             operateur: str = "",
             bareme_seuils: "Optional[List[Dict[str, Any]]]" = None,
             appariement_brins: Optional[Sequence[Optional[int]]] = None
             ) -> None:
    """Rattache à `arbre` un relevé issu d'une ancienne mission, avec
    l'historique que cet ancien arbre portait déjà. Les identifiants sont
    alignés sur ceux de `arbre` ; `ancien` n'est pas modifié.

    `appariement_brins[i]` = index du brin ancien correspondant au brin
    courant `i` (défaut : `evolution.appariement_par_defaut`). Lève
    `ValueError` sans rien modifier si une date existe déjà."""
    if appariement_brins is None:
        appariement_brins = appariement_par_defaut(ancien, arbre)
    utilises = [i for i in appariement_brins if i is not None]
    if (len(appariement_brins) != len(arbre.brins)
            or len(set(utilises)) != len(utilises)
            or any(not 0 <= i < len(ancien.brins) for i in utilises)):
        raise ValueError("Appariement des brins invalide.")
    # Identifiant ancien → identifiant courant.
    alias = {ancien.brins[i_old].id: arbre.brins[i_cur].id
             for i_cur, i_old in enumerate(appariement_brins)
             if i_old is not None}
    courants = {b.id for b in arbre.brins}

    releves = [Releve(date, operateur, copy.deepcopy(bareme_seuils or []),
                      _figer(ancien))]
    releves += copy.deepcopy(ancien.campagnes)
    for r in releves:
        r.arbre.id = arbre.id
        for b in r.arbre.brins:
            if b.id in alias:
                b.id = alias[b.id]
            elif b.id in courants:
                # Appariement refusé par l'expert : ne pas relier par l'id.
                b.id = f"{b.id}-ancien"
    _ajouter(arbre, releves)


def serie(arbre: "Arbre", date_courante: str) -> List[Campagne]:
    """Relevés archivés puis relevé courant, pour `evolution.suivre`."""
    passes = [Campagne(r.date, r.arbre) for r in arbre.campagnes]
    return [*passes, Campagne(date_courante, arbre)]


class Precedent(NamedTuple):
    """Le dernier relevé archivé d'une tige, pour guider la saisie."""
    date: str
    brin: "Brin"
    hauteurs: "Optional[tuple[float, float]]"   # renseigné si différentes


def precedent(arbre: "Arbre", brin: "Brin") -> Optional[Precedent]:
    """Relevé le plus récent où figure ce brin (par identifiant)."""
    for releve in reversed(arbre.campagnes):
        for ancien in releve.arbre.brins:
            if ancien.id == brin.id:
                return Precedent(releve.date, ancien,
                                 hauteurs_incompatibles(releve.arbre, arbre))
    return None


def _grades_communs(a: "DegradationExterne",
                    b: "DegradationExterne") -> List[int]:
    return [g for g in GRADES if a.couvre_grade(g) and b.couvre_grade(g)]


def cal_depuis(ancien: "Brin", brin: "Brin",
               deg: "DegradationExterne") -> Optional[float]:
    """Bois formé au-dessus de la plaie `deg` depuis le relevé `ancien`, où
    elle était encore ouverte : croissance moyenne du rayon sur les
    directions communes. `None` si `ancien` ne la montre pas ouverte."""
    grades = sorted({g for old in ancien.degradations_externes
                     if not old.recouverte
                     for g in _grades_communs(old, deg)})
    if not grades:
        return None
    ecart = sum(brin.rayon_a_grade(g) - ancien.rayon_a_grade(g)
                for g in grades) / len(grades)
    return max(0.0, ecart)


def cals(arbre: "Arbre", brin: "Brin") -> Dict[int, float]:
    """Pour le dessin : épaisseur de cal (cm) au-dessus de chaque
    dégradation recouverte de `brin`, indexée par son rang dans la liste.

    Le cal n'est pas mesuré : il est déduit de la croissance depuis le
    dernier relevé où la plaie était ouverte. Sans un tel relevé, absent du
    résultat : la plaie est dessinée à la surface, sans épaisseur inventée."""
    out: Dict[int, float] = {}
    for i, deg in enumerate(brin.degradations_externes):
        if not deg.recouverte:
            continue
        for releve in reversed(arbre.campagnes):
            ancien = next((b for b in releve.arbre.brins if b.id == brin.id),
                          None)
            if ancien is None:
                continue
            cal = cal_depuis(ancien, brin, deg)
            if cal is not None:
                out[i] = cal
                break
    return out


def _a_des_mesures(arbre: "Arbre") -> bool:
    return any(b.sondages or b.degradations_externes or b.contreforts
               or b.diametres_locaux for b in arbre.brins)


def _reprendre_releve(arbre: "Arbre") -> None:
    """Prépare la visite suivante : tout reste prérempli, mais les sondages
    sont marqués « à confirmer »."""
    for b in arbre.brins:
        for sondage in b.sondages:
            sondage.a_confirmer = True


def nouvelle_campagne(chantier: "Chantier", date: str,
                      bareme_seuils: "Optional[List[Dict[str, Any]]]" = None
                      ) -> int:
    """Archive le relevé actuel de chaque arbre mesuré, puis prépare la
    saisie à la date `date`. Renvoie le nombre d'arbres archivés.

    Un sondage resté « à confirmer » n'a pas été mesuré à la date archivée :
    il est absent de l'archive (et reste proposé pour la visite suivante).

    Lève `ValueError` **sans rien modifier** si les dates ne permettent pas
    d'ordonner les relevés ou s'il n'y a rien à archiver."""
    ancienne = normaliser_date(chantier.date_releve)
    nouvelle = normaliser_date(date)
    if not ancienne:
        raise ValueError("La date du relevé actuel n'est pas renseignée.")
    if not nouvelle:
        raise ValueError("La date de la nouvelle campagne est illisible.")
    ecart = annees_entre(ancienne, nouvelle)
    if ecart is None or ecart <= 0:
        raise ValueError(f"La nouvelle campagne doit être postérieure au "
                         f"{ancienne}.")
    arbres = [a for a in chantier.arbres if _a_des_mesures(a)]
    if not arbres:
        raise ValueError("Aucun arbre ne porte de mesures à archiver.")
    for a in arbres:
        if any(normaliser_date(r.date) == ancienne for r in a.campagnes):
            raise ValueError(f"Arbre n° {a.numero_arbre} : un relevé du "
                             f"{ancienne} est déjà archivé.")
    for a in arbres:
        releve = archiver(a, ancienne, chantier.operateur, bareme_seuils)
        for b in releve.arbre.brins:
            b.sondages = [x for x in b.sondages if not x.a_confirmer]
            b.renumeroter_sondages()
        _reprendre_releve(a)
    chantier.date_releve = nouvelle
    return len(arbres)


def en_progression(arbre: "Arbre", date_courante: str) -> bool:
    """La dégradation a-t-elle progressé depuis le dernier relevé archivé ?"""
    if not arbre.campagnes:
        return False
    dernier = arbre.campagnes[-1]
    return comparer_campagnes(
        Campagne(dernier.date, dernier.arbre),
        Campagne(date_courante, arbre)).conclusion is Conclusion.PROGRESSION
