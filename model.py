"""
Modèle de données du Pénétromètre.

Dataclasses sérialisables qui forment le cœur métier de l'application :

- `Sondage`           — une mesure ponctuelle dans une direction.
- `DegradationExterne`— un arc d'écorce dégradée.
- `Contrefort`        — un empattement à la base du tronc.
- `Arbre`             — un arbre avec ses sondages, ses dégradations et
                        ses contreforts. Porte UNIQUEMENT les
                        mutateurs de cohérence (`set_rayon`,
                        `renumeroter_*`) et la propriété d'identité
                        (`display_name`).
- `Chantier`          — une mission qui regroupe plusieurs arbres.

Module sans dépendance externe (stdlib + `geometry`). Volontairement
isolé de Tkinter, de PIL et de la couche d'export, ce qui permet à la
suite de tests unittest de couvrir la logique sans embarquer l'UI.

Les **calculs de diagnostic** (extrapolation, PRBS par grade, ratio
t/R, répartition par classe, `DiagnosticSnapshot`, lignes de résumé
textuel) vivent dans `diagnostic.py` sous forme de fonctions pures
(non-méthodes). C'est délibéré : `Arbre` redevient une dataclass de
données pure, et les renderers/exports consomment les calculs via
`from diagnostic import …` plutôt que via une méthode sur l'objet.

La persistance JSON (chargement, sauvegarde, migration de format) vit
dans `persistence.py` pour garder le modèle métier focalisé sur ses
dataclasses.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Sequence, Tuple

from geometry import GRADES

# Niveaux d'urgence d'intervention (préconisation par arbre). Ordonnés du
# plus urgent au moins urgent ; `""` (non listé) = non renseignée. Sert au
# combobox de l'onglet Diagnostic, au tri/couleur de la synthèse de mission
# et à la fiche PDF. `URGENCE_RANG` donne l'ordre de priorité (0 = plus
# urgent) pour trier la synthèse.
URGENCE_NIVEAUX = (
    "Immédiate",
    "< 6 mois",
    "< 1 an",
    "< 2 ans",
)
URGENCE_RANG = {niveau: i for i, niveau in enumerate(URGENCE_NIVEAUX)}


@dataclass
class Sondage:
    numero: int = 1
    grade: int = 0
    bois_sain_cm: float = 0.0
    bois_altere_cm: float = 0.0
    compartimentation: str = "non renseignée"
    commentaire: str = ""
    incertain: bool = False   # sondage douteux (angle, pression, accès)

    def __post_init__(self) -> None:
        if self.grade not in GRADES:
            raise ValueError(
                f"grade={self.grade} invalide (attendu: multiple de 25, 0–375)")
        self.bois_sain_cm = max(0.0, float(self.bois_sain_cm))
        self.bois_altere_cm = max(0.0, float(self.bois_altere_cm))

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
        plutôt `diagnostic.ratio_tR_par_grade(arbre)`, qui retranche la
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
    # Géométrie de la dégradation vis-à-vis de l'écorce. L'écorce n'est
    # JAMAIS du bois sain (le rayon est déjà sous écorce) — ce drapeau ne
    # règle PAS cela ; il décrit d'où part la dégradation :
    #   True  (défaut) = « comprend l'écorce » : la zone dégradée part de la
    #     surface extérieure (écorce visuellement dégradée). La part de
    #     profondeur dans la bande d'écorce ne consomme pas de bois →
    #     bois perdu = max(0, profondeur − épaisseur_écorce).
    #   False = « commence sous l'écorce » : l'écorce reste intacte, la
    #     dégradation part de la surface du bois → toute la profondeur est
    #     du bois perdu.
    # Pilote à la fois `profondeur_bois_cm` (diagnostic) et le rayon de
    # départ du dessin (`geometry.degradation_externe_outline`).
    comprend_ecorce: bool = True

    def __post_init__(self) -> None:
        if self.grade_debut not in GRADES:
            raise ValueError(
                f"grade_debut={self.grade_debut} invalide (multiple de 25, 0–375)")
        if self.grade_fin not in GRADES:
            raise ValueError(
                f"grade_fin={self.grade_fin} invalide (multiple de 25, 0–375)")
        self.profondeur_cm = max(0.0, float(self.profondeur_cm))
        self.comprend_ecorce = bool(self.comprend_ecorce)

    def profondeur_bois_cm(self, epaisseur_ecorce_cm: float = 0.0) -> float:
        """Profondeur qui consomme effectivement du **bois sain** (cm).

        Si `comprend_ecorce`, la profondeur est radiale depuis la surface
        extérieure : la bande d'écorce traversée ne réduit pas la PRBS
        (l'écorce n'est pas du bois) → on déduit son épaisseur. Sinon, la
        dégradation part de la surface du bois et toute la profondeur compte.
        Fonction pure (utilisée par le diagnostic)."""
        if self.comprend_ecorce:
            return max(0.0, self.profondeur_cm - max(0.0, epaisseur_ecorce_cm))
        return self.profondeur_cm

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


def label_brin(index: int) -> str:
    """Libellé canonique du brin d'indice `index` : « a », « b », … puis
    le rang en clair au-delà de 26 brins.

    Source unique : `Arbre._relabel_brins` s'en sert pour étiqueter, et
    les exports pour **retrouver** un libellé quand `Brin.label` est vide.
    Le champ n'est peuplé que par `ajouter_brin`/`supprimer_brin` : une
    cépée reconstruite autrement (JSON édité à la main, fixture de test)
    a des labels vides, et afficher « ? » dans un livrable au lieu de la
    position réelle du brin n'aide personne.
    """
    return chr(ord("a") + index) if index < 26 else str(index + 1)


def degradations_chevauchements(
        existantes: Sequence[DegradationExterne],
        exclure: Optional[DegradationExterne],
        grade_debut: int,
        grade_fin: int,
) -> List[Tuple[DegradationExterne, List[int]]]:
    """Dégradations existantes qui chevauchent l'arc candidat
    `grade_debut → grade_fin` (sens horaire), avec les grades partagés.

    Règle métier : les arcs ne doivent pas se chevaucher, mais deux arcs
    **mitoyens bout-à-bout** sont autorisés (la fin de l'un = le début de
    l'autre) — ces grades-frontières sont donc exclus du comptage.
    `exclure` permet d'ignorer la dégradation en cours d'édition.

    Renvoie une liste vide si l'arc candidat est valide. Partagé entre
    le dialogue `edit_degradation` et la saisie en place de l'onglet
    Dégradations (`pane_degradations`).
    """
    candidate = DegradationExterne(grade_debut=grade_debut,
                                   grade_fin=grade_fin)
    out: List[Tuple[DegradationExterne, List[int]]] = []
    for other in existantes:
        if other is exclure:
            continue
        shared = [g for g in GRADES
                  if candidate.couvre_grade(g)
                  and other.couvre_grade(g)
                  and not (g == grade_debut and g == other.grade_fin)
                  and not (g == grade_fin and g == other.grade_debut)]
        if shared:
            out.append((other, shared))
    return out


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

    def __post_init__(self) -> None:
        if self.grade_centre not in GRADES:
            raise ValueError(
                f"grade_centre={self.grade_centre} invalide "
                f"(attendu: multiple de 25, 0–375)")
        if self.largeur_grades < 0:
            raise ValueError(
                f"largeur_grades={self.largeur_grades} invalide (attendu: >= 0)")
        self.longueur_cm = max(0.0, float(self.longueur_cm))

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
class Brin:
    """Un brin (= un *ramet*) : une tige individuelle d'un arbre.

    Au sens de l'écologie des plantes clonales, un `Brin` est un **ramet** :
    une unité physiquement distincte et mécaniquement autonome. Un arbre
    ordinaire (mono-caule) est modélisé comme un genet (`Arbre`) ne portant
    qu'**un seul** brin ; une **cépée** porte plusieurs brins, chacun avec sa
    géométrie, sa cavité et sa position propres.

    Le brin porte donc tout ce qui est **physique et propre à la tige** :
    - sa géométrie (rayon, diamètre sous écorce, épaisseur d'écorce) ;
    - ses mesures (sondages, dégradations externes, contreforts) ;
    - sa **position** `(pos_x_cm, pos_y_cm)` et son orientation
      (`rotation_grades`) dans le plan du genet — (0, 0) et 0° pour un
      brin unique, centré.

    Le genet (`Arbre`) porte l'identité partagée (n° d'inventaire, essence,
    port, hauteurs, longueur de mèche) — voir `Arbre`.

    Porte UNIQUEMENT les mutateurs de cohérence (`set_rayon`,
    `renumeroter_*`). Les **calculs** (PRBS par grade, t/R, classe) restent
    dans `diagnostic.py` sous forme de fonctions pures.
    """
    label: str = ""                  # libellé du brin ("a", "b", … ; "" = unique)
    pos_x_cm: float = 0.0            # position du centre dans le plan du genet
    pos_y_cm: float = 0.0            # (0, 0) pour un brin unique, centré)
    rotation_grades: int = 0        # rotation du repère local (réservé v2)
    rayon_tronc_cm: float = 20.0
    diametre_sous_ecorce_cm: float = 0.0
    epaisseur_ecorce_cm: float = 0.0  # épaisseur radiale de l'écorce, ajoutée
    # vers l'extérieur du tronc — purement visuel, n'intervient pas dans la
    # PRBS ni le diagnostic. 0 = pas d'épaisseur (trait fin classique).
    sondages: List[Sondage] = field(default_factory=list)
    degradations_externes: List[DegradationExterne] = field(
        default_factory=list)
    contreforts: List[Contrefort] = field(default_factory=list)
    # Diamètres locaux sous écorce mesurés à certaines directions (grade →
    # diamètre cm), INDÉPENDANTS de tout sondage — une direction peut porter
    # un diamètre local sans PRBS mesurée là (p. ex. mesuré au pied à
    # coulisse pour capter un méplat entre deux sondages, sans multiplier
    # les mesures au résistographe). Fixe le rayon local de sa direction ;
    # une direction absente de la table retombe sur le rayon général
    # `rayon_tronc_cm`. Permet d'approcher la vraie forme du tronc (jamais
    # parfaitement cylindrique) sans ellipse globale — cf. `rayon_a_grade`.
    diametres_locaux: Dict[int, float] = field(default_factory=dict)

    def _rayon_locaux(self) -> Dict[int, float]:
        """Rayon local (cm) aux 16 `GRADES` canoniques.

        Un diamètre local renseigné (`diametres_locaux`) fixe le rayon de sa
        direction ; sinon la direction retombe sur le rayon général
        `rayon_tronc_cm`."""
        table: Dict[int, float] = {}
        for g in GRADES:
            d = self.diametres_locaux.get(g, 0.0)
            table[g] = d / 2.0 if d > 0 else self.rayon_tronc_cm
        return table

    @property
    def a_rayon_variable(self) -> bool:
        """Vrai si au moins une direction a un rayon local différent du rayon
        général (un sondage y porte un diamètre mesuré propre)."""
        return any(abs(r - self.rayon_tronc_cm) > 1e-9
                   for r in self._rayon_locaux().values())

    def rayon_a_grade(self, grade: float) -> float:
        """Rayon extérieur du bois (cm) dans la direction `grade`.

        Lecture exacte dans la table des 16 rayons locaux si `grade` est un
        grade canonique ; entre deux directions mesurées, **interpolation
        lissée par cosinus** (raccord à dérivée nulle à chaque direction
        mesurée — pas d'angle vif — tout en restant **strictement bornée**
        entre les deux valeurs voisines, jamais de dépassement contrairement
        à une spline) — utilisé pour le contour dessiné, échantillonné à des
        grades quelconques (`geometry.contour_polygon`)."""
        table = self._rayon_locaux()
        g = grade % 400.0
        g_int = round(g)
        if abs(g - g_int) < 1e-9 and g_int % 25 == 0:
            return table[g_int % 400]
        g_lo = (int(g // 25) * 25) % 400
        g_hi = (g_lo + 25) % 400
        r_lo, r_hi = table[g_lo], table[g_hi]
        t = (g - g_lo) / 25.0
        t_lisse = (1.0 - math.cos(math.pi * t)) / 2.0
        return r_lo + (r_hi - r_lo) * t_lisse

    def extent_cm(self) -> float:
        """Rayon d'encombrement (cm) : distance maximale du cœur du brin à sa
        surface, **écorce et contreforts compris**.

        Sert au cadrage d'une cépée : la *bounding box* d'un brin est son
        centre `(pos_x_cm, pos_y_cm)` ± `extent_cm` (cf.
        `geometry.brins_layout`). Pour une section circulaire ça vaut
        `rayon_tronc_cm + écorce + plus longue saillie de contrefort`."""
        r_max = max((self.rayon_a_grade(g) for g in GRADES),
                    default=self.rayon_tronc_cm)
        saillie = max((c.longueur_cm for c in self.contreforts), default=0.0)
        return r_max + max(0.0, self.epaisseur_ecorce_cm) + saillie

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
        self._resync_sondages_local()
        return True

    def _resync_sondages_local(self) -> None:
        """Réaligne le bois altéré (et la profondeur des dégradations) sur le
        rayon LOCAL de chaque direction, en **préservant la PRBS**.

        Sans diamètre local mesuré, le rayon local vaut `rayon_tronc_cm`
        partout → comportement strictement identique à l'ancien `set_rayon`.
        Avec un diamètre local sur certaines directions, chaque sondage est
        borné par le rayon de SA direction (`rayon_a_grade`). À appeler après
        tout changement de rayon (général ou local d'un sondage)."""
        for s in self.sondages:
            r_loc = self.rayon_a_grade(s.grade)
            s.bois_sain_cm = min(s.bois_sain_cm, r_loc)
            s.bois_altere_cm = max(0.0, r_loc - s.bois_sain_cm)
        for deg in self.degradations_externes:
            # Borne de sécurité : une dégradation qui comprend l'écorce part
            # de la surface extérieure (rayon du bois + écorce) ; sinon elle
            # part de la surface du bois (rayon seul).
            r_max = self.rayon_a_grade(deg.grade_debut)
            if deg.comprend_ecorce:
                r_max += max(0.0, self.epaisseur_ecorce_cm)
            deg.profondeur_cm = min(deg.profondeur_cm, r_max)

    def set_diametre_local(self, grade: int, diametre_cm: float) -> bool:
        """Définit (ou efface) le diamètre local sous écorce mesuré à UNE
        direction — **indépendant de tout sondage** : peut être renseigné
        même sans PRBS mesurée à cette direction (p. ex. pour modéliser un
        méplat entre deux sondages sans multiplier les mesures au
        résistographe). Réaligne le bois altéré du sondage éventuellement
        présent à cette direction — **sans jamais retoucher sa PRBS**
        (`bois_sain_cm`) : contrairement à `set_rayon` (rayon général, réglé
        une fois en amont de la saisie), le Ø local peut être ajusté après
        coup, et reclamper la PRBS ici la ferait changer à CHAQUE
        ajustement dans le cas courant (mesure locale plus étroite que le
        rayon général) — la PRBS est une mesure physique du pénétromètre,
        elle ne doit jamais bouger silencieusement. La profondeur des
        dégradations de cette même direction est bornée par sécurité (même
        principe que `_resync_sondages_local`, restreint à cette direction).

        `diametre_cm <= 0` efface l'entrée ⟹ direction « non renseignée »,
        retombe sur le rayon général. Renvoie `True` si la valeur a
        effectivement changé (l'UI rafraîchit alors les tables dépendantes
        du rayon)."""
        diametre_cm = max(0.0, diametre_cm)
        old = self.diametres_locaux.get(grade, 0.0)
        if abs(diametre_cm - old) <= 1e-9:
            return False
        if diametre_cm > 0:
            self.diametres_locaux[grade] = diametre_cm
        else:
            self.diametres_locaux.pop(grade, None)
        if self.rayon_tronc_cm > 0:
            r_loc = self.rayon_a_grade(grade)
            sondage = next((s for s in self.sondages if s.grade == grade),
                           None)
            if sondage is not None:
                sondage.bois_altere_cm = max(0.0, r_loc - sondage.bois_sain_cm)
            for deg in self.degradations_externes:
                if deg.grade_debut != grade:
                    continue
                r_max = r_loc
                if deg.comprend_ecorce:
                    r_max += max(0.0, self.epaisseur_ecorce_cm)
                deg.profondeur_cm = min(deg.profondeur_cm, r_max)
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


@dataclass
class Arbre:
    """Un arbre inventorié (= un *genet*) : l'individu génétique.

    Au sens de l'écologie des plantes clonales, un `Arbre` est un **genet** :
    tout ce qui descend d'un seul événement sexué (une graine), donc un
    génotype unique. C'est l'unité **inventoriée** (« arbre n°12 »). Il porte
    l'**identité partagée** (n° d'inventaire, essence, port, hauteurs, mèche)
    et un ou plusieurs **brins** (`Brin`, = ramets) qui portent, eux, la
    géométrie et les mesures physiques propres à chaque tige.

    Un arbre ordinaire (mono-caule) a exactement **un** brin ; une **cépée**
    en a plusieurs.

    Compatibilité : la géométrie et les mesures vivaient auparavant directement
    sur `Arbre`. Des **propriétés-relais** (`rayon_tronc_cm`, `sondages`, …) et
    des méthodes-relais (`set_rayon`, `renumeroter_*`) délèguent au **premier
    brin** (`brins[0]`) pour que le code mono-caule (panes, renderers, exports,
    diagnostic) continue de fonctionner sans changement.
    """
    numero_arbre: str = "1"
    essence: str = ""
    hauteur_sondage_cm: float = 0.0
    hauteur_arbre_m: float = 0.0
    port_arbre: str = "libre"
    meche_cm: float = 40.0   # longueur de la mèche du pénétromètre (cm)
    commentaire: str = ""
    # --- Expertise → décision (saisis dans l'onglet Diagnostic) -------
    # La classe de risque dit « quel danger » ; ces champs disent « quoi
    # faire » — c'est le livrable de l'expertise. Niveau genet (la
    # recommandation porte sur l'individu, pas sur un brin).
    urgence: str = ""        # niveau (cf. URGENCE_NIVEAUX), "" = non renseignée
    echeance: str = ""       # date limite d'intervention JJ/MM/AAAA, optionnelle
    preconisation: str = ""  # action recommandée, texte libre
    suivi_validite: str = "" # durée de validité du suivi ("1 an" … "5 ans"), "" = non renseignée
    suivi_echeance: str = "" # date de prochaine visite JJ/MM/AAAA, optionnelle
    suivi_texte: str = ""    # description du suivi, texte libre
    photos: List[str] = field(default_factory=list)  # chemins absolus des photos
    brins: List[Brin] = field(default_factory=lambda: [Brin()])

    def __init__(
        self,
        numero_arbre: str = "1",
        essence: str = "",
        hauteur_sondage_cm: float = 0.0,
        hauteur_arbre_m: float = 0.0,
        port_arbre: str = "libre",
        meche_cm: float = 40.0,
        commentaire: str = "",
        brins: "Optional[List[Brin]]" = None,
        *,
        urgence: str = "",
        echeance: str = "",
        preconisation: str = "",
        suivi_validite: str = "",
        suivi_echeance: str = "",
        suivi_texte: str = "",
        photos: "Optional[List[str]]" = None,
        # --- Compat : kwargs de géométrie/mesures hérités de l'API pré-brins.
        # Routés vers le premier brin (brins[0]) pour la compatibilité fichiers.
        rayon_tronc_cm: "Optional[float]" = None,
        diametre_sous_ecorce_cm: "Optional[float]" = None,
        epaisseur_ecorce_cm: "Optional[float]" = None,
        sondages: "Optional[List[Sondage]]" = None,
        degradations_externes: "Optional[List[DegradationExterne]]" = None,
        contreforts: "Optional[List[Contrefort]]" = None,
    ) -> None:
        # `@dataclass` n'engendre PAS d'__init__ quand la classe en définit
        # un (cf. doc dataclasses) : ces défauts doivent rester en phase avec
        # les défauts des champs déclarés ci-dessus.
        self.numero_arbre = numero_arbre
        self.essence = essence
        self.hauteur_sondage_cm = hauteur_sondage_cm
        self.hauteur_arbre_m = hauteur_arbre_m
        self.port_arbre = port_arbre
        self.meche_cm = meche_cm
        self.commentaire = commentaire
        self.urgence = urgence
        self.echeance = echeance
        self.preconisation = preconisation
        self.suivi_validite = suivi_validite
        self.suivi_echeance = suivi_echeance
        self.suivi_texte = suivi_texte
        self.photos: List[str] = list(photos) if photos is not None else []
        self.brins = list(brins) if brins is not None else [Brin()]
        b = self.brins[0]
        if rayon_tronc_cm is not None:
            b.rayon_tronc_cm = rayon_tronc_cm
        if diametre_sous_ecorce_cm is not None:
            b.diametre_sous_ecorce_cm = diametre_sous_ecorce_cm
        if epaisseur_ecorce_cm is not None:
            b.epaisseur_ecorce_cm = epaisseur_ecorce_cm
        if sondages is not None:
            b.sondages = sondages
        if degradations_externes is not None:
            b.degradations_externes = degradations_externes
        if contreforts is not None:
            b.contreforts = contreforts

    # ---- Relais de compatibilité vers le premier brin ---------------------
    # Délèguent à brins[0] pour que le code mono-caule continue de fonctionner
    # sans changement. Le brin courant de l'UI est sélectionné via App.

    @property
    def brin_courant(self) -> Brin:
        """Premier brin (brins[0]), cible des propriétés-relais de compatibilité.

        Auto-répare une liste vide issue d'une désérialisation corrompue."""
        if not self.brins:
            self.brins = [Brin()]
        return self.brins[0]

    @property
    def rayon_tronc_cm(self) -> float:
        return self.brin_courant.rayon_tronc_cm

    @rayon_tronc_cm.setter
    def rayon_tronc_cm(self, value: float) -> None:
        self.brin_courant.rayon_tronc_cm = value

    @property
    def a_rayon_variable(self) -> bool:
        return self.brin_courant.a_rayon_variable

    def rayon_a_grade(self, grade: float) -> float:
        return self.brin_courant.rayon_a_grade(grade)

    @property
    def diametre_sous_ecorce_cm(self) -> float:
        return self.brin_courant.diametre_sous_ecorce_cm

    @diametre_sous_ecorce_cm.setter
    def diametre_sous_ecorce_cm(self, value: float) -> None:
        self.brin_courant.diametre_sous_ecorce_cm = value

    @property
    def epaisseur_ecorce_cm(self) -> float:
        return self.brin_courant.epaisseur_ecorce_cm

    @epaisseur_ecorce_cm.setter
    def epaisseur_ecorce_cm(self, value: float) -> None:
        self.brin_courant.epaisseur_ecorce_cm = value

    @property
    def sondages(self) -> List[Sondage]:
        return self.brin_courant.sondages

    @sondages.setter
    def sondages(self, value: List[Sondage]) -> None:
        self.brin_courant.sondages = value

    @property
    def degradations_externes(self) -> List[DegradationExterne]:
        return self.brin_courant.degradations_externes

    @degradations_externes.setter
    def degradations_externes(self, value: List[DegradationExterne]) -> None:
        self.brin_courant.degradations_externes = value

    @property
    def contreforts(self) -> List[Contrefort]:
        return self.brin_courant.contreforts

    @contreforts.setter
    def contreforts(self, value: List[Contrefort]) -> None:
        self.brin_courant.contreforts = value

    def set_rayon(self, new_R: float) -> bool:
        """Relais : modifie le rayon du brin courant (cf. `Brin.set_rayon`)."""
        return self.brin_courant.set_rayon(new_R)

    @property
    def diametres_locaux(self) -> Dict[int, float]:
        return self.brin_courant.diametres_locaux

    @diametres_locaux.setter
    def diametres_locaux(self, value: Dict[int, float]) -> None:
        self.brin_courant.diametres_locaux = value

    def set_diametre_local(self, grade: int, diametre_cm: float) -> bool:
        """Relais : définit le diamètre local d'une direction du brin
        courant (cf. `Brin.set_diametre_local`)."""
        return self.brin_courant.set_diametre_local(grade, diametre_cm)

    def renumeroter_sondages(self) -> None:
        self.brin_courant.renumeroter_sondages()

    def renumeroter_degradations(self) -> None:
        self.brin_courant.renumeroter_degradations()

    def renumeroter_contreforts(self) -> None:
        self.brin_courant.renumeroter_contreforts()

    # ---- Gestion des brins de la cépée -----------------------------------

    def _relabel_brins(self) -> None:
        """Réétiquette les brins : `""` pour un genet mono-caule (un seul
        brin), sinon `"a"`, `"b"`, `"c"`… dans l'ordre de la liste. Appelé
        après tout ajout/suppression de brin."""
        if len(self.brins) <= 1:
            for b in self.brins:
                b.label = ""
        else:
            for i, b in enumerate(self.brins):
                b.label = label_brin(i)

    def ajouter_brin(self) -> Brin:
        """Ajoute un brin à la cépée et le renvoie.

        Le nouveau brin **hérite de la forme** du brin le plus à l'Est
        (rayon, écorce, diamètre) mais PAS de ses mesures (sondages,
        dégradations, contreforts — à relever sur la nouvelle tige, diamètres
        locaux compris). Il est placé à l'**Est** de la cépée, sans
        recouvrement (`pos_x` au-delà du bord droit + marge). Les labels sont
        remis à jour (a, b, c…)."""
        ref = self.brins[-1] if self.brins else Brin()
        nouveau = Brin(
            rayon_tronc_cm=ref.rayon_tronc_cm,
            epaisseur_ecorce_cm=ref.epaisseur_ecorce_cm,
            diametre_sous_ecorce_cm=ref.diametre_sous_ecorce_cm,
        )
        if self.brins:
            marge = 4.0
            bord_est = max(b.pos_x_cm + b.extent_cm() for b in self.brins)
            nouveau.pos_x_cm = bord_est + nouveau.extent_cm() + marge
        self.brins.append(nouveau)
        self._relabel_brins()
        return nouveau

    def supprimer_brin(self, index: int) -> bool:
        """Supprime le brin d'indice `index`. Refuse de descendre sous 1 brin
        (un genet a toujours ≥ 1 brin) ou un index hors bornes. Renvoie
        `True` si un brin a été retiré (les restants sont réétiquetés)."""
        if len(self.brins) <= 1 or not (0 <= index < len(self.brins)):
            return False
        del self.brins[index]
        self._relabel_brins()
        return True

    @property
    def display_name(self) -> str:
        """Nom affiché : 'Arbre n°X' ou 'Arbre n°X — Essence'."""
        base = f"Arbre n°{self.numero_arbre}" if self.numero_arbre else "Arbre"
        if self.essence:
            return f"{base} — {self.essence}"
        return base


@dataclass
class Chantier:
    """Mission : groupe plusieurs arbres dans une même expertise.

    Pure dataclass : la sérialisation JSON, le chargement et la
    migration de format vivent dans `persistence.py` pour rester hors
    du modèle métier.
    """
    nom: str = "Nouvelle mission"
    adresse: str = ""
    client: str = ""          # Nom du client / maître d'ouvrage
    operateur: str = ""
    date_releve: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))
    arbres: List[Arbre] = field(default_factory=list)
    # Seuils du barème EFFECTIVEMENT utilisés pour cette mission, sous la
    # forme brute JSON `[{"nom":.., "ports":[...], "vert":.., "orange":..}, ...]`
    # (un groupe par entrée — cf. `bareme.GroupeBareme`/`groupes_vers_brut`).
    # Champ **duck-typé** (liste de dicts génériques) : `model.py` ne
    # dépend pas de `bareme.py`, qui reste sous `model` dans le graphe de
    # dépendances.
    #
    # Le barème est un réglage de POSTE (`~/.penetrometre/bareme.json`) :
    # sans cette trace, rien dans le fichier ni dans le livrable ne dit
    # avec quels seuils une classe Vert/Orange/Rouge a été obtenue, et le
    # diagnostic n'est pas reproductible d'un poste à l'autre. Rempli à
    # l'enregistrement par `persistence.chantier_to_dict` ; vide pour les
    # missions antérieures à cette trace (aucune migration : l'absence
    # signifie « inconnu », ce qui est l'information juste).
    bareme_seuils: "List[Dict[str, Any]]" = field(default_factory=list)
