"""
Calculs de diagnostic d'un arbre : extrapolation, PRBS par grade,
ratio t/R, répartition par classe, lignes de résumé textuel.

Toutes les fonctions exposées par ce module sont **pures** : elles
prennent un `Arbre` (ou un objet duck-typé équivalent) en paramètre
et ne mutent rien. Aucun cache n'est stocké sur l'arbre — chaque
appelant (renderers Tk/PIL, exports, onglet Diagnostic) qui a besoin
du résultat le stocke dans une variable locale au point d'usage.

Contenu :
- `ClasseRepartition`, `DiagnosticSnapshot` — types de retour du
  snapshot diagnostic.
- `compute_alteration_par_grade(arbre)` — extrapolation par moyenne
  pondérée linéaire entre les voisins sondés.
- `degradation_externe_par_grade(arbre)` — profondeur de dégradation
  externe maximale par direction.
- `prbs_par_grade(arbre)` — PRBS effective (rayon − altération
  interne − dégradation externe).
- `ratio_tR_par_grade(arbre)` — PRBS / rayon, borné à [0, 1].
- `repartition_classes(arbre)` — `DiagnosticSnapshot` self-contained
  (répartition Vert/Orange/Rouge + ratios + extrapolation_text).
- `extrapolation_summary(arbre)` / `extrapolation_summary_text(arbre)` —
  indicateurs bruts + phrase prête à afficher de fiabilité de
  l'extrapolation.
- `diagnostic_summary_lines(arbre)` — résumé textuel multi-lignes
  pour le widget Label Tk de l'onglet Diagnostic et la fiche PDF.

Le module ne dépend que de `bareme.classer_prbs`, des constantes
`GRADES`/`DIRECTION_LABELS` de `geometry`, et de `model.Arbre` (en
TYPE_CHECKING uniquement, pour éviter tout import circulaire). Couvert
par `tests/test_model.py` (renommé volontairement pour ne pas casser
l'historique git, mais cible désormais ce module).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional, Tuple, Union

from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT, classer_prbs
from geometry import DIRECTION_LABELS, GRADES, polar_idx_to_xy, polar_to_xy
from model import URGENCE_NIVEAUX, URGENCE_RANG

if TYPE_CHECKING:
    from model import Arbre, Brin, Chantier, DegradationExterne  # noqa: F401
    # URGENCE_NIVEAUX / URGENCE_RANG sont importés à l'exécution ci-dessus.

    # Une « section » = tout ce qui expose la surface géométrique d'une tige
    # (rayon par direction, sondages, dégradations) : un `Brin` (= ramet,
    # natif) ou un `Arbre` (= genet, qui relaie vers `brins[0]` via shims).
    # Les fonctions de calcul/rendu acceptent indifféremment les deux, ce qui
    # permet d'opérer par brin sans casser les ~nombreux appels genet-level.
    Section = Union[Arbre, Brin]


@dataclass(frozen=True)
class ClasseRepartition:
    """Une ligne du diagnostic : nombre de directions, étendue angulaire,
    et pourcentage du périmètre pour une classe (Vert, Orange ou Rouge).
    """
    n: int          # nb de directions sur 16 dans cette classe
    grades: int     # étendue angulaire cumulée (gr) — chaque direction = 25 gr
    pct: float      # % du périmètre (= grades / 400)


@dataclass(frozen=True)
class DiagnosticSnapshot:
    """Snapshot self-contained du diagnostic d'un arbre, produit par
    `repartition_classes()`. Remplace l'ancien dict fourre-tout
    (`{"Vert": {...}, "ratios": [...], "tR_min": ..., …}`) par un type
    explicite, qui rend le contrat lisible et typable côté consommateurs.

    Le snapshot porte volontairement :
    - la répartition par classe (`vert`/`orange`/`rouge`) ;
    - la liste brute des `ratios` (16 t/R) ;
    - les indicateurs de direction critique (`tR_min*`) ;
    - la classe globale calculée sur le `tR_moyen` ;
    - la classe ponctuelle la plus défavorable (`classe_pire`) ;
    - l'état de l'extrapolation (`n_sondees`, `diagnostic_fiable`,
      `extrapolation_text`).

    `diagnostic_fiable` est True à partir de **3 directions sondées**
    (seuil, aligné sur la pastille d'état verte de la
    liste d'arbres et le footer « X/N arbres fiables »). En-dessous,
    `classe_globale` et `tR_moyen` reposent sur trop peu de mesures
    (les directions non sondées sont extrapolées ou supposées saines) et
    donneraient un résultat faussement rassurant : les consommateurs
    (UI, fiche PDF, XLSX, HTML) doivent masquer ces deux champs et
    signaler l'indisponibilité.

    NB : l'extrapolation géométrique de la cavité
    (`compute_alteration_par_grade`) reste active dès 2 sondages — c'est
    son minimum mathématique. La fiabilité du *diagnostic global publié*
    est un critère plus strict (3), volontairement découplé.
    """
    vert: ClasseRepartition
    orange: ClasseRepartition
    rouge: ClasseRepartition
    ratios: List[float]
    tR_min: float
    tR_min_grade: int
    tR_min_dir: str
    tR_moyen: float
    classe_globale: str
    classe_pire: str
    n_sondees: int
    diagnostic_fiable: bool
    extrapolation_text: str

    def par_classe(self, classe: str) -> ClasseRepartition:
        """Accès indexé par label (`"Vert"`, `"Orange"`, `"Rouge"`).

        Pratique pour les consommateurs qui itèrent
        `for cls in ("Vert", "Orange", "Rouge"):` sans dupliquer la
        gestion par attribut.
        """
        return {"Vert": self.vert,
                "Orange": self.orange,
                "Rouge": self.rouge}[classe]

    @property
    def diagnostic_global(self) -> Optional[Tuple[float, str]]:
        """`(tR_moyen, classe_globale)` si publiable, `None` sinon.

        Encapsule la règle « pas de diagnostic global si <3 sondages » :
        chaque consommateur (fiche PDF, XLSX, HTML, diagnostic Tk) doit
        appeler cette propriété plutôt que de lire `tR_moyen` /
        `classe_globale` puis tester `diagnostic_fiable` à la main —
        sinon le prochain export à arriver oubliera le masquage et
        affichera un Vert trompeur sur un arbre avec 1 sondage.

        Renvoyer un tuple plutôt qu'un objet permet le destructuring
        idiomatique :
        ```
        if (g := snap.diagnostic_global) is not None:
            tR_moyen, classe = g
            # … afficher t/R moyen et classe
        else:
            # … afficher l'avertissement
        ```
        """
        if not self.diagnostic_fiable:
            return None
        return (self.tR_moyen, self.classe_globale)


def compute_alteration_par_grade(arbre: "Section") -> List[float]:
    """Calcule les 16 épaisseurs d'altération à partir des sondages :

    - directions sondées : valeur la plus défavorable des sondages,
    - directions non sondées : moyenne pondérée entre les 2 sondages
      voisins (sens horaire / anti-horaire) — uniquement s'il y a
      au moins 2 sondages. Sinon 0 (bois sain).

    Fonction pure : ne mute rien. Les appelants stockent le résultat
    dans une variable locale au moment où ils en ont besoin. Pas de
    cache sur l'arbre : ça évitait des bugs « cache périmé avant
    dessin ».
    """
    # Étape 1 : valeurs aux directions sondées
    measured: Dict[int, float] = {}
    for s in arbre.sondages:
        if s.grade not in GRADES:
            continue
        idx = GRADES.index(s.grade)
        measured[idx] = max(measured.get(idx, 0.0), s.bois_altere_cm)

    new_vals = [0.0] * 16
    if len(measured) < 2:
        # Pas assez de points pour extrapoler : on garde les mesures
        # là où elles existent, et 0 ailleurs.
        for idx, v in measured.items():
            new_vals[idx] = v
        return new_vals

    # Étape 2 : pour chaque grade, soit mesuré, soit extrapolé
    sorted_idx = sorted(measured.keys())
    for i in range(16):
        if i in measured:
            new_vals[i] = measured[i]
            continue
        # voisin horaire (j > i en circulaire) + anti-horaire (j < i)
        next_idx: Optional[int] = None
        for j in sorted_idx:
            if j > i:
                next_idx = j
                break
        if next_idx is None:
            next_idx = sorted_idx[0]  # boucle
        prev_idx: Optional[int] = None
        for j in reversed(sorted_idx):
            if j < i:
                prev_idx = j
                break
        if prev_idx is None:
            prev_idx = sorted_idx[-1]  # boucle

        # distances angulaires (en nombre de pas de 22,5°)
        d_next = (next_idx - i) % 16
        d_prev = (i - prev_idx) % 16
        total = d_next + d_prev
        if total == 0:
            new_vals[i] = measured[i]  # cas dégénéré impossible ici
        else:
            # Moyenne pondérée : plus le voisin est proche, plus il
            # pèse. 20 cm à 0° + 10 cm à 100° (4 crans) donnent
            # 15 cm à 50° (2 crans de part et d'autre).
            w_next = d_prev / total
            w_prev = d_next / total
            new_vals[i] = (measured[next_idx] * w_next
                           + measured[prev_idx] * w_prev)
    return new_vals


def degradation_externe_par_grade(arbre: "Section") -> List[float]:
    """Pour chaque direction (16 grades), retourne la profondeur de
    dégradation externe **consommant du bois sain** qui couvre cette
    direction (max si plusieurs). 0 si aucune ne la couvre.

    La part de profondeur tombant dans la bande d'écorce est déduite quand
    la dégradation est mesurée depuis l'écorce (cf.
    `DegradationExterne.profondeur_bois_cm`) — l'écorce n'entre pas dans le
    calcul de la PRBS.
    """
    ep = max(0.0, arbre.epaisseur_ecorce_cm)
    out = [0.0] * 16
    for deg in arbre.degradations_externes:
        prof_bois = deg.profondeur_bois_cm(ep)
        for i, g in enumerate(GRADES):
            if deg.couvre_grade(g):
                out[i] = max(out[i], prof_bois)
    return out


def rayon_par_grade(arbre: "Section") -> List[float]:
    """Pour chaque direction (16 grades), retourne le rayon extérieur du
    bois en cm.

    Section circulaire (cas par défaut) → `rayon_tronc_cm` constant dans
    les 16 directions (comportement historique strictement préservé).
    Section ovale → rayon LOCAL de l'ellipse, qui rend le t/R par direction
    plus juste (un grand axe a plus de marge qu'un petit axe à PRBS égale).
    """
    return [arbre.rayon_a_grade(g) for g in GRADES]


def prbs_par_grade(arbre: "Section") -> List[float]:
    """Pour chaque direction (16 grades), retourne la PRBS réelle :
    rayon - altération interne - dégradation externe.

    C'est l'épaisseur de bois sain effectivement disponible, qui
    intègre les deux types de dégradation. Le rayon utilisé est le rayon
    LOCAL de la direction (cf. `rayon_par_grade` — constant si circulaire).
    Fonction pure.
    """
    if arbre.rayon_tronc_cm <= 0:
        return [0.0] * 16
    rayons = rayon_par_grade(arbre)
    alt_int = compute_alteration_par_grade(arbre)
    deg_ext = degradation_externe_par_grade(arbre)
    return [max(0.0, rayons[i] - alt_int[i] - deg_ext[i]) for i in range(16)]


def fusion_ecretee_par_grade(arbre: "Section") -> List[bool]:
    """Pour chaque direction (16 grades), True si la fusion des deux
    dégradations a écrêté : altération centrale + dégradation externe
    dépassent le rayon local, donc les deux zones se rejoignent et
    `prbs_par_grade` ramène la PRBS à 0. Le surplus saisi est
    physiquement impossible (plus de bois dégradé que de rayon).

    Convention confirmée (protocole terrain) : le sondage mesure la
    paroi totale en ignorant la dégradation externe (mèche posée à côté
    de la zone dégradée) ; l'app déduit ensuite la profondeur. L'écrêtage
    est donc légitime — mais il doit être SIGNALÉ, pas silencieux : sert
    au garde-fou non bloquant (⚠) des grilles de saisie et de l'onglet
    Diagnostic. Fonction pure.
    """
    if arbre.rayon_tronc_cm <= 0:
        return [False] * 16
    rayons = rayon_par_grade(arbre)
    alt_int = compute_alteration_par_grade(arbre)
    deg_ext = degradation_externe_par_grade(arbre)
    return [deg_ext[i] > 0 and alt_int[i] + deg_ext[i] > rayons[i] + 1e-9
            for i in range(16)]


# Message du garde-fou de fusion — partagé par les bandeaux ⚠ des onglets
# Sondages, Dégradations externes et Diagnostic (même vocabulaire partout).
FUSION_WARN_TEXT = (
    "⚠ Altération centrale + dégradation externe dépassent le rayon sur "
    "au moins une direction : les deux zones dégradées se rejoignent et "
    "la PRBS y est écrêtée à 0. Vérifiez la profondeur de la dégradation "
    "ou le bois sain du sondage concerné.")


def degradation_ecretee(arbre: "Section",
                        deg: "DegradationExterne") -> bool:
    """True si CETTE dégradation, cumulée à l'altération centrale,
    dépasse le rayon local sur au moins une direction qu'elle couvre.

    Variante par-objet de `fusion_ecretee_par_grade` : le flag par grade
    agrège le max des profondeurs, ce qui marquerait à tort la voisine
    peu profonde d'un arc mitoyen profond (les deux couvrent le
    grade-frontière). Ici on ne teste que la profondeur de `deg`.
    """
    prof_bois = deg.profondeur_bois_cm(max(0.0, arbre.epaisseur_ecorce_cm))
    if arbre.rayon_tronc_cm <= 0 or prof_bois <= 0:
        return False
    rayons = rayon_par_grade(arbre)
    alt_int = compute_alteration_par_grade(arbre)
    return any(deg.couvre_grade(g)
               and alt_int[i] + prof_bois > rayons[i] + 1e-9
               for i, g in enumerate(GRADES))


def ratio_tR_par_grade(arbre: "Section") -> List[float]:
    """Pour chaque direction, ratio t/R = PRBS / Rayon (entre 0 et 1).

    Le rayon dénominateur est le rayon LOCAL de la direction
    (`rayon_par_grade`) : pour une section ovale, chaque direction est
    rapportée à son propre rayon — c'est l'apport métier de l'Étape 1.
    Pour une section circulaire, c'est `rayon_tronc_cm` partout (inchangé).

    Clamp défensif `min(1.0, …)` : `prbs_par_grade` borne déjà à
    `[0, R_local]`, mais on aligne explicitement le contrat de sortie sur
    `Sondage.ratio_tR_brut` (qui clampe aussi).
    """
    if arbre.rayon_tronc_cm <= 0:
        return [0.0] * 16
    rayons = rayon_par_grade(arbre)
    prbs = prbs_par_grade(arbre)
    return [min(1.0, prbs[i] / rayons[i]) if rayons[i] > 0 else 0.0
            for i in range(16)]


def extrapolation_summary(arbre: "Section") -> Dict[str, int]:
    """Indicateurs bruts de fiabilité de l'extrapolation.

    Renvoie un dict :
    - `n_sondees`         : nombre de directions (sur 16) qui ont
                              au moins un sondage direct.
    - `n_extrapolees`     : `16 - n_sondees`.
    - `ecart_max_grades`  : plus grand écart angulaire (en gr)
                              entre deux directions sondées
                              voisines, en circulaire. Vaut 400
                              quand une seule direction est sondée
                              (pas de second point → l'arc à
                              extrapoler couvre tout le tour).
                              Vaut 0 quand aucune direction n'est
                              sondée.

    L'interprétation (« est-ce fiable ? ») est laissée au lecteur :
    l'app expose les chiffres bruts dans le diagnostic et la fiche
    PDF/XLSX/HTML, libre à l'opérateur Pénétromètre d'en tirer la
    conclusion adaptée à son cas.
    """
    grades_sondes = sorted({s.grade for s in arbre.sondages
                             if s.grade in GRADES})
    n = len(grades_sondes)
    if n == 0:
        return {"n_sondees": 0, "n_extrapolees": 16,
                "ecart_max_grades": 0}
    if n == 1:
        return {"n_sondees": 1, "n_extrapolees": 15,
                "ecart_max_grades": 400}
    ecart_max = max(
        (grades_sondes[(i + 1) % n] - grades_sondes[i]) % 400
        for i in range(n)
    )
    return {"n_sondees": n, "n_extrapolees": 16 - n,
            "ecart_max_grades": ecart_max}


def extrapolation_summary_text(arbre: "Section") -> str:
    """Phrase de couverture de sondage pour la fiche PDF : « N/16 directions
    sondées ». Chaîne vide si aucun sondage (le diagnostic affiche déjà
    « aucune altération »). L'écart angulaire entre voisins, peu parlant pour
    la lecture du diagnostic, n'est plus affiché ; la fiabilité (< 3 sondages)
    est signalée séparément par l'avertissement dédié."""
    n = extrapolation_summary(arbre)["n_sondees"]
    if n == 0:
        return ""
    if n == 1:
        return "1/16 direction sondée."
    return f"{n}/16 directions sondées."


