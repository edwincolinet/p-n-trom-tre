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
from typing import TYPE_CHECKING, Dict, List, NamedTuple, Optional, Tuple

from bareme import classer_prbs
from geometry import DIRECTION_LABELS, GRADES, polar_idx_to_xy

if TYPE_CHECKING:
    from model import Arbre, Chantier  # noqa: F401


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
    (seuil métier Silvavenir, aligné sur la pastille d'état verte de la
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


def compute_alteration_par_grade(arbre: "Arbre") -> List[float]:
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


def degradation_externe_par_grade(arbre: "Arbre") -> List[float]:
    """Pour chaque direction (16 grades), retourne la profondeur
    maximale de dégradation externe qui couvre cette direction.
    0 si aucune dégradation ne la couvre.
    """
    out = [0.0] * 16
    for deg in arbre.degradations_externes:
        for i, g in enumerate(GRADES):
            if deg.couvre_grade(g):
                out[i] = max(out[i], deg.profondeur_cm)
    return out


def rayon_par_grade(arbre: "Arbre") -> List[float]:
    """Pour chaque direction (16 grades), retourne le rayon extérieur du
    bois en cm.

    Section circulaire (cas par défaut) → `rayon_tronc_cm` constant dans
    les 16 directions (comportement historique strictement préservé).
    Section ovale → rayon LOCAL de l'ellipse, qui rend le t/R par direction
    plus juste (un grand axe a plus de marge qu'un petit axe à PRBS égale).
    """
    return [arbre.rayon_a_grade(g) for g in GRADES]


def prbs_par_grade(arbre: "Arbre") -> List[float]:
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


def ratio_tR_par_grade(arbre: "Arbre") -> List[float]:
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


def extrapolation_summary(arbre: "Arbre") -> Dict[str, int]:
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
    PDF/XLSX/HTML, libre à l'opérateur Silvavenir d'en tirer la
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


def extrapolation_summary_text(arbre: "Arbre") -> str:
    """Phrase prête à afficher pour le diagnostic. Renvoie une chaîne
    vide si aucun sondage n'a été saisi (auquel cas le diagnostic
    affiche déjà « aucune altération »)."""
    s = extrapolation_summary(arbre)
    n = s["n_sondees"]
    if n == 0:
        return ""
    if n == 16:
        return "16/16 directions sondées — aucune extrapolation."
    if n == 1:
        return ("1/16 direction sondée — pas de second point, "
                "l'extrapolation est désactivée.")
    return (f"{n}/16 directions sondées — écart angulaire maximal "
            f"entre voisins : {s['ecart_max_grades']} gr.")


def repartition_classes(arbre: "Arbre") -> DiagnosticSnapshot:
    """Construit un `DiagnosticSnapshot` self-contained pour l'arbre.

    Snapshot self-contained : la dataclass porte aussi `ratios` et
    `extrapolation_text` pour que les callers (fiche PDF, diagnostic
    Tk, XLSX/HTML) n'aient pas à rappeler `ratio_tR_par_grade()` ni
    `extrapolation_summary_text()` après — ce qui rejouait toute la
    chaîne `compute_alteration_par_grade` une deuxième fois pour rien.

    Voir `DiagnosticSnapshot` pour le détail du contrat (en
    particulier `diagnostic_fiable`).
    """
    ratios = ratio_tR_par_grade(arbre)
    # Compteurs par classe, construits localement puis figés dans le
    # dataclass à la fin.
    n_par_classe = {"Vert": 0, "Orange": 0, "Rouge": 0}
    for r in ratios:
        n_par_classe[classer_prbs(r, arbre.port_arbre)] += 1
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

    # Classe globale = barème Silvavenir appliqué au t/R MOYEN sur les
    # 16 directions du pourtour.
    #
    # Cette approche reflète l'état général de la section :
    # - une seule direction critique ne déclasse pas tout l'arbre,
    # - mais une dégradation répartie tire la moyenne vers le bas.
    #
    # On conserve aussi t/R minimal et la pire classe ponctuelle comme
    # indicateurs complémentaires d'alerte locale.
    #
    # Convention métier confirmée par Silvavenir (2026-05) : la classe
    # publiée est bien celle du t/R moyen, pas la pire classe
    # ponctuelle. Toute modification de cette règle doit revalider avec
    # l'utilisateur métier — la fiche PDF, XLSX et HTML s'alignent
    # toutes sur ce choix.
    tR_moyen = sum(ratios) / len(ratios) if ratios else 1.0
    classe_globale = classer_prbs(tR_moyen, arbre.port_arbre)
    # Pire classe ponctuelle (info complémentaire)
    if repartitions["Rouge"].n > 0:
        classe_pire = "Rouge"
    elif repartitions["Orange"].n > 0:
        classe_pire = "Orange"
    else:
        classe_pire = "Vert"

    # Fiabilité : seuil métier Silvavenir fixé à 3 directions sondées
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


def diagnostic_summary_lines(arbre: "Arbre") -> List[str]:
    """Renvoie les lignes textuelles du résumé diagnostic, prêtes à
    être jointes par `"\\n".join(...)` pour un widget Label Tk.

    Couvre :
    - identité de l'arbre + comptes de sondages/dégradations/contreforts ;
    - fiabilité de l'extrapolation (n/16 directions, écart angulaire max) ;
    - direction critique (t/R minimal) ;
    - répartition Vert/Orange/Rouge sur les 16 directions ;
    - t/R moyen et classe globale.

    Cas particuliers :
    - rayon nul → une seule ligne d'aide à l'utilisateur ;
    - aucune altération saisie → un message court remplace la
      répartition.

    Fonction pure, testable. Les widgets Tk sont mis à jour par
    l'appelant (`pane_diagnostic.refresh`).
    """
    if arbre.rayon_tronc_cm <= 0:
        return ["Renseignez le rayon du tronc et ajoutez des "
                "sondages pour obtenir un résumé."]

    R = arbre.rayon_tronc_cm
    # Un seul appel à repartition_classes : le snapshot porte aussi
    # `ratios` et `extrapolation_text` pour qu'on n'ait pas à rejouer
    # `ratio_tR_par_grade` ni `extrapolation_summary_text` (qui
    # repassent par compute_alteration_par_grade et ses copains).
    snap = repartition_classes(arbre)
    lignes: List[str] = [
        f"« {arbre.display_name} »",
        f"Rayon : {R:g} cm   •   Sondages : {len(arbre.sondages)}"
        f"   •   Dégrad. ext. : {len(arbre.degradations_externes)}"
        f"   •   Contreforts : {len(arbre.contreforts)}",
        f"Port : {arbre.port_arbre}",
        "",
    ]
    if snap.extrapolation_text:
        lignes.append(snap.extrapolation_text)
        lignes.append("")

    # Si rien de saisi (t/R == 1 partout, à l'epsilon près)
    if all(r >= 0.999 for r in snap.ratios):
        lignes.append("Aucune altération saisie (interne ou externe).")
        return lignes

    lignes.append(
        f"t/R minimal : {100*snap.tR_min:.1f} %  "
        f"(grade {snap.tR_min_grade} gr — {snap.tR_min_dir})")
    lignes.append("")

    # En-dessous de 3 sondages, le diagnostic global n'est pas publié :
    # trop peu de mesures réelles sur le pourtour (les directions non
    # sondées sont extrapolées ou supposées saines), ce qui ferait
    # afficher un t/R moyen et une classe globale faussement rassurants.
    # La propriété `diagnostic_global` retourne `None` dans ce cas — un
    # seul point d'entrée à respecter (par tous les exports) au lieu de
    # tester `diagnostic_fiable` à la main.
    diag = snap.diagnostic_global
    if diag is None:
        lignes.append(
            "⚠ Diagnostic global indisponible : il faut au moins "
            "3 directions sondées pour un diagnostic fiable.")
        return lignes
    tR_moyen, classe_globale = diag

    lignes.append("Répartition sur le pourtour (16 directions) :")
    for cls, symbol in (("Vert", "🟢"), ("Orange", "🟠"),
                         ("Rouge", "🔴")):
        r = snap.par_classe(cls)
        if r.n > 0:
            lignes.append(
                f"  {symbol} {cls:<7} : {r.n}/16 directions  "
                f"({r.grades} gr / {r.pct:.0f} % du pourtour)")
    lignes.append("")
    lignes.append(
        f"t/R moyen sur le pourtour : {100*tR_moyen:.1f} %")
    lignes.append(f"→ Classe globale : {classe_globale}")
    return lignes


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


def mission_synthesis_rows(chantier: "Chantier") -> List[MissionSynthesisRow]:
    """Construit la synthèse de la mission : une `MissionSynthesisRow`
    par arbre, dans l'ordre de la liste d'arbres.

    Fonction pure (réutilise `repartition_classes` et respecte la règle
    « pas de diagnostic global < 3 sondages »). Sert de source unique aux
    exports de synthèse (XLSX/CSV) et à tout récap à l'écran.
    """
    rows: List[MissionSynthesisRow] = []
    for a in chantier.arbres:
        n = len([s for s in a.sondages if s.grade in GRADES])
        if a.rayon_tronc_cm <= 0 or n == 0:
            rows.append(MissionSynthesisRow(
                numero=a.numero_arbre, essence=a.essence,
                port=a.port_arbre, n_sondees=n,
                rayon_cm=a.rayon_tronc_cm, fiable=False,
                tR_moyen_pct=None, classe_globale=None,
                tR_min_pct=None, crit_grade=None, crit_dir=""))
            continue
        snap = repartition_classes(a)
        diag = snap.diagnostic_global
        tR_moyen_pct = 100.0 * diag[0] if diag is not None else None
        classe = diag[1] if diag is not None else None
        if snap.tR_min >= 0.999:  # aucune altération → pas de dir. critique
            tR_min_pct: Optional[float] = None
            crit_grade: Optional[int] = None
            crit_dir = ""
        else:
            tR_min_pct = 100.0 * snap.tR_min
            crit_grade = snap.tR_min_grade
            crit_dir = snap.tR_min_dir
        rows.append(MissionSynthesisRow(
            numero=a.numero_arbre, essence=a.essence, port=a.port_arbre,
            n_sondees=snap.n_sondees, rayon_cm=a.rayon_tronc_cm,
            fiable=snap.diagnostic_fiable,
            tR_moyen_pct=tR_moyen_pct, classe_globale=classe,
            tR_min_pct=tR_min_pct, crit_grade=crit_grade,
            crit_dir=crit_dir))
    return rows


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
    arbre: "Arbre", cx: float, cy: float, R: float, scale: float,
    inset_cm: float, couleur_classe: Dict[str, str],
) -> List[SondageRenderItem]:
    """Calcule les données de rendu de chaque sondage (position, couleur).

    Partage la logique entre les deux renderers (Tk et PIL) : même
    classification, même positionnement, même pénétration. Les renderers
    n'ont plus qu'à dessiner avec leur propre API.
    """
    if R <= 0:
        return []
    port = arbre.port_arbre
    meche = arbre.meche_cm if arbre.meche_cm > 0 else float("inf")
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
