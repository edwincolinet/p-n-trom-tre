"""
Modèle de données du Pénétromètre.

Dataclasses sérialisables qui forment le cœur métier de l'application :

- `Sondage`           — une mesure ponctuelle dans une direction.
- `DegradationExterne`— un arc d'écorce dégradée.
- `Contrefort`        — un empattement à la base du tronc.
- `Arbre`             — un arbre avec ses sondages, ses dégradations et
                        ses contreforts ; porte la logique métier
                        d'extrapolation, de PRBS et de classification.
- `Chantier`          — une mission qui regroupe plusieurs arbres ;
                        sait se sérialiser et migrer les anciens JSON.

Module sans dépendance externe (stdlib + `geometry`). Volontairement
isolé de Tkinter, de PIL et de la couche d'export, ce qui permet à la
suite de tests unittest de couvrir la logique sans embarquer l'UI.

La persistance JSON (chargement, sauvegarde, migration de format) vit
dans `persistence.py` pour garder le modèle métier focalisé sur ses
dataclasses et sa logique d'extrapolation.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from bareme import classer_prbs
from geometry import DIRECTION_LABELS, GRADES


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
    `Arbre.repartition_classes()`. Remplace l'ancien dict fourre-tout
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

    `diagnostic_fiable` est True dès qu'au moins 2 directions sont
    sondées — seuil minimal pour que l'extrapolation linéaire ait un
    sens. En-dessous, `classe_globale` et `tR_moyen` sont calculés sur
    des valeurs majoritairement nulles et donnent un résultat
    faussement Vert : les consommateurs (UI, fiche PDF, XLSX, HTML)
    doivent masquer ces deux champs et signaler l'indisponibilité.
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

        Encapsule la règle « pas de diagnostic global si <2 sondages » :
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


@dataclass
class Sondage:
    numero: int = 1
    grade: int = 0
    bois_sain_cm: float = 0.0
    bois_altere_cm: float = 0.0
    compartimentation: str = "-"
    commentaire: str = ""

    @property
    def prbs_cm(self) -> float:
        """Paroi Résiduelle de Bois Sain (alias métier de bois_sain_cm).

        Terme utilisé dans la méthode VTA de Claus Mattheck :
        épaisseur de bois sain mesurée par le résistographe entre
        l'écorce et la zone altérée.
        """
        return self.bois_sain_cm

    def ratio_tR_brut(self, rayon_cm: float) -> float:
        """Ratio t/R *brut* (Mattheck) : PRBS / Rayon, en valeur décimale 0-1.

        Brut = ne tient PAS compte de la dégradation externe qui peut
        couvrir la direction du sondage. Pour le diagnostic, utiliser
        plutôt `Arbre.ratio_tR_par_grade()`, qui retranche la
        dégradation externe avant de calculer le ratio.

        Cette méthode reste exposée parce que l'export CSV conserve une
        colonne « t/R brut » (compat ré-analyses existantes) à côté de
        la colonne ajustée.
        """
        if rayon_cm <= 0:
            return 0.0
        return min(1.0, self.prbs_cm / rayon_cm)


@dataclass
class DegradationExterne:
    """Dégradation visible sur l'écorce : arc continu défini par un grade
    de début et un grade de fin (sens horaire), avec une profondeur radiale
    en cm depuis l'écorce vers l'intérieur.

    Exemple : "dégradation entre 50 gr et 100 gr, profondeur 3 cm" =
    arc qui couvre les directions NE→E, sur 3 cm de profondeur.
    """
    numero: int = 1
    grade_debut: int = 0       # 0 à 375 gr (inclus)
    grade_fin: int = 25        # 0 à 375 gr (inclus), sens horaire
    profondeur_cm: float = 1.0 # épaisseur radiale depuis l'écorce
    commentaire: str = ""

    def largeur_grades(self) -> int:
        """Étendue angulaire en grades (sens horaire), de 25 à 400."""
        d = (self.grade_fin - self.grade_debut) % 400
        # Si on a saisi début == fin, on considère que c'est un secteur
        # d'au moins 25 gr (la résolution minimale du dessin).
        return d if d > 0 else 25

    def largeur_cm(self, rayon_cm: float) -> float:
        """Largeur de l'arc en cm sur le périmètre (utile pour la saisie
        en cm). 1 grade = 360°/400 = 0.9° donc largeur = R × angle_rad."""
        if rayon_cm <= 0:
            return 0.0
        angle_rad = self.largeur_grades() * math.pi / 200.0
        return rayon_cm * angle_rad

    def couvre_grade(self, grade: int) -> bool:
        """Vrai si la dégradation couvre la direction donnée.

        Bornes incluses, arc parcouru dans le sens horaire avec wrap au
        grade 0. Un grade hors grille (non multiple de 25) renvoie
        toujours False — la grille n'a que 16 directions.
        """
        if grade not in GRADES:
            return False
        offset = (grade - self.grade_debut) % 400
        return offset <= self.largeur_grades()


@dataclass
class Contrefort:
    """Contrefort (empattement) : excroissance radiale à la base du tronc,
    centrée sur une orientation donnée (grade), avec une largeur angulaire
    et une longueur (saillie radiale vers l'extérieur depuis l'écorce).

    Élément purement descriptif/visuel : n'impacte ni la PRBS, ni le
    ratio t/R, ni la classification. Le sondage étant fait à
    `hauteur_sondage_cm` plus haut, le contrefort n'intervient pas dans
    le diagnostic.

    Exemple : "contrefort orienté à 100 gr (E), largeur 75 gr,
    longueur 12 cm" = bosse de 12 cm de long centrée à l'Est, large
    de 75 grades sur le pourtour.
    """
    numero: int = 1
    grade_centre: int = 0      # orientation (0 à 375 gr, par pas de 25)
    largeur_grades: int = 50   # étendue angulaire (multiple de 25)
    longueur_cm: float = 10.0  # saillie radiale vers l'extérieur (cm)
    commentaire: str = ""

    def grade_debut(self) -> int:
        """Grade de début de l'arc couvert par le contrefort (sens horaire)."""
        demi = self.largeur_grades // 2
        return (self.grade_centre - demi) % 400

    def grade_fin(self) -> int:
        """Grade de fin de l'arc couvert (sens horaire)."""
        return (self.grade_debut() + self.largeur_grades) % 400

    def largeur_cm(self, rayon_cm: float) -> float:
        """Largeur de la base du contrefort en cm sur le périmètre."""
        if rayon_cm <= 0:
            return 0.0
        angle_rad = self.largeur_grades * math.pi / 200.0
        return rayon_cm * angle_rad


