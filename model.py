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
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import List

from geometry import DIRECTION_LABELS, GRADES, classer_prbs


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
        """Vrai si la dégradation couvre la direction donnée."""
        if grade not in GRADES:
            return False
        # On parcourt l'arc du début à la fin dans le sens horaire
        start = self.grade_debut
        n = self.largeur_grades() // 25 + 1
        for _ in range(n):
            if start == grade:
                return True
            start = (start + 25) % 400
            if start == self.grade_fin:
                # on inclut la borne fin
                if start == grade:
                    return True
                break
        return False


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

    def extrapolation_summary(self) -> dict:
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
        """Pour chaque direction, ratio t/R = PRBS / Rayon (entre 0 et 1)."""
        R = self.rayon_tronc_cm
        if R <= 0:
            return [0.0] * 16
        return [p / R for p in self.prbs_par_grade()]

    def repartition_classes(self) -> dict:
        """Répartition des 16 directions par classe (Vert/Orange/Rouge),
        avec étendue angulaire en grades et en pourcentage du périmètre.

        Retourne un dict :
          {
            "Vert":   {"n": int, "grades": int, "pct": float},
            "Orange": {...},
            "Rouge":  {...},
            "tR_min": float,         # ratio t/R minimal sur les 16
            "tR_min_grade": int,     # grade où t/R est minimal
            "tR_min_dir": str,       # direction cardinale ou voisine
            "classe_globale": str,   # pire classe rencontrée
          }
        """
        ratios = self.ratio_tR_par_grade()
        result = {
            "Vert":   {"n": 0, "grades": 0, "pct": 0.0},
            "Orange": {"n": 0, "grades": 0, "pct": 0.0},
            "Rouge":  {"n": 0, "grades": 0, "pct": 0.0},
        }
        for i, r in enumerate(ratios):
            classe = classer_prbs(r, self.port_arbre)
            result[classe]["n"] += 1
            result[classe]["grades"] += 25  # chaque secteur fait 25 gr
        # Pourcentage du périmètre (16 secteurs = 400 gr)
        for cls in ("Vert", "Orange", "Rouge"):
            result[cls]["pct"] = 100.0 * result[cls]["grades"] / 400.0

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
        result["tR_min"] = tR_min
        result["tR_min_grade"] = grade_crit
        result["tR_min_dir"] = dir_crit

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
        result["tR_moyen"] = tR_moyen
        result["classe_globale"] = classer_prbs(tR_moyen,
                                                 self.port_arbre)
        # Pire classe ponctuelle (info complémentaire)
        if result["Rouge"]["n"] > 0:
            result["classe_pire"] = "Rouge"
        elif result["Orange"]["n"] > 0:
            result["classe_pire"] = "Orange"
        else:
            result["classe_pire"] = "Vert"
        return result


@dataclass
class Chantier:
    nom: str = "Nouvelle mission"
    adresse: str = ""
    operateur: str = ""
    date_releve: str = field(
        default_factory=lambda: datetime.now().strftime("%d/%m/%Y"))
    arbres: List[Arbre] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"nom": self.nom, "adresse": self.adresse,
                "operateur": self.operateur, "date_releve": self.date_releve,
                "arbres": [asdict(a) for a in self.arbres]}

    @classmethod
    def from_dict(cls, d: dict) -> "Chantier":
        # Mapping de migration des anciens libellés de port (v3.1 → v3.2)
        port_legacy = {
            "Libre, semi-libre ou traumatique": "libre",
            "Architecturé ou traumatique": "architecturé",
        }
        # Champs connus de chaque dataclass : permet d'ignorer
        # silencieusement un champ inconnu dans un JSON futur (ascendance
        # garantie même si on ajoute un champ côté code et qu'on revient
        # à une ancienne version de l'app, ou inversement). Sans ce
        # filtre, `Arbre(**a)` lèverait TypeError sur clé inattendue.
        arbre_fields = set(Arbre.__dataclass_fields__)
        sondage_fields = set(Sondage.__dataclass_fields__)
        deg_fields = set(DegradationExterne.__dataclass_fields__)
        cf_fields = set(Contrefort.__dataclass_fields__)

        arbres = []
        for a in d.get("arbres", []):
            # Lecture non destructive : `get`, pas `pop`. Le filtre par
            # `__dataclass_fields__` plus bas exclut de toute façon ces
            # clés du dict passé à `Arbre(**...)`, et le caller conserve
            # son dict d'origine intact (pas d'effet de bord).
            sondages = [Sondage(**{k: v for k, v in s.items()
                                    if k in sondage_fields})
                        for s in a.get("sondages", [])]
            degs = [DegradationExterne(**{k: v for k, v in dg.items()
                                           if k in deg_fields})
                    for dg in a.get("degradations_externes", [])]
            # Contreforts : ajout v3.3 — anciens fichiers → liste vide
            contreforts = [Contrefort(**{k: v for k, v in c.items()
                                          if k in cf_fields})
                           for c in a.get("contreforts", [])]
            # Migration du port si ancien format. On copie le dict pour
            # appliquer la migration sans toucher à l'entrée du caller.
            a_norm = dict(a)
            if "port_arbre" in a_norm:
                a_norm["port_arbre"] = port_legacy.get(a_norm["port_arbre"],
                                                       a_norm["port_arbre"])
            arb = Arbre(**{k: v for k, v in a_norm.items()
                           if k in arbre_fields})
            arb.sondages = sondages
            arb.degradations_externes = degs
            arb.contreforts = contreforts
            arbres.append(arb)
        c = cls(nom=d.get("nom", ""), adresse=d.get("adresse", ""),
                operateur=d.get("operateur", ""),
                date_releve=d.get("date_releve", ""))
        c.arbres = arbres
        return c