def repartition_classes(arbre: "Arbre") -> DiagnosticSnapshot:
    """Diagnostic du **brin courant** du genet (compat : `brins[0]` + port
    du genet). Point d'entrée historique, inchangé pour tous les appelants
    mono-brin. Pour une cépée, voir `repartition_classes_brin` (par brin) et
    `genet_diagnostic` (agrégation pire-brin)."""
    return repartition_classes_brin(arbre.brin_courant, arbre.port_arbre)


def repartition_classes_brin(section: "Section", port: str) -> DiagnosticSnapshot:
    """Construit un `DiagnosticSnapshot` self-contained pour une **section**
    (un `Brin`, ou un `Arbre` mono-brin via shims).

    `port` est genet-level (partagé par tous les brins de la cépée) → passé
    explicitement, comme `sondage_render_data`.

    Snapshot self-contained : la dataclass porte aussi `ratios` et
    `extrapolation_text` pour que les callers (fiche PDF, diagnostic
    Tk, XLSX/HTML) n'aient pas à rappeler `ratio_tR_par_grade()` ni
    `extrapolation_summary_text()` après — ce qui rejouait toute la
    chaîne `compute_alteration_par_grade` une deuxième fois pour rien.

    Voir `DiagnosticSnapshot` pour le détail du contrat (en
    particulier `diagnostic_fiable`).
    """
    arbre = section  # alias local : le corps lit la géométrie de la section
    ratios = ratio_tR_par_grade(arbre)
    # Compteurs par classe, construits localement puis figés dans le
    # dataclass à la fin.
    n_par_classe = {"Vert": 0, "Orange": 0, "Rouge": 0}
    for r in ratios:
        n_par_classe[classer_prbs(r, port)] += 1
    # Chaque secteur = 25 gr ; pourcentage du périmètre = grades/400.
    repartitions = {
        cls: ClasseRepartition(
            n=n_par_classe[cls],
            grades=n_par_classe[cls] * 25,
            pct=100.0 * n_par_classe[cls] * 25 / 400.0,
        )
        for cls in ("Vert", "Orange", "Rouge")
    }

    # Direction critique (t/R minimal — info conservée)
    tR_min = min(ratios)
    i_crit = ratios.index(tR_min)
    grade_crit = GRADES[i_crit]
    dir_crit = DIRECTION_LABELS.get(grade_crit, "")
    if not dir_crit:
        for delta in (1, -1, 2, -2):
            g2 = GRADES[(i_crit + delta) % 16]
            lbl = DIRECTION_LABELS.get(g2)
            if lbl:
                dir_crit = f"~{lbl}"
                break

    # Classe globale = barème appliqué au t/R MOYEN sur les
    # 16 directions du pourtour.
    #
    # Cette approche reflète l'état général de la section :
    # - une seule direction critique ne déclasse pas tout l'arbre,
    # - mais une dégradation répartie tire la moyenne vers le bas.
    #
    # On conserve aussi t/R minimal et la pire classe ponctuelle comme
    # indicateurs complémentaires d'alerte locale.
    #
    # Convention métier confirmée par Pénétromètre (2026-05) : la classe
    # publiée est bien celle du t/R moyen, pas la pire classe
    # ponctuelle. Toute modification de cette règle doit revalider avec
    # l'utilisateur métier — la fiche PDF, XLSX et HTML s'alignent
    # toutes sur ce choix.
    tR_moyen = sum(ratios) / len(ratios) if ratios else 1.0
    classe_globale = classer_prbs(tR_moyen, port)
    # Pire classe ponctuelle (info complémentaire)
    if repartitions["Rouge"].n > 0:
        classe_pire = "Rouge"
    elif repartitions["Orange"].n > 0:
        classe_pire = "Orange"
    else:
        classe_pire = "Vert"

    # Fiabilité : seuil fixé à 3 directions sondées
    # minimum (aligné sur la pastille verte et le footer de la liste
    # d'arbres). En-dessous, trop peu de mesures réelles sur le pourtour :
    # les directions non sondées sont extrapolées (≥2) ou supposées
    # saines (≤1), ce qui tire artificiellement le t/R moyen vers Vert.
    n_sondees = extrapolation_summary(arbre)["n_sondees"]

    return DiagnosticSnapshot(
        vert=repartitions["Vert"],
        orange=repartitions["Orange"],
        rouge=repartitions["Rouge"],
        ratios=ratios,
        tR_min=tR_min,
        tR_min_grade=grade_crit,
        tR_min_dir=dir_crit,
        tR_moyen=tR_moyen,
        classe_globale=classe_globale,
        classe_pire=classe_pire,
        n_sondees=n_sondees,
        diagnostic_fiable=n_sondees >= 3,
        extrapolation_text=extrapolation_summary_text(arbre),
    )


