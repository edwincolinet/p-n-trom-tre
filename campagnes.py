"""Historique des relevés d'un arbre (modèle) : archiver, importer une
ancienne mission, fournir la série à `evolution`. Pur, sans UI.

L'arbre d'une mission est le relevé **courant** ; ses relevés antérieurs
sont figés dans `Arbre.campagnes`.
"""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence

from dialogs_shared import normaliser_date
from evolution import Campagne, appariement_par_defaut
from model import Releve

if TYPE_CHECKING:
    from model import Arbre, Chantier


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
