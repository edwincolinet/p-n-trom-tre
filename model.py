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
from typing import List, Optional

from geometry import GRADES


@dataclass
class Sondage:
    numero: int = 1
    grade: int = 0
    bois_sain_cm: float = 0.0
    bois_altere_cm: float = 0.0
    compartimentation: str = "non renseignée"
    commentaire: str = ""

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

    def __post_init__(self) -> None:
        if self.grade_debut not in GRADES:
            raise ValueError(
                f"grade_debut={self.grade_debut} invalide (multiple de 25, 0–375)")
        if self.grade_fin not in GRADES:
            raise ValueError(
                f"grade_fin={self.grade_fin} invalide (multiple de 25, 0–375)")
        self.profondeur_cm = max(0.0, float(self.profondeur_cm))

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

    Compatibilité (transition Étape 0) : la géométrie et les mesures vivaient
    auparavant directement sur `Arbre`. Pour ne pas réécrire les ~140 points
    d'accès du code (panes, renderers, exports, diagnostic) tant que l'UI ne
    gère qu'un brin, des **propriétés-relais** (`rayon_tronc_cm`, `sondages`,
    …) et des méthodes-relais (`set_rayon`, `renumeroter_*`) délèguent au
    **premier brin** (`brins[0]`). Ces relais sont des points de couplage
    *temporaires* — ils disparaîtront quand l'UI saura sélectionner un brin.
    """
    numero_arbre: str = "1"
    essence: str = ""
    hauteur_sondage_cm: float = 0.0
    hauteur_arbre_m: float = 0.0
    port_arbre: str = "libre"
    meche_cm: float = 40.0   # longueur de la mèche du pénétromètre (cm)
    commentaire: str = ""
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
        # --- Compat Étape 0 : kwargs de géométrie/mesures qui vivaient sur
        # `Arbre` avant l'introduction des brins. Routés vers le brin courant
        # (brins[0]). À retirer quand les appelants construiront des `Brin`.
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

    # ---- Relais de compatibilité vers le premier brin (Étape 0) ----------
    # Délèguent au brin courant (brins[0]) pour que tout le code écrit avant
    # l'introduction des cépées continue de fonctionner sans changement. À
    # retirer progressivement quand chaque appelant ciblera un brin explicite.

    @property
    def brin_courant(self) -> Brin:
        """Le brin actuellement piloté par les relais de compat (brins[0]).

        Garantit la présence d'au moins un brin (auto-réparation défensive si
        une désérialisation produisait une liste vide)."""
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

    def renumeroter_sondages(self) -> None:
        self.brin_courant.renumeroter_sondages()

    def renumeroter_degradations(self) -> None:
        self.brin_courant.renumeroter_degradations()

    def renumeroter_contreforts(self) -> None:
        self.brin_courant.renumeroter_contreforts()

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
    operateur: str = ""
    date_releve: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))
    arbres: List[Arbre] = field(default_factory=list)