# ---------------------------------------------------------------------
# Agrégation genet (cépée) : un diagnostic par brin + classe globale
# ---------------------------------------------------------------------

# Ordre de gravité des classes : le « pire brin » d'une cépée est celui de
# classe maximale selon cet ordre (approche sécuritaire validée —
# l'agrégat porte sur les CLASSES des brins, jamais sur un t/R moyen
# inter-brins, dont les repères polaires distincts n'ont pas de sens commun).
_GRAVITE_CLASSE = {"Vert": 0, "Orange": 1, "Rouge": 2}


def pire_classe(classes: List[str]) -> Optional[str]:
    """Classe la plus défavorable d'une liste (Rouge > Orange > Vert).
    `None` si la liste est vide."""
    if not classes:
        return None
    return max(classes, key=lambda c: _GRAVITE_CLASSE.get(c, 0))


class BrinDiagnostic(NamedTuple):
    """Diagnostic d'un brin dans le contexte d'un genet."""
    label: str                      # « a », « b », … ("" si genet mono-caule)
    snapshot: DiagnosticSnapshot    # diagnostic complet du brin
    fiable: bool                    # rayon défini ET ≥ 3 directions sondées


class GenetDiagnostic(NamedTuple):
    """Diagnostic agrégé d'un genet (cépée) : un snapshot par brin + la
    synthèse pire-brin.

    `classe_globale` = pire classe parmi les brins **fiables** (≥ 3 sondages
    ET rayon défini) ; `None` si aucun brin n'est fiable. `fiable` = au moins
    un brin fiable (le genet a alors une classe publiable). Règle métier :
    un brin non fiable est **rapporté** (dans `brins`) mais n'entre PAS dans
    la classe globale et ne rend pas le genet non publiable.
    """
    brins: List[BrinDiagnostic]
    classe_globale: Optional[str]
    fiable: bool


