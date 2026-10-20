"""
Barème de classification : classification d'un sondage en
Vert / Orange / Rouge selon le ratio t/R et le port de l'arbre.

Module isolé de Tkinter, de PIL et de la géométrie pure. Ne contient
QUE la règle métier — la couleur hexa associée à chaque classe est
une convention de présentation et vit côté UI dans `palette.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

# ----------------------------------------------------------------------
# Ports d'arbre + groupes de barème
# ----------------------------------------------------------------------

PORTS_ARBRE = ["libre", "semi-libre", "délaissé",
               "architecturé", "traumatique"]

# Partition par défaut (2 groupes) :
#   - libre + semi-libre + délaissé : Vert > 30 %, Orange 15-30 %, Rouge < 15 %
#   - architecturé + traumatique :    Vert > 20 %, Orange 10-20 %, Rouge < 10 %
# Conservés comme constantes nommées (définissent GROUPES_DEFAUT ci-dessous
# et sont référencés par quelques docstrings/tests historiques).
PORTS_GROUPE_LIBRE = ("libre", "semi-libre", "délaissé")
PORTS_GROUPE_STRICT = ("architecturé", "traumatique")


# ----------------------------------------------------------------------
# Groupes de barème : un groupe = un sous-ensemble de PORTS_ARBRE + ses
# seuils t/R propres. Un « port individuel » n'est qu'un groupe à un seul
# port — aucune distinction de code entre les deux cas. Composition et
# nombre de groupes librement réglables par l'expert (Affichage →
# Barème…, `dialogs_settings.ask_bareme_settings`) ; la partition
# ci-dessous est la valeur par défaut de tout nouveau poste.
# ----------------------------------------------------------------------

@dataclass
class GroupeBareme:
    """Un groupe de ports d'arbre partageant les mêmes seuils t/R."""
    nom: str
    ports: Tuple[str, ...]
    seuil_vert: float
    seuil_orange: float


GROUPES_DEFAUT: Tuple[GroupeBareme, ...] = (
    GroupeBareme("Libre / Semi-libre / Délaissé", PORTS_GROUPE_LIBRE,
                 0.30, 0.15),
    GroupeBareme("Architecturé / Traumatique", PORTS_GROUPE_STRICT,
                 0.20, 0.10),
)

# Groupes courants (initialisés aux défauts, remplacés par set_groupes).
_groupes: List[GroupeBareme] = list(GROUPES_DEFAUT)

_IDX_PORT = {p: i for i, p in enumerate(PORTS_ARBRE)}


def _canonise(groupes: Sequence[GroupeBareme]) -> List[GroupeBareme]:
    """Ordre stable : ports de chaque groupe triés sur leur index dans
    `PORTS_ARBRE`, groupes triés sur le premier de ces index.

    Rend `seuils_personnalises()` fiable (comparaison structurelle) quel
    que soit l'ordre de saisie dans l'éditeur."""
    ordered = [GroupeBareme(g.nom,
                            tuple(sorted(g.ports, key=lambda p: _IDX_PORT[p])),
                            g.seuil_vert, g.seuil_orange)
              for g in groupes if g.ports]
    ordered.sort(key=lambda g: _IDX_PORT[g.ports[0]])
    return ordered


def get_groupes() -> List[GroupeBareme]:
    """Groupes de barème courants (copie)."""
    return list(_groupes)


def set_groupes(groupes: Sequence[GroupeBareme]) -> None:
    """Applique des groupes personnalisés (persistés par `bareme_store`)."""
    global _groupes
    _groupes = _canonise(groupes)


def groupe_pour_port(port_arbre: str) -> Optional[GroupeBareme]:
    """Groupe courant contenant ce port (normalisé), sinon `None`."""
    p = port_arbre.lower().strip()
    for g in _groupes:
        if p in g.ports:
            return g
    return None


def seuils_personnalises() -> bool:
    """Vrai si les groupes courants diffèrent de la partition par défaut."""
    return get_groupes() != list(GROUPES_DEFAUT)