@dataclass
class Arbre:
    numero_arbre: str = "1"
    essence: str = ""
    hauteur_sondage_cm: float = 0.0
    diametre_sous_ecorce_cm: float = 0.0
    hauteur_arbre_m: float = 0.0
    port_arbre: str = "libre"
    rayon_tronc_cm: float = 20.0
    meche_cm: float = 40.0   # longueur de la mèche du pénétromètre (cm)
    epaisseur_ecorce_cm: float = 0.0  # épaisseur radiale de l'écorce, ajoutée
    # vers l'extérieur du tronc — purement visuel, n'intervient pas dans la
    # PRBS ni le diagnostic. 0 = pas d'épaisseur (trait fin classique).
    sondages: List[Sondage] = field(default_factory=list)
    degradations_externes: List[DegradationExterne] = field(
        default_factory=list)
    contreforts: List[Contrefort] = field(default_factory=list)
    commentaire: str = ""

    def set_rayon(self, new_R: float) -> bool:
        """Modifie le rayon et propage la cohérence aux sondages et
        dégradations.

        Règle métier : la PRBS (`bois_sain_cm`) est la mesure physique
        du pénétromètre, on la **préserve** ; le bois altéré se
        recalcule pour rester cohérent (sain + altéré = R). Si
        `new_R < bois_sain`, la PRBS est bornée à `new_R` (cas non
        physique sinon — on ne peut pas mesurer plus de bois sain que
        le rayon).

        Idem pour les dégradations externes : la profondeur est une
        mesure physique d'épaisseur d'écorce dégradée, indépendante du
        rayon. On la borne juste à `new_R` par sécurité.

        L'ajustement n'est PAS déclenché quand l'ancien rayon vaut 0
        (cas où l'utilisateur a saisi des sondages avant de renseigner
        le rayon — on préserve les valeurs telles quelles).

        Renvoie `True` si le rayon a effectivement changé (l'UI doit
        alors rafraîchir tables sondages, dégradations et contreforts ;
        la colonne « Largeur (cm) » des contreforts dépend elle aussi
        de R, même quand il n'y a aucun sondage à ajuster). Renvoie
        `False` quand le rayon est inchangé ou que l'ancien valait 0.
        """
        new_R = max(0.0, new_R)
        old_R = self.rayon_tronc_cm
        self.rayon_tronc_cm = new_R
        if old_R <= 0 or abs(new_R - old_R) <= 1e-9:
            return False
        for s in self.sondages:
            s.bois_sain_cm = min(s.bois_sain_cm, new_R)
            s.bois_altere_cm = max(0.0, new_R - s.bois_sain_cm)
        for deg in self.degradations_externes:
            deg.profondeur_cm = min(deg.profondeur_cm, new_R)
        return True

    def renumeroter_sondages(self) -> None:
        """Renumérote les sondages 1..N selon leur position dans la liste.
        À appeler après ajout ou suppression."""
        for i, s in enumerate(self.sondages, 1):
            s.numero = i

    def renumeroter_degradations(self) -> None:
        """Renumérote les dégradations externes 1..N selon leur position."""
        for i, deg in enumerate(self.degradations_externes, 1):
            deg.numero = i

    def renumeroter_contreforts(self) -> None:
        """Renumérote les contreforts 1..N selon leur position."""
        for i, c in enumerate(self.contreforts, 1):
            c.numero = i

    @property
    def display_name(self) -> str:
        """Nom affiché : 'Arbre n°X' ou 'Arbre n°X — Essence'."""
        base = f"Arbre n°{self.numero_arbre}" if self.numero_arbre else "Arbre"
        if self.essence:
            return f"{base} — {self.essence}"
        return base

    def compute_alteration_par_grade(self) -> List[float]:
        """Calcule les 16 épaisseurs d'altération à partir des sondages :

        - directions sondées : valeur la plus défavorable des sondages,
        - directions non sondées : moyenne pondérée entre les 2 sondages
          voisins (sens horaire / anti-horaire) — uniquement s'il y a
          au moins 2 sondages. Sinon 0 (bois sain).

        Fonction pure : ne mute rien. Les appelants (renderers, exports,
        diagnostic) stockent le résultat dans une variable locale au
        moment où ils en ont besoin. Pas de cache sur l'arbre : ça
        évitait des bugs « cache périmé avant dessin ».
        """
        # Étape 1 : valeurs aux directions sondées
        measured: dict[int, float] = {}
        for s in self.sondages:
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
            next_idx = None
            for j in sorted_idx:
                if j > i:
                    next_idx = j
                    break
            if next_idx is None:
                next_idx = sorted_idx[0]  # boucle
            prev_idx = None
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

    def extrapolation_summary(self) -> Dict[str, int]:
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
        grades_sondes = sorted({s.grade for s in self.sondages
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

    def diagnostic_summary_lines(self) -> List[str]:
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

        Méthode pure, testable. Les widgets Tk sont mis à jour par
        l'appelant (`App._refresh_diag`).
        """
        if self.rayon_tronc_cm <= 0:
            return ["Renseignez le rayon du tronc et ajoutez des "
                    "sondages pour obtenir un résumé."]

        R = self.rayon_tronc_cm
        # Un seul appel à repartition_classes : le snapshot porte aussi
        # `ratios` et `extrapolation_text` pour qu'on n'ait pas à
        # rejouer `ratio_tR_par_grade` ni `extrapolation_summary_text`
        # (qui repassent par compute_alteration_par_grade et ses
        # copains).
        snap = self.repartition_classes()
        lignes: List[str] = [
            f"« {self.display_name} »",
            f"Rayon : {R:g} cm   •   Sondages : {len(self.sondages)}"
            f"   •   Dégrad. ext. : {len(self.degradations_externes)}"
            f"   •   Contreforts : {len(self.contreforts)}",
            f"Port : {self.port_arbre}",
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

        # Avec un seul sondage, l'extrapolation linéaire est désactivée
        # (cf. compute_alteration_par_grade) : 15 des 16 directions sont
        # alors supposées saines, ce qui ferait afficher faussement Vert
        # pour t/R moyen et classe globale. La propriété
        # `diagnostic_global` retourne `None` dans ce cas — un seul
        # point d'entrée à respecter (par tous les exports) au lieu de
        # tester `diagnostic_fiable` à la main.
        diag = snap.diagnostic_global
        if diag is None:
            lignes.append(
                "⚠ Diagnostic global indisponible : il faut au moins "
                "2 directions sondées pour extrapoler le pourtour.")
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

    def extrapolation_summary_text(self) -> str:
        """Phrase prête à afficher pour le diagnostic. Renvoie une
        chaîne vide si aucun sondage n'a été saisi (auquel cas le
        diagnostic affiche déjà « aucune altération »)."""
        s = self.extrapolation_summary()
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

    def degradation_externe_par_grade(self) -> List[float]:
        """Pour chaque direction (16 grades), retourne la profondeur
        maximale de dégradation externe qui couvre cette direction.
        0 si aucune dégradation ne la couvre.
        """
        out = [0.0] * 16
        for deg in self.degradations_externes:
            for i, g in enumerate(GRADES):
                if deg.couvre_grade(g):
                    out[i] = max(out[i], deg.profondeur_cm)
        return out

    def prbs_par_grade(self) -> List[float]:
        """Pour chaque direction (16 grades), retourne la PRBS réelle :
        rayon - altération interne - dégradation externe.

        C'est l'épaisseur de bois sain effectivement disponible, qui
        intègre les deux types de dégradation. Fonction pure.
        """
        R = self.rayon_tronc_cm
        if R <= 0:
            return [0.0] * 16
        alt_int = self.compute_alteration_par_grade()
        deg_ext = self.degradation_externe_par_grade()
        return [max(0.0, R - alt_int[i] - deg_ext[i]) for i in range(16)]

    def ratio_tR_par_grade(self) -> List[float]:
        """Pour chaque direction, ratio t/R = PRBS / Rayon (entre 0 et 1).

        Clamp défensif `min(1.0, …)` : `prbs_par_grade` borne déjà à
        `[0, R]`, mais on aligne explicitement le contrat de sortie sur
        `Sondage.ratio_tR_brut` (qui clampe aussi). Évite qu'un futur
        changement de `prbs_par_grade` ne fasse silencieusement dériver
        le ratio au-dessus de 1.
        """
        R = self.rayon_tronc_cm
        if R <= 0:
            return [0.0] * 16
        return [min(1.0, p / R) for p in self.prbs_par_grade()]

    def repartition_classes(self) -> DiagnosticSnapshot:
        """Construit un `DiagnosticSnapshot` self-contained pour
        l'arbre courant.

        Snapshot self-contained : la dataclass porte aussi `ratios` et
        `extrapolation_text` pour que les callers (fiche PDF,
        diagnostic Tk, XLSX/HTML) n'aient pas à rappeler
        `ratio_tR_par_grade()` ni `extrapolation_summary_text()` après —
        ce qui rejouait toute la chaîne `compute_alteration_par_grade`
        une deuxième fois pour rien.

        Voir `DiagnosticSnapshot` pour le détail du contrat (en
        particulier `diagnostic_fiable`).
        """
        ratios = self.ratio_tR_par_grade()
        # Compteurs par classe, construits localement puis figés dans
        # le dataclass à la fin.
        n_par_classe = {"Vert": 0, "Orange": 0, "Rouge": 0}
        for r in ratios:
            n_par_classe[classer_prbs(r, self.port_arbre)] += 1
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

        # Classe globale = barème Silvavenir appliqué au t/R MOYEN
        # sur les 16 directions du pourtour.
        #
        # Cette approche reflète l'état général de la section :
        # - une seule direction critique ne déclasse pas tout l'arbre,
        # - mais une dégradation répartie tire la moyenne vers le bas.
        #
        # On conserve aussi t/R minimal et la pire classe ponctuelle
        # comme indicateurs complémentaires d'alerte locale.
        tR_moyen = sum(ratios) / len(ratios) if ratios else 1.0
        classe_globale = classer_prbs(tR_moyen, self.port_arbre)
        # Pire classe ponctuelle (info complémentaire)
        if repartitions["Rouge"].n > 0:
            classe_pire = "Rouge"
        elif repartitions["Orange"].n > 0:
            classe_pire = "Orange"
        else:
            classe_pire = "Vert"

        # Fiabilité : il faut au moins 2 directions sondées pour que
        # l'extrapolation linéaire (`compute_alteration_par_grade`)
        # produise des valeurs significatives ailleurs que sur le grade
        # sondé. À n=1, les 15 autres directions sont supposées saines,
        # ce qui tire artificiellement le t/R moyen vers Vert.
        n_sondees = self.extrapolation_summary()["n_sondees"]

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
            diagnostic_fiable=n_sondees >= 2,
            extrapolation_text=self.extrapolation_summary_text(),
        )


@dataclass
class Chantier:
    """Mission : groupe plusieurs arbres dans une même expertise.

    Pure dataclass : la sérialisation JSON, le chargement et la
    migration de format vivent dans `persistence.py` pour rester hors
    du modèle métier.
    """
    nom: str = "Nouvelle mission"
    adresse: str = ""
    operateur: str = ""
    date_releve: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))
    arbres: List[Arbre] = field(default_factory=list)