def genet_diagnostic(arbre: "Arbre") -> GenetDiagnostic:
    """Agrège le diagnostic d'un genet (mono-caule ou cépée).

    Un `BrinDiagnostic` par brin (diagnostic du brin + sa fiabilité), et la
    classe globale = pire classe parmi les brins fiables. Pour un genet
    mono-brin, `classe_globale`/`fiable` coïncident avec le diagnostic du
    brin unique (comportement historique préservé)."""
    port = arbre.port_arbre
    brins_diag: List[BrinDiagnostic] = []
    for b in arbre.brins:
        snap = repartition_classes_brin(b, port)
        fiable = b.rayon_tronc_cm > 0 and snap.diagnostic_fiable
        brins_diag.append(BrinDiagnostic(label=b.label, snapshot=snap,
                                         fiable=fiable))
    classes = [bd.snapshot.diagnostic_global[1]
               for bd in brins_diag
               if bd.fiable and bd.snapshot.diagnostic_global is not None]
    return GenetDiagnostic(brins=brins_diag,
                           classe_globale=pire_classe(classes),
                           fiable=any(bd.fiable for bd in brins_diag))


def diagnostic_summary_lines(arbre: "Arbre") -> List[str]:
    """Résumé diagnostic du **brin courant** du genet (compat mono-brin,
    inchangé). Pour une cépée, voir `genet_summary_lines` (résumé agrégé
    avec un bloc par brin). Lignes prêtes à `"\\n".join(...)`. Fonction pure."""
    return [t for t, _ in _section_summary_tagged(arbre.brin_courant,
                                                   arbre.port_arbre,
                                                   arbre.display_name)]