def groupes_vers_brut(groupes: Sequence[GroupeBareme]) -> List[Dict[str, Any]]:
    """Sérialise des groupes vers la forme brute JSON (liste de dicts)."""
    return [{"nom": g.nom, "ports": list(g.ports),
             "vert": g.seuil_vert, "orange": g.seuil_orange}
            for g in groupes]


def _groupes_defaut_pour_ports(ports: Sequence[str]) -> List[GroupeBareme]:
    """Secours pour des ports absents d'une config brute incomplète : un
    groupe par port manquant, avec les seuils par défaut de CE port."""
    out = []
    for p in ports:
        defaut = next(g for g in GROUPES_DEFAUT if p in g.ports)
        out.append(GroupeBareme(p, (p,), defaut.seuil_vert, defaut.seuil_orange))
    return out


def seuils_depuis_brut(brut: object) -> List[GroupeBareme]:
    """Reconstruit des groupes depuis la forme sérialisée JSON.

    Tolérant : toute entrée absente ou illisible retombe sur le défaut,
    pour qu'un fichier abîmé n'empêche jamais l'ouverture d'un poste ou
    d'une mission. Gère aussi la migration depuis l'ancien format à 2
    groupes fixes (`{"libre": [vert, orange], "strict": [vert, orange]}`,
    présent sur tous les postes et missions antérieurs à cette
    fonctionnalité).
    """
    # Nouveau format : liste de groupes bruts.
    if isinstance(brut, list):
        groupes: List[GroupeBareme] = []
        ports_vus: set[str] = set()
        for item in brut:
            if not isinstance(item, dict):
                continue
            nom = item.get("nom")
            ports_brut = item.get("ports")
            if (not isinstance(nom, str) or not nom.strip()
                    or not isinstance(ports_brut, list)):
                continue
            ports = tuple(p for p in ports_brut
                         if isinstance(p, str) and p in PORTS_ARBRE
                         and p not in ports_vus)
            if not ports:
                continue
            try:
                vert = float(item.get("vert"))  # type: ignore[arg-type]
                orange = float(item.get("orange"))  # type: ignore[arg-type]
            except (TypeError, ValueError):
                continue
            if not (0 < orange < vert <= 1):
                continue
            ports_vus.update(ports)
            groupes.append(GroupeBareme(nom.strip(), ports,
                                        round(vert, 4), round(orange, 4)))
        # Au moins un groupe exploité : complète les ports manquants par un
        # secours, plutôt que de considérer toute la liste illisible (une
        # liste VIDE, elle, n'a rien à compléter — tombe au fallback final).
        if groupes:
            manquants = [p for p in PORTS_ARBRE if p not in ports_vus]
            if manquants:
                groupes.extend(_groupes_defaut_pour_ports(manquants))
            return _canonise(groupes)
    # Ancien format (2 groupes fixes nommés) : migration transparente.
    if isinstance(brut, dict) and ("libre" in brut or "strict" in brut):
        out = []
        for cle, defaut in (("libre", GROUPES_DEFAUT[0]),
                            ("strict", GROUPES_DEFAUT[1])):
            paire = brut.get(cle)
            migre = None
            if isinstance(paire, (list, tuple)) and len(paire) == 2:
                try:
                    vert, orange = float(paire[0]), float(paire[1])
                    if 0 < orange < vert <= 1:
                        migre = GroupeBareme(defaut.nom, defaut.ports,
                                             round(vert, 4), round(orange, 4))
                except (TypeError, ValueError):
                    pass
            out.append(migre if migre is not None else defaut)
        return _canonise(out)
    # Rien d'exploitable.
    return list(GROUPES_DEFAUT)