# Tag couleur pour chaque classe (correspond aux tags tk.Text de pane_diagnostic).
_TAG_CLASSE: Dict[str, str] = {"Vert": "vert", "Orange": "orange", "Rouge": "rouge"}


def _section_summary_tagged(section: "Section", port: str, titre: str, *,
                             show_port: bool = True) -> "List[Tuple[str, str]]":
    """Cœur du résumé textuel pour UNE section (brin).

    Retourne des tuples `(texte, tag)` — tag ∈ ``{"vert","orange","rouge","warn",""}``.
    Les lignes de classe portent le tag coloré ; toutes les autres ont `""`.
    `show_port=False` masque la ligne « Port » (redondante dans un bloc de
    brin où le port du genet est déjà affiché en tête)."""
    if section.rayon_tronc_cm <= 0:
        return [("Renseignez le rayon du tronc et ajoutez des "
                 "sondages pour obtenir un résumé.", "")]

    R = section.rayon_tronc_cm
    snap = repartition_classes_brin(section, port)
    n_sondees = extrapolation_summary(section)["n_sondees"]

    # Ligne d'identité compacte : rayon + port + couverture de sondage.
    # (Le nb de dégrad./contreforts et l'écart angulaire n'aident pas la
    # lecture du diagnostic → retirés ; « N/16 directions sondées » remplace
    # à la fois l'ancien compteur « Sondages : N » et la phrase d'extrapolation.)
    meta = f"Rayon : {R:g} cm"
    if show_port:
        meta += f"   •   Port : {port}"
    meta += f"   •   {n_sondees}/16 directions sondées"
    lignes: List[Tuple[str, str]] = [
        (f"« {titre} »", ""),
        (meta, ""),
        ("", ""),
    ]

    if all(r >= 0.999 for r in snap.ratios):
        lignes.append(("Aucune altération saisie (interne ou externe).", ""))
        return lignes

    # Direction critique = mesure réelle → montrée même en diagnostic non
    # fiable (< 3 sondages). t/R minimal est regroupé avec t/R moyen (zone
    # unique) quand le diagnostic global est publiable.
    tR_min_txt = (f"t/R minimal : {100*snap.tR_min:.1f} %  "
                  f"(grade {snap.tR_min_grade} gr — {snap.tR_min_dir})")

    diag = snap.diagnostic_global
    if diag is None:
        lignes.append((tR_min_txt, ""))
        lignes.append(("", ""))
        lignes.append(
            ("⚠ Diagnostic global indisponible : il faut au moins "
             "3 directions sondées pour un diagnostic fiable.", "warn"))
        return lignes
    tR_moyen, classe_globale = diag

    lignes.append(("Répartition sur le pourtour (16 directions) :", ""))
    for cls in ("Vert", "Orange", "Rouge"):
        r = snap.par_classe(cls)
        if r.n > 0:
            tag = _TAG_CLASSE[cls]
            lignes.append(
                (f"  ● {cls:<7} : {r.n}/16 directions  "
                 f"({r.grades} gr / {r.pct:.0f} % du pourtour)", tag))
    lignes.append(("", ""))
    # Zone t/R regroupée : moyen (global) + minimal (direction critique).
    lignes.append(
        (f"t/R moyen : {100*tR_moyen:.1f} %      {tR_min_txt}", ""))
    lignes.append((f"→ Classe globale : {classe_globale}",
                   _TAG_CLASSE.get(classe_globale, "")))
    return lignes


def _section_summary_lines(section: "Section", port: str, titre: str, *,
                            show_port: bool = True) -> List[str]:
    """Wrapper non coloré de `_section_summary_tagged` (lignes texte seules)."""
    return [t for t, _ in _section_summary_tagged(
        section, port, titre, show_port=show_port)]


def genet_summary_tagged(arbre: "Arbre") -> "List[Tuple[str, str]]":
    """Version taguée de `genet_summary_lines` : `(texte, tag)` par ligne.

    Mono-caule → bloc unique ; cépée → en-tête + un bloc par brin.
    Tag ∈ ``{"vert","orange","rouge","warn",""}`` — exploité par le widget
    ``tk.Text`` de ``pane_diagnostic`` pour coloriser les lignes de classe.
    Fonction pure."""
    if len(arbre.brins) <= 1:
        return _section_summary_tagged(arbre.brin_courant, arbre.port_arbre,
                                       arbre.display_name)
    gd = genet_diagnostic(arbre)
    lignes: List[Tuple[str, str]] = [
        (f"« {arbre.display_name} » — cépée à {len(arbre.brins)} brins", ""),
        (f"Port : {arbre.port_arbre}", ""),
    ]
    if gd.classe_globale is not None:
        lignes.append(
            (f"→ Classe globale (pire brin fiable) : {gd.classe_globale}",
             _TAG_CLASSE.get(gd.classe_globale, "")))
    else:
        lignes.append(
            ("⚠ Classe globale indisponible : aucun brin avec au moins "
             "3 directions sondées.", "warn"))
    lignes.append(("", ""))
    for b in arbre.brins:
        lbl = b.label or "?"
        lignes.append((f"──── Brin {lbl} ────", ""))
        lignes.extend(_section_summary_tagged(
            b, arbre.port_arbre, f"Brin {lbl}", show_port=False))
        lignes.append(("", ""))
    return lignes


def genet_summary_lines(arbre: "Arbre") -> List[str]:
    """Résumé diagnostic d'un genet, prêt à `"\\n".join(...)`.

    Mono-caule → identique à `diagnostic_summary_lines`. Cépée → en-tête
    (classe globale = pire brin fiable) puis un **bloc par brin** (a, b, …).
    Fonction pure."""
    return [t for t, _ in genet_summary_tagged(arbre)]


# ---------------------------------------------------------------------
# Synthèse de mission : une ligne par arbre (hiérarchisation du risque)
# ---------------------------------------------------------------------

class MissionSynthesisRow(NamedTuple):
    """Une ligne de synthèse mission = l'état diagnostic d'un arbre.

    Champs masqués (`None`) selon la règle métier de fiabilité :
    - `tR_moyen_pct` / `classe_globale` = `None` si le diagnostic global
      n'est pas publiable (rayon nul, ou < 3 directions sondées — cf.
      `DiagnosticSnapshot.diagnostic_global`).
    - `tR_min_pct` / `crit_grade` = `None` s'il n'y a aucune altération
      saisie (ou aucun sondage) : pas de « direction critique » pertinente.

    `fiable` rappelle l'état de fiabilité (≥ 3 sondages) pour que les
    consommateurs puissent afficher « Non fiable » plutôt qu'un simple
    tiret quand l'arbre a 1-2 sondages.
    """
    numero: str
    essence: str
    port: str
    n_sondees: int
    rayon_cm: float
    fiable: bool
    tR_moyen_pct: Optional[float]
    classe_globale: Optional[str]
    tR_min_pct: Optional[float]
    crit_grade: Optional[int]
    crit_dir: str
    # "" pour une ligne genet (mono-caule, ou ligne de tête d'une cépée) ;
    # "a"/"b"/… pour une sous-ligne de brin d'une cépée.
    brin_label: str = ""
    # Préconisation (niveau genet → renseignée sur les lignes genet/tête de
    # cépée uniquement, "" sur les sous-lignes de brin).
    urgence: str = ""
    echeance: str = ""
    preconisation: str = ""
    # Suivi (même portée genet).
    suivi_validite: str = ""
    suivi_echeance: str = ""
    suivi_texte: str = ""