def description_seuils(groupes: "Optional[Sequence[GroupeBareme]]" = None
                       ) -> str:
    """Phrase courte décrivant les seuils, pour les **livrables**.

    Le barème est réglable par poste (`bareme_store`, dans
    `~/.penetrometre/`) : deux opérateurs aux réglages différents
    classent les mêmes mesures en Vert chez l'un et Orange chez
    l'autre. Tant que le document remis au client ne dit pas quels
    seuils ont servi, son diagnostic n'est pas reproductible — c'est un
    problème de traçabilité, pas de présentation. D'où cette ligne,
    présente sur la fiche PDF et dans les exports tableur.

    `groupes` : jeu à décrire (défaut : celui en vigueur). Passer le jeu
    lu dans un fichier de mission permet de décrire le barème
    **historique** d'un relevé plutôt que celui du poste courant.
    """
    gs = list(groupes) if groupes is not None else get_groupes()

    def pct(x: float) -> str:
        return f"{x * 100:.4g} %"

    return "  ·  ".join(
        f"{g.nom} : vert > {pct(g.seuil_vert)}, orange ≥ {pct(g.seuil_orange)}"
        for g in gs)


def description_seuils_mission(chantier: object) -> str:
    """Description du barème d'une mission, pour un livrable.

    Utilise les seuils **enregistrés dans la mission** s'ils existent
    (`Chantier.bareme_seuils`), sinon ceux en vigueur sur le poste. Une
    mission antérieure à cette trace est donc décrite avec le barème
    courant — c'est la seule information disponible, et c'est bien celle
    qui a servi à recalculer les classes affichées.

    `chantier` est pris en duck-typing pour que ce module reste sous
    `model` dans le graphe de dépendances.
    """
    brut = getattr(chantier, "bareme_seuils", None)
    return description_seuils(seuils_depuis_brut(brut) if brut else None)


def description_seuils_arbre(chantier: object, port_arbre: str) -> str:
    """Seuils du **seul** groupe applicable à ce port, pour un livrable client.

    Même source que `description_seuils_mission` (seuils enregistrés dans
    la mission, sinon ceux du poste), mais restreinte au groupe de
    l'arbre et **sans nom de groupe ni port** : « vert > 70 %, orange ≥ 40 % ».
    Port sans groupe (config altérée) : repli sur `GROUPES_DEFAUT`, comme
    `classer_prbs`.
    """
    brut = getattr(chantier, "bareme_seuils", None)
    groupes = seuils_depuis_brut(brut) if brut else get_groupes()
    p = port_arbre.lower().strip()
    g = (next((x for x in groupes if p in x.ports), None)
         or next((x for x in GROUPES_DEFAUT if p in x.ports), None))
    if g is None:
        return ""
    return (f"vert > {g.seuil_vert * 100:.4g} %, "
            f"orange ≥ {g.seuil_orange * 100:.4g} %, "
            f"rouge < {g.seuil_orange * 100:.4g} %")


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

    Cherche le groupe de barème courant contenant ce port
    (`groupe_pour_port`, cf. `Affichage → Barème…` pour la composition
    des groupes). Si aucun groupe ne le couvre (config `bareme.json`
    incomplète ou altérée à la main — l'éditeur garantit normalement une
    partition complète), retombe sur le groupe de la partition PAR
    DÉFAUT qui contient ce port (ou le groupe libre par défaut si le
    port est lui-même inconnu) : jamais de crash, jamais un classement
    arbitraire silencieux.

    Convention de bornes : seuil haut strict (`>`), seuil bas inclusif
    (`>=`). Donc pile le seuil Vert est Orange, pile le seuil Orange est
    Orange, juste en dessous est Rouge.

    Renvoie le label de classe (`Vert`, `Orange` ou `Rouge`). La couleur
    hexa associée est une convention de présentation et vit côté UI.
    """
    p = port_arbre.lower().strip()
    grp = groupe_pour_port(p)
    if grp is None:
        grp = next((g for g in GROUPES_DEFAUT if p in g.ports),
                   GROUPES_DEFAUT[0])
    if ratio_tR > grp.seuil_vert:
        return CLASSE_VERT
    elif ratio_tR >= grp.seuil_orange:
        return CLASSE_ORANGE
    else:
        return CLASSE_ROUGE