def _synthesis_row_for_section(numero: str, essence: str, port: str,
                               section: "Section", brin_label: str = ""
                               ) -> MissionSynthesisRow:
    """Ligne de synthèse pour une **section** (brin) : t/R moyen, classe,
    direction critique, en respectant le masquage < 3 sondages."""
    n = len([s for s in section.sondages if s.grade in GRADES])
    if section.rayon_tronc_cm <= 0 or n == 0:
        return MissionSynthesisRow(
            numero=numero, essence=essence, port=port, n_sondees=n,
            rayon_cm=section.rayon_tronc_cm, fiable=False,
            tR_moyen_pct=None, classe_globale=None,
            tR_min_pct=None, crit_grade=None, crit_dir="",
            brin_label=brin_label)
    snap = repartition_classes_brin(section, port)
    diag = snap.diagnostic_global
    tR_moyen_pct = 100.0 * diag[0] if diag is not None else None
    classe = diag[1] if diag is not None else None
    if snap.tR_min >= 0.999:  # aucune altération → pas de direction critique
        tR_min_pct: Optional[float] = None
        crit_grade: Optional[int] = None
        crit_dir = ""
    else:
        tR_min_pct = 100.0 * snap.tR_min
        crit_grade = snap.tR_min_grade
        crit_dir = snap.tR_min_dir
    return MissionSynthesisRow(
        numero=numero, essence=essence, port=port,
        n_sondees=snap.n_sondees, rayon_cm=section.rayon_tronc_cm,
        fiable=snap.diagnostic_fiable,
        tR_moyen_pct=tR_moyen_pct, classe_globale=classe,
        tR_min_pct=tR_min_pct, crit_grade=crit_grade, crit_dir=crit_dir,
        brin_label=brin_label)


def _synthesis_genet_row(arbre: "Arbre") -> MissionSynthesisRow:
    """Ligne de tête d'une cépée : classe globale = pire brin (via
    `genet_diagnostic`), rayon = plus gros brin, point critique = pire t/R
    parmi les brins. `tR_moyen_pct` reste `None` (la moyenne inter-brins
    n'a pas de sens — l'agrégat porte sur les classes)."""
    gd = genet_diagnostic(arbre)
    port = arbre.port_arbre
    n_total = sum(extrapolation_summary(b)["n_sondees"] for b in arbre.brins)
    rayon = max((b.rayon_tronc_cm for b in arbre.brins), default=0.0)
    worst: Optional[DiagnosticSnapshot] = None
    for b in arbre.brins:
        if b.rayon_tronc_cm <= 0:
            continue
        snap = repartition_classes_brin(b, port)
        if snap.tR_min < 0.999 and (worst is None or snap.tR_min < worst.tR_min):
            worst = snap
    if worst is not None:
        tR_min_pct: Optional[float] = 100.0 * worst.tR_min
        crit_grade: Optional[int] = worst.tR_min_grade
        crit_dir = worst.tR_min_dir
    else:
        tR_min_pct = crit_grade = None
        crit_dir = ""
    return MissionSynthesisRow(
        numero=arbre.numero_arbre, essence=arbre.essence, port=port,
        n_sondees=n_total, rayon_cm=rayon, fiable=gd.fiable,
        tR_moyen_pct=None, classe_globale=gd.classe_globale,
        tR_min_pct=tR_min_pct, crit_grade=crit_grade, crit_dir=crit_dir,
        brin_label="")


# Rang de tri pour la classe de risque : Rouge = priorité haute, None/inconnu
# = priorité basse (non fiable). Utilisé par `mission_synthesis_rows`.
_CLASSE_RANG: Dict[Optional[str], int] = {
    CLASSE_ROUGE: 0, CLASSE_ORANGE: 1, CLASSE_VERT: 2
}


def mission_synthesis_rows(chantier: "Chantier", *,
                           trier_par_urgence: bool = False,
                           ) -> List[MissionSynthesisRow]:
    """Synthèse de la mission.

    Un genet **mono-caule** = une ligne (comportement historique). Une
    **cépée** = une ligne de tête (classe globale = pire brin) suivie d'une
    sous-ligne par brin (`brin_label` renseigné). Fonction pure ; respecte
    la règle « pas de diagnostic global < 3 sondages ». Source unique des
    exports de synthèse (XLSX/CSV) et de tout récap à l'écran.

    Si `trier_par_urgence=True`, les lignes sont triées par urgence
    décroissante (Immédiate → … → non renseignée) puis par classe de risque
    (Rouge → Orange → Vert → non fiable). Les sous-lignes de brin (cépées)
    restent groupées sous leur ligne de tête.
    """
    rows: List[MissionSynthesisRow] = []
    for a in chantier.arbres:
        # Préconisation : portée par la ligne genet / tête de cépée.
        def _with_preco(row: MissionSynthesisRow,
                        arbre: "Arbre" = a) -> MissionSynthesisRow:
            return row._replace(urgence=arbre.urgence,
                                echeance=arbre.echeance,
                                preconisation=arbre.preconisation,
                                suivi_validite=arbre.suivi_validite,
                                suivi_echeance=arbre.suivi_echeance,
                                suivi_texte=arbre.suivi_texte)
        if len(a.brins) <= 1:
            rows.append(_with_preco(_synthesis_row_for_section(
                a.numero_arbre, a.essence, a.port_arbre, a.brin_courant)))
            continue
        rows.append(_with_preco(_synthesis_genet_row(a)))
        for b in a.brins:
            rows.append(_synthesis_row_for_section(
                a.numero_arbre, a.essence, a.port_arbre, b,
                brin_label=b.label or "?"))

    if trier_par_urgence:
        # Regroupe les lignes : chaque groupe = ligne genet + éventuelles
        # sous-lignes de brin (brin_label != ""). La ligne de tête pilote
        # le tri ; les sous-lignes restent collées à elle.
        groups: List[List[MissionSynthesisRow]] = []
        for row in rows:
            if not row.brin_label:
                groups.append([row])
            else:
                groups[-1].append(row)

        def _group_key(g: List[MissionSynthesisRow]) -> Tuple[int, int]:
            head = g[0]
            return (
                URGENCE_RANG.get(head.urgence, len(URGENCE_NIVEAUX)),
                _CLASSE_RANG.get(head.classe_globale, 3),
            )

        groups.sort(key=_group_key)
        rows = [r for g in groups for r in g]

    return rows


# La comparaison inter-missions (ré-inspection) vit dans
# `diagnostic_comparaison.py` — sous-domaine distinct, déjà séparé côté
# UI (comparaison.py/comparaison_render.py), qui ne réutilise d'ici que
# `prbs_par_grade`, `_synthesis_row_for_section`, `_synthesis_genet_row`
# et `_GRAVITE_CLASSE`.

# ---------------------------------------------------------------------
# Données de rendu partagées Tk ↔ PIL pour les sondages
# ---------------------------------------------------------------------

class SondageRenderItem(NamedTuple):
    """Données pré-calculées pour dessiner un sondage sur la section."""
    numero: int
    arrow_start: Tuple[float, float]
    arrow_end: Tuple[float, float]
    bullet_center: Tuple[float, float]
    classe_color: str


def sondage_render_data(
    arbre: "Section", port: str, meche: float,
    cx: float, cy: float, R: float, scale: float,
    inset_cm: float, couleur_classe: Dict[str, str],
    rotation_grades: float = 0.0,
) -> List[SondageRenderItem]:
    """Calcule les données de rendu de chaque sondage (position, couleur).

    Partage la logique entre les deux renderers (Tk et PIL) : même
    classification, même positionnement, même pénétration. Les renderers
    n'ont plus qu'à dessiner avec leur propre API.

    `arbre` est une **section** (un `Brin`, ou un `Arbre` mono-brin via
    shims) : on y lit la géométrie et les sondages. `port` et `meche` sont
    des données **genet-level** (portées par l'`Arbre`, partagées par tous
    les brins) — passées explicitement pour que ce calcul opère par brin
    dans une cépée sans avoir à remonter au genet.
    """
    if R <= 0:
        return []
    meche = meche if meche > 0 else float("inf")
    deg_ext = degradation_externe_par_grade(arbre)
    items: List[SondageRenderItem] = []
    for s in arbre.sondages:
        if s.grade not in GRADES:
            continue
        i = GRADES.index(s.grade)
        # Rayon LOCAL de la direction (= R pour un tronc circulaire, rayon
        # de l'ellipse pour un tronc ovale) : la flèche et la pastille se
        # posent sur le contour réel, et le t/R de la pastille est rapporté
        # au rayon de SA direction.
        r_loc = arbre.rayon_a_grade(s.grade)
        penetration = min(s.bois_sain_cm + s.bois_altere_cm, meche)
        penetration = max(0.0, min(penetration, r_loc))
        end_radius = r_loc - penetration
        prbs_adj = max(0.0, s.prbs_cm - deg_ext[i])
        ratio_adj = prbs_adj / r_loc if r_loc > 0 else 0.0
        col = couleur_classe[classer_prbs(ratio_adj, port)]
        if rotation_grades:
            # Brin pivoté (cépée) : place la pastille/flèche au grade monde
            # `i*25 + rotation`, cohérent avec la forme pivotée du brin.
            g_world = i * 25.0 + rotation_grades
            x_ext, y_ext = polar_to_xy(cx, cy, scale, r_loc - inset_cm, g_world)
            x_end, y_end = polar_to_xy(cx, cy, scale, end_radius, g_world)
        else:
            x_ext, y_ext = polar_idx_to_xy(cx, cy, scale, r_loc - inset_cm, i)
            x_end, y_end = polar_idx_to_xy(cx, cy, scale, end_radius, i)
        items.append(SondageRenderItem(
            numero=s.numero,
            arrow_start=(x_ext, y_ext),
            arrow_end=(x_end, y_end),
            bullet_center=(x_ext, y_ext),
            classe_color=col,
        ))
    return items


# --- Checkliste de complétude de mission --------------------------------

def mission_completeness_warnings(chantier: "Chantier") -> list[str]:
    """Renvoie une liste de messages d'avertissement sur la complétude
    de la mission avant export. Liste vide = mission exportable sans réserve.

    Catégories vérifiées :
    - Arbres sans rayon (Ø non saisi → diagnostic impossible)
    - Arbres sans aucun sondage
    - Arbres avec 1-2 sondages (diagnostic non fiable, < 3)
    - Arbres sans urgence renseignée (préconisation incomplète)
    """
    arbres = chantier.arbres
    if not arbres:
        return []

    def _nums(lst: list, max_shown: int = 5) -> str:
        nums = [a.numero_arbre or "?" for a in lst[:max_shown]]
        suffix = f"… (+{len(lst)-max_shown})" if len(lst) > max_shown else ""
        return ", ".join(nums) + suffix

    warnings: list[str] = []

    sans_rayon = [a for a in arbres if a.rayon_tronc_cm <= 0]
    if sans_rayon:
        warnings.append(
            f"{len(sans_rayon)} arbre(s) sans rayon saisi "
            f"(diagnostic impossible) : {_nums(sans_rayon)}")

    sans_sondage = [a for a in arbres
                    if not any(b.sondages for b in a.brins)]
    if sans_sondage:
        warnings.append(
            f"{len(sans_sondage)} arbre(s) sans aucun sondage "
            f": {_nums(sans_sondage)}")

    non_fiable = [a for a in arbres
                  if 0 < sum(len(b.sondages) for b in a.brins) < 3
                  and a.rayon_tronc_cm > 0]
    if non_fiable:
        warnings.append(
            f"{len(non_fiable)} arbre(s) avec moins de 3 sondages "
            f"(diagnostic non fiable) : {_nums(non_fiable)}")

    sans_urgence = [a for a in arbres if not a.urgence]
    if sans_urgence:
        warnings.append(
            f"{len(sans_urgence)} arbre(s) sans préconisation d'urgence"
            f" : {_nums(sans_urgence)}")

    return warnings
