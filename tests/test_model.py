"""Tests des dataclasses métier et des fonctions de diagnostic.

Couvre :
- `Sondage.ratio_tR_brut` (cap, rayon nul).
- `DegradationExterne.largeur_grades` / `couvre_grade` (cas normal,
  wrap-around, début == fin).
- `Contrefort.grade_debut` / `grade_fin` (wrap au grade 0).
- `diagnostic.compute_alteration_par_grade` (extrapolation pondérée,
  cas 0/1/N, doublons → max).
- `diagnostic.degradation_externe_par_grade` (max sur recouvrements).
- `diagnostic.prbs_par_grade` (combinaison interne + externe + cap à 0).
- `diagnostic.repartition_classes` (compteurs, t/R minimal, classe
  globale).

Note : les fonctions de diagnostic vivent dans `diagnostic.py` depuis
le refactor de mai 2026 — auparavant méthodes sur `Arbre`, désormais
fonctions pures `f(arbre)`. Le fichier garde son nom `test_model.py`
parce qu'il couvre aussi les dataclasses (`Sondage`, `Contrefort`,
`DegradationExterne`) et que le diagnostic dépend du modèle.
"""

from __future__ import annotations

import unittest

from diagnostic import (
    arbre_compare_summary,
    comparaison_detaillee,
    compute_alteration_par_grade,
    degradation_externe_par_grade,
    diagnostic_summary_lines,
    evolution_classe,
    extrapolation_summary,
    genet_diagnostic,
    genet_summary_lines,
    mission_synthesis_rows,
    pire_classe,
    prbs_par_grade,
    ratio_tR_par_grade,
    rayon_par_grade,
    repartition_classes,
    repartition_classes_brin,
)
from geometry import GRADES
from model import (
    Arbre,
    Brin,
    Contrefort,
    DegradationExterne,
    Sondage,
    degradations_chevauchements,
)


class SondageTests(unittest.TestCase):

    def test_ratio_tR_brut_rayon_zero(self):
        s = Sondage(bois_sain_cm=5.0)
        self.assertEqual(s.ratio_tR_brut(0.0), 0.0)
        self.assertEqual(s.ratio_tR_brut(-3.0), 0.0)

    def test_ratio_tR_brut_normal(self):
        s = Sondage(bois_sain_cm=5.0)
        self.assertAlmostEqual(s.ratio_tR_brut(20.0), 0.25)

    def test_ratio_tR_brut_capped_a_1(self):
        # Si le bois sain dépasse le rayon (saisie incohérente), le
        # ratio est plafonné à 1 — pas de division aberrante.
        s = Sondage(bois_sain_cm=30.0)
        self.assertEqual(s.ratio_tR_brut(20.0), 1.0)

    def test_prbs_alias_de_bois_sain(self):
        s = Sondage(bois_sain_cm=7.5)
        self.assertEqual(s.prbs_cm, 7.5)


class DegradationExterneTests(unittest.TestCase):

    def test_largeur_simple(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        self.assertEqual(deg.largeur_grades(), 100)

    def test_largeur_wrap(self):
        # 350 → 50 dans le sens horaire = 100 gr
        deg = DegradationExterne(grade_debut=350, grade_fin=50)
        self.assertEqual(deg.largeur_grades(), 100)

    def test_largeur_debut_egal_fin_minimum_25(self):
        # Documenté : début == fin est traité comme un secteur minimal
        # de 25 gr (résolution du dessin).
        deg = DegradationExterne(grade_debut=50, grade_fin=50)
        self.assertEqual(deg.largeur_grades(), 25)

    def test_couvre_grade_couvre_les_bornes(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        for g in (0, 25, 50, 75, 100):
            with self.subTest(g=g):
                self.assertTrue(deg.couvre_grade(g))

    def test_couvre_grade_exclut_l_exterieur(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        for g in (125, 200, 375):
            with self.subTest(g=g):
                self.assertFalse(deg.couvre_grade(g))

    def test_couvre_grade_wrap_around(self):
        deg = DegradationExterne(grade_debut=350, grade_fin=50)
        for g in (350, 375, 0, 25, 50):
            with self.subTest(g=g):
                self.assertTrue(deg.couvre_grade(g))
        for g in (75, 325):
            with self.subTest(g=g):
                self.assertFalse(deg.couvre_grade(g))

    def test_couvre_grade_hors_resolution(self):
        # Grade non multiple de 25 → toujours False (hors grille).
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        self.assertFalse(deg.couvre_grade(30))
        self.assertFalse(deg.couvre_grade(99))

    def test_largeur_cm_proportionnelle_au_rayon(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)  # 100 gr
        # 100 gr = π/2 rad → largeur = R × π/2
        self.assertAlmostEqual(deg.largeur_cm(20.0), 20.0 * 3.141592653589793 / 2)
        self.assertEqual(deg.largeur_cm(0.0), 0.0)

    def test_profondeur_bois_deduit_ecorce_par_defaut(self):
        # Mesurée depuis l'écorce (défaut) : la part dans l'écorce ne
        # consomme pas de bois sain.
        deg = DegradationExterne(profondeur_cm=2.0)
        self.assertTrue(deg.comprend_ecorce)
        self.assertAlmostEqual(deg.profondeur_bois_cm(1.5), 0.5)
        # Profondeur entièrement dans l'écorce → aucun bois perdu.
        self.assertEqual(deg.profondeur_bois_cm(3.0), 0.0)
        # Sans écorce → profondeur brute.
        self.assertEqual(deg.profondeur_bois_cm(0.0), 2.0)

    def test_profondeur_bois_plein_bois_ignore_ecorce(self):
        # Décochée : toute la profondeur compte (ancien comportement).
        deg = DegradationExterne(profondeur_cm=2.0, comprend_ecorce=False)
        self.assertEqual(deg.profondeur_bois_cm(1.5), 2.0)


class DegradationsChevauchementsTests(unittest.TestCase):
    """Helper pur de non-chevauchement, partagé entre le dialogue
    `edit_degradation` et la saisie en place de `pane_degradations`."""

    def test_arc_disjoint_valide(self):
        existantes = [DegradationExterne(grade_debut=0, grade_fin=50)]
        self.assertEqual(
            degradations_chevauchements(existantes, None, 100, 150), [])

    def test_chevauchement_detecte_avec_grades_partages(self):
        existantes = [DegradationExterne(numero=1,
                                         grade_debut=0, grade_fin=100)]
        conflits = degradations_chevauchements(existantes, None, 75, 150)
        self.assertEqual(len(conflits), 1)
        other, shared = conflits[0]
        self.assertIs(other, existantes[0])
        self.assertEqual(shared, [75, 100])

    def test_mitoyen_bout_a_bout_autorise(self):
        # La fin de l'un = le début de l'autre : grades-frontières exclus.
        existantes = [DegradationExterne(grade_debut=0, grade_fin=50)]
        self.assertEqual(
            degradations_chevauchements(existantes, None, 50, 100), [])
        # Et dans l'autre sens (le candidat finit où l'existant commence).
        self.assertEqual(
            degradations_chevauchements(existantes, None, 350, 0), [])

    def test_exclure_ignore_la_degradation_en_cours_d_edition(self):
        deg = DegradationExterne(grade_debut=0, grade_fin=100)
        # Réduire l'arc de `deg` lui-même ne doit pas se voir en conflit.
        self.assertEqual(
            degradations_chevauchements([deg], deg, 0, 50), [])

    def test_wrap_au_grade_zero(self):
        existantes = [DegradationExterne(grade_debut=350, grade_fin=50)]
        conflits = degradations_chevauchements(existantes, None, 0, 100)
        self.assertEqual(len(conflits), 1)


class FusionEcreteeTests(unittest.TestCase):
    """Garde-fou fusion : altération centrale + dégradation externe ne
    peuvent pas physiquement dépasser le rayon — `prbs_par_grade` écrête
    à 0 et ces helpers signalent les directions/dégradations concernées."""

    def _brin(self, sain: float, prof: float) -> Brin:
        b = Brin(rayon_tronc_cm=30.0)
        b.sondages.append(Sondage(numero=1, grade=0, bois_sain_cm=sain,
                                  bois_altere_cm=30.0 - sain))
        b.degradations_externes.append(DegradationExterne(
            numero=1, grade_debut=375, grade_fin=25, profondeur_cm=prof))
        return b

    def test_ecretage_detecte_quand_profondeur_depasse_le_sain(self):
        from diagnostic import fusion_ecretee_par_grade, prbs_par_grade
        b = self._brin(sain=5.0, prof=7.0)  # 25 altéré + 7 ext = 32 > 30
        self.assertTrue(fusion_ecretee_par_grade(b)[0])
        self.assertEqual(prbs_par_grade(b)[0], 0.0)

    def test_pas_d_ecretage_quand_la_somme_tient_dans_le_rayon(self):
        from diagnostic import fusion_ecretee_par_grade
        b = self._brin(sain=10.0, prof=7.0)  # 20 + 7 = 27 <= 30
        self.assertFalse(any(fusion_ecretee_par_grade(b)))

    def test_profondeur_superieure_au_rayon_sans_sondage(self):
        from diagnostic import fusion_ecretee_par_grade
        b = Brin(rayon_tronc_cm=30.0)
        b.degradations_externes.append(DegradationExterne(
            numero=1, grade_debut=0, grade_fin=50, profondeur_cm=35.0))
        self.assertTrue(fusion_ecretee_par_grade(b)[0])

    def test_rayon_nul_jamais_ecrete(self):
        from diagnostic import fusion_ecretee_par_grade
        b = Brin(rayon_tronc_cm=0.0)
        b.degradations_externes.append(DegradationExterne(
            numero=1, grade_debut=0, grade_fin=50, profondeur_cm=5.0))
        self.assertFalse(any(fusion_ecretee_par_grade(b)))

    def test_degradation_ecretee_ne_marque_pas_la_voisine_mitoyenne(self):
        from diagnostic import degradation_ecretee
        b = self._brin(sain=5.0, prof=7.0)  # arc 375→25, écrêté
        # Arc mitoyen bout-à-bout (25→75), peu profond : partage le
        # grade-frontière 25 mais ne doit PAS être marqué.
        voisine = DegradationExterne(numero=2, grade_debut=25,
                                     grade_fin=75, profondeur_cm=1.0)
        b.degradations_externes.append(voisine)
        self.assertTrue(degradation_ecretee(b, b.degradations_externes[0]))
        self.assertFalse(degradation_ecretee(b, voisine))


class ContrefortTests(unittest.TestCase):

    def test_grade_debut_fin_normal(self):
        c = Contrefort(grade_centre=200, largeur_grades=100)
        self.assertEqual(c.grade_debut(), 150)
        self.assertEqual(c.grade_fin(), 250)

    def test_grade_debut_fin_wrap(self):
        c = Contrefort(grade_centre=0, largeur_grades=50)
        self.assertEqual(c.grade_debut(), 375)
        self.assertEqual(c.grade_fin(), 25)

    def test_largeur_cm_proportionnelle(self):
        c = Contrefort(grade_centre=0, largeur_grades=200)  # demi-pourtour
        # 200 gr = π rad → R × π
        self.assertAlmostEqual(c.largeur_cm(10.0), 10.0 * 3.141592653589793)


class ValidationTests(unittest.TestCase):
    """Vérifie que __post_init__ rejette les valeurs incohérentes."""

    def test_sondage_grade_invalide(self):
        with self.assertRaises(ValueError):
            Sondage(grade=30)  # pas multiple de 25
        with self.assertRaises(ValueError):
            Sondage(grade=400)  # hors plage
        with self.assertRaises(ValueError):
            Sondage(grade=-25)

    def test_sondage_clamp_negatifs(self):
        s = Sondage(bois_sain_cm=-5.0, bois_altere_cm=-2.0)
        self.assertEqual(s.bois_sain_cm, 0.0)
        self.assertEqual(s.bois_altere_cm, 0.0)

    def test_degradation_grade_invalide(self):
        with self.assertRaises(ValueError):
            DegradationExterne(grade_debut=30, grade_fin=100)
        with self.assertRaises(ValueError):
            DegradationExterne(grade_debut=0, grade_fin=401)

    def test_degradation_profondeur_clampee(self):
        deg = DegradationExterne(profondeur_cm=-3.0)
        self.assertEqual(deg.profondeur_cm, 0.0)

    def test_contrefort_grade_centre_hors_plage(self):
        with self.assertRaises(ValueError):
            Contrefort(grade_centre=400)
        with self.assertRaises(ValueError):
            Contrefort(grade_centre=-1)

    def test_contrefort_grade_centre_pas_multiple_de_25(self):
        with self.assertRaises(ValueError):
            Contrefort(grade_centre=13)
        with self.assertRaises(ValueError):
            Contrefort(grade_centre=120)

    def test_contrefort_largeur_negative(self):
        with self.assertRaises(ValueError):
            Contrefort(largeur_grades=-25)

    def test_contrefort_longueur_clampee(self):
        c = Contrefort(longueur_cm=-5.0)
        self.assertEqual(c.longueur_cm, 0.0)


class ComputeAlterationTests(unittest.TestCase):

    def _new_arbre(self) -> Arbre:
        return Arbre(rayon_tronc_cm=20.0)

    def test_aucun_sondage_donne_zeros(self):
        a = self._new_arbre()
        self.assertEqual(compute_alteration_par_grade(a), [0.0] * 16)

    def test_un_seul_sondage_pas_d_extrapolation(self):
        # Documenté : moins de 2 sondages → on garde la mesure ponctuelle
        # et on laisse les autres à 0 (pas assez d'info pour extrapoler).
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_sain_cm=15.0,
                                   bois_altere_cm=5.0))
        alt = compute_alteration_par_grade(a)
        self.assertEqual(alt[0], 5.0)
        self.assertEqual(sum(alt[1:]), 0.0)

    def test_deux_sondages_opposes_donnent_moyenne_ponderee(self):
        # Sondage à 0 gr (idx 0) avec altéré=4, sondage à 200 gr (idx 8)
        # avec altéré=8. Au milieu (100 gr, idx 4) : équidistant des
        # deux → moyenne arithmétique 6.
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_altere_cm=4.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=8.0))
        alt = compute_alteration_par_grade(a)
        self.assertAlmostEqual(alt[0], 4.0)
        self.assertAlmostEqual(alt[8], 8.0)
        # Milieu (idx 4) entre idx 0 et idx 8 : (4+8)/2 = 6
        self.assertAlmostEqual(alt[4], 6.0)
        # idx 2 : 2 crans de 0, 6 crans de 8 → 4*0.75 + 8*0.25 = 5
        self.assertAlmostEqual(alt[2], 5.0)

    def test_doublon_au_meme_grade_le_pire_gagne(self):
        # Si plusieurs sondages au même grade, on garde la valeur
        # la plus défavorable (max d'altération).
        a = self._new_arbre()
        a.sondages.append(Sondage(grade=0, bois_altere_cm=3.0))
        a.sondages.append(Sondage(grade=0, bois_altere_cm=7.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=2.0))
        alt = compute_alteration_par_grade(a)
        self.assertAlmostEqual(alt[0], 7.0)


class DegradationExterneParGradeTests(unittest.TestCase):

    def test_aucune_degradation_donne_zeros(self):
        a = Arbre(rayon_tronc_cm=20.0)
        self.assertEqual(degradation_externe_par_grade(a), [0.0] * 16)

    def test_une_degradation_couvre_les_grades_attendus(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=50, grade_fin=100,
                                profondeur_cm=2.0))
        out = degradation_externe_par_grade(a)
        # 50, 75, 100 → couverts ; ailleurs → 0
        self.assertAlmostEqual(out[GRADES.index(50)], 2.0)
        self.assertAlmostEqual(out[GRADES.index(75)], 2.0)
        self.assertAlmostEqual(out[GRADES.index(100)], 2.0)
        self.assertEqual(out[GRADES.index(0)], 0.0)
        self.assertEqual(out[GRADES.index(125)], 0.0)

    def test_deux_degradations_qui_se_recouvrent_donnent_le_max(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=100,
                                profondeur_cm=1.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=50, grade_fin=150,
                                profondeur_cm=3.0))
        out = degradation_externe_par_grade(a)
        # Recouvrement à 50, 75, 100 → max(1, 3) = 3
        for g in (50, 75, 100):
            self.assertAlmostEqual(out[GRADES.index(g)], 3.0)
        # Hors recouvrement de la deuxième
        self.assertAlmostEqual(out[GRADES.index(0)], 1.0)
        self.assertAlmostEqual(out[GRADES.index(125)], 3.0)


class PrbsParGradeTests(unittest.TestCase):

    def test_arbre_sans_alteration_ni_degradation(self):
        a = Arbre(rayon_tronc_cm=20.0)
        self.assertEqual(prbs_par_grade(a), [20.0] * 16)

    def test_alteration_interne_seule(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        out = prbs_par_grade(a)
        # Aux deux directions sondées : 20 - 5 = 15
        self.assertAlmostEqual(out[0], 15.0)
        self.assertAlmostEqual(out[8], 15.0)

    def test_degradation_externe_seule(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=2.0))
        out = prbs_par_grade(a)
        self.assertAlmostEqual(out[0], 18.0)

    def test_alteration_et_degradation_se_cumulent(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=2.0))
        out = prbs_par_grade(a)
        # 20 - 5 (interne) - 2 (externe) = 13 au grade 0
        self.assertAlmostEqual(out[0], 13.0)

    def test_prbs_jamais_negative(self):
        # Si interne + externe dépasse le rayon, la PRBS est plafonnée à 0
        # (pas de bois sain négatif).
        a = Arbre(rayon_tronc_cm=10.0)
        a.sondages.append(Sondage(grade=0, bois_altere_cm=8.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=8.0))
        a.degradations_externes.append(
            DegradationExterne(grade_debut=0, grade_fin=0,
                                profondeur_cm=5.0))
        out = prbs_par_grade(a)
        self.assertEqual(out[0], 0.0)

    def test_rayon_zero_donne_zeros(self):
        a = Arbre(rayon_tronc_cm=0.0)
        self.assertEqual(prbs_par_grade(a), [0.0] * 16)

    def test_arbre_n_expose_plus_de_cache_alteration(self):
        # Verrou : le cache `alteration_par_grade` a été retiré. Toute
        # tentative de le restaurer doit être détectée — il rouvrirait
        # le piège « cache périmé avant dessin » qui motivait sa
        # suppression. Source de vérité unique :
        # `compute_alteration_par_grade()`.
        self.assertNotIn("alteration_par_grade",
                         Arbre.__dataclass_fields__)
        self.assertFalse(hasattr(Arbre, "recompute_alteration_from_sondages"))


class SectionOvaleTests(unittest.TestCase):
    """Section ovale (ellipse) — Étape 1 : rayon et t/R par direction."""

    def test_section_circulaire_par_defaut(self):
        # rayon_petit_axe_cm == 0 ⟹ circulaire : rayon constant partout.
        a = Arbre(rayon_tronc_cm=30.0)
        self.assertFalse(a.est_ovale)
        self.assertEqual(rayon_par_grade(a), [30.0] * 16)

    def test_petit_axe_egal_grand_reste_circulaire(self):
        a = Arbre(rayon_tronc_cm=30.0)
        a.rayon_petit_axe_cm = 30.0
        self.assertFalse(a.est_ovale)
        self.assertEqual(rayon_par_grade(a), [30.0] * 16)

    def test_rayon_par_grade_suit_l_ellipse(self):
        # Grand axe 30 (N-S, orientation 0), petit axe 18 (E-O).
        a = Arbre(rayon_tronc_cm=30.0)
        a.rayon_petit_axe_cm = 18.0
        self.assertTrue(a.est_ovale)
        rayons = rayon_par_grade(a)
        self.assertAlmostEqual(rayons[0], 30.0)   # N (grand axe)
        self.assertAlmostEqual(rayons[8], 30.0)   # S (grand axe)
        self.assertAlmostEqual(rayons[4], 18.0)   # E (petit axe)
        self.assertAlmostEqual(rayons[12], 18.0)  # O (petit axe)

    def test_tR_local_par_direction_sur_ovale(self):
        # À PRBS identique (10 cm) sur grand et petit axe, le t/R est PLUS
        # FAVORABLE sur le petit axe (rayon plus court) — apport métier
        # de l'Étape 1 : chaque direction rapportée à son propre rayon.
        a = Arbre(rayon_tronc_cm=30.0)
        a.rayon_petit_axe_cm = 18.0
        # bois_altere tel que PRBS = rayon_local - alteration = 10 partout
        # N (grand axe, R=30) : altération 20 → PRBS 10 → t/R = 10/30
        a.sondages.append(Sondage(grade=0, bois_altere_cm=20.0))
        # E (petit axe, R=18) : altération 8 → PRBS 10 → t/R = 10/18
        a.sondages.append(Sondage(grade=100, bois_altere_cm=8.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=20.0))
        ratios = ratio_tR_par_grade(a)
        self.assertAlmostEqual(ratios[0], 10.0 / 30.0, places=4)
        self.assertAlmostEqual(ratios[4], 10.0 / 18.0, places=4)
        self.assertGreater(ratios[4], ratios[0])

    def test_rayon_tronc_reste_le_demi_grand_axe(self):
        # Compat : rayon_tronc_cm garde son sens (= le plus grand rayon),
        # ce que lisent les exports/synthèse comme « rayon représentatif ».
        a = Arbre(rayon_tronc_cm=30.0)
        a.rayon_petit_axe_cm = 18.0
        self.assertEqual(a.rayon_tronc_cm, 30.0)
        self.assertEqual(max(rayon_par_grade(a)), 30.0)

    def test_set_forme_ovale_realigne_altere_et_preserve_prbs(self):
        # Tronc circulaire R=30 avec un sondage à l'E (grade 100) :
        # PRBS=10, altéré=20. On passe en ovale petit axe 18 à l'E.
        a = Arbre(rayon_tronc_cm=30.0)
        a.sondages.append(Sondage(grade=100, bois_sain_cm=10.0,
                                   bois_altere_cm=20.0))
        changed = a.set_forme_ovale(18.0, 0)
        self.assertTrue(changed)
        s = a.sondages[0]
        # PRBS (mesure physique) inchangée…
        self.assertAlmostEqual(s.bois_sain_cm, 10.0)
        # …mais l'altéré se réaligne sur le rayon LOCAL (18 à l'E) : 18-10=8.
        self.assertAlmostEqual(s.bois_altere_cm, 8.0)

    def test_set_forme_ovale_clampe_prbs_au_rayon_local(self):
        # Si la PRBS dépasse le petit axe, elle est bornée au rayon local.
        a = Arbre(rayon_tronc_cm=30.0)
        a.sondages.append(Sondage(grade=100, bois_sain_cm=25.0,
                                   bois_altere_cm=5.0))
        a.set_forme_ovale(18.0, 0)
        s = a.sondages[0]
        self.assertAlmostEqual(s.bois_sain_cm, 18.0)   # borné au rayon E
        self.assertAlmostEqual(s.bois_altere_cm, 0.0)

    def test_set_forme_ovale_inchange_renvoie_false(self):
        a = Arbre(rayon_tronc_cm=30.0)
        a.set_forme_ovale(18.0, 0)
        self.assertFalse(a.set_forme_ovale(18.0, 0))

    def test_set_forme_ovale_zero_revient_circulaire(self):
        a = Arbre(rayon_tronc_cm=30.0)
        a.set_forme_ovale(18.0, 0)
        self.assertTrue(a.est_ovale)
        a.set_forme_ovale(0.0, 0)
        self.assertFalse(a.est_ovale)
        self.assertEqual(rayon_par_grade(a), [30.0] * 16)


class SetRayonTests(unittest.TestCase):
    """Règle métier : quand le rayon change, la PRBS (mesure physique
    du pénétromètre) est préservée et le bois altéré est recalculé."""

    def test_augmentation_du_rayon_augmente_le_bois_altere(self):
        # PRBS = 5 cm mesurée. R passe de 20 à 25 → altéré passe de 15 à 20.
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(bois_sain_cm=5.0, bois_altere_cm=15.0))
        changed = a.set_rayon(25.0)
        self.assertTrue(changed)
        self.assertEqual(a.rayon_tronc_cm, 25.0)
        self.assertEqual(a.sondages[0].bois_sain_cm, 5.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 20.0)

    def test_diminution_du_rayon_diminue_le_bois_altere(self):
        # PRBS = 5 cm. R passe de 20 à 12 → altéré passe de 15 à 7.
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(bois_sain_cm=5.0, bois_altere_cm=15.0))
        changed = a.set_rayon(12.0)
        self.assertTrue(changed)
        self.assertEqual(a.sondages[0].bois_sain_cm, 5.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 7.0)

    def test_rayon_inferieur_a_la_prbs_borne_la_prbs(self):
        # Cas non physique : PRBS = 18 et R nouveau = 10 → PRBS bornée
        # à 10, altéré = 0.
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(bois_sain_cm=18.0, bois_altere_cm=2.0))
        changed = a.set_rayon(10.0)
        self.assertTrue(changed)
        self.assertEqual(a.sondages[0].bois_sain_cm, 10.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 0.0)

    def test_profondeur_degradation_externe_bornee_au_rayon(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(profondeur_cm=8.0))
        a.set_rayon(5.0)
        self.assertEqual(a.degradations_externes[0].profondeur_cm, 5.0)

    def test_profondeur_degradation_externe_preservee_si_dans_le_rayon(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.degradations_externes.append(
            DegradationExterne(profondeur_cm=3.0))
        a.set_rayon(30.0)
        self.assertEqual(a.degradations_externes[0].profondeur_cm, 3.0)

    def test_rayon_identique_ne_modifie_rien(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(bois_sain_cm=5.0, bois_altere_cm=15.0))
        changed = a.set_rayon(20.0)
        self.assertFalse(changed)
        self.assertEqual(a.sondages[0].bois_sain_cm, 5.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 15.0)

    def test_rayon_initial_zero_ne_declenche_pas_l_ajustement(self):
        # Cas où l'utilisateur a saisi des sondages avant d'avoir
        # renseigné le rayon. On préserve les valeurs telles quelles —
        # set_rayon ne les écrase pas même si la nouvelle valeur diffère.
        a = Arbre(rayon_tronc_cm=0.0)
        a.sondages.append(Sondage(bois_sain_cm=7.0, bois_altere_cm=3.0))
        changed = a.set_rayon(20.0)
        self.assertFalse(changed)
        self.assertEqual(a.rayon_tronc_cm, 20.0)
        self.assertEqual(a.sondages[0].bois_sain_cm, 7.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 3.0)

    def test_rayon_negatif_est_borne_a_zero(self):
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(bois_sain_cm=5.0, bois_altere_cm=15.0))
        a.set_rayon(-3.0)
        self.assertEqual(a.rayon_tronc_cm, 0.0)
        # Sondages remis à zéro car bornés au nouveau rayon nul.
        self.assertEqual(a.sondages[0].bois_sain_cm, 0.0)
        self.assertEqual(a.sondages[0].bois_altere_cm, 0.0)

    def test_sans_sondages_ni_degradations(self):
        # Pas de sondage ni de dégradation à ajuster mais le rayon a
        # changé : on signale True pour que l'UI rafraîchisse la table
        # contreforts (la colonne "Largeur (cm)" dépend de R).
        a = Arbre(rayon_tronc_cm=20.0)
        changed = a.set_rayon(15.0)
        self.assertTrue(changed)
        self.assertEqual(a.rayon_tronc_cm, 15.0)


class RepartitionClassesTests(unittest.TestCase):

    def test_arbre_sain_tout_vert(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        snap = repartition_classes(a)
        self.assertEqual(snap.vert.n, 16)
        self.assertEqual(snap.orange.n, 0)
        self.assertEqual(snap.rouge.n, 0)
        self.assertEqual(snap.classe_globale, "Vert")
        self.assertEqual(snap.vert.grades, 400)
        self.assertAlmostEqual(snap.vert.pct, 100.0)

    def test_classe_globale_basee_sur_le_tR_moyen(self):
        # On crée 2 sondages opposés très altérés : le t/R moyen tombe
        # bas → classe globale Rouge même si certaines directions
        # extrapolées peuvent être Orange.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=18.0))
        snap = repartition_classes(a)
        # PRBS partout = 20 - 18 = 2 (extrapolé identique partout)
        # t/R = 0.10 < 0.15 → Rouge sur tout le pourtour
        self.assertEqual(snap.rouge.n, 16)
        self.assertEqual(snap.classe_globale, "Rouge")
        self.assertAlmostEqual(snap.tR_moyen, 0.10)

    def test_tR_min_localise_sur_la_pire_direction(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        # Direction 100 gr est la plus dégradée
        a.sondages.append(Sondage(grade=0, bois_altere_cm=2.0))
        a.sondages.append(Sondage(grade=100, bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=2.0))
        snap = repartition_classes(a)
        self.assertEqual(snap.tR_min_grade, 100)

    def test_pct_grades_n_coherent(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        snap = repartition_classes(a)
        total_n = sum(snap.par_classe(c).n
                      for c in ("Vert", "Orange", "Rouge"))
        total_grades = sum(snap.par_classe(c).grades
                           for c in ("Vert", "Orange", "Rouge"))
        total_pct = sum(snap.par_classe(c).pct
                        for c in ("Vert", "Orange", "Rouge"))
        self.assertEqual(total_n, 16)
        self.assertEqual(total_grades, 400)
        self.assertAlmostEqual(total_pct, 100.0)

    def test_diagnostic_non_fiable_avec_deux_sondages(self):
        # Seuil métier porté à 3 : 2 sondages ne suffisent plus à publier
        # un diagnostic global fiable (la cavité reste extrapolée, mais
        # t/R moyen + classe globale sont masqués).
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        snap = repartition_classes(a)
        self.assertEqual(snap.n_sondees, 2)
        self.assertFalse(snap.diagnostic_fiable)

    def test_diagnostic_fiable_avec_trois_sondages(self):
        # Dès n_sondees >= 3 → diagnostic_fiable = True.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=100, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        snap = repartition_classes(a)
        self.assertEqual(snap.n_sondees, 3)
        self.assertTrue(snap.diagnostic_fiable)

    def test_diagnostic_non_fiable_avec_un_seul_sondage(self):
        # n_sondees == 1 → l'extrapolation est désactivée (15 directions
        # supposées saines), la classe globale serait faussement Verte.
        # Le flag protège les consommateurs (UI, PDF, XLSX, HTML).
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=18.0))
        snap = repartition_classes(a)
        self.assertEqual(snap.n_sondees, 1)
        self.assertFalse(snap.diagnostic_fiable)

    def test_diagnostic_non_fiable_sans_sondage(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        snap = repartition_classes(a)
        self.assertEqual(snap.n_sondees, 0)
        self.assertFalse(snap.diagnostic_fiable)

    def test_diagnostic_global_none_si_non_fiable(self):
        # Verrouille la règle : tant que <3 directions sondées,
        # diagnostic_global doit renvoyer None pour que les exports
        # (PDF, XLSX, HTML, Tk) n'aient qu'un seul point d'entrée à
        # respecter au lieu de tester diagnostic_fiable à la main.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=18.0))
        snap = repartition_classes(a)
        self.assertIsNone(snap.diagnostic_global)

    def test_diagnostic_global_tuple_si_fiable(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=2.0))
        a.sondages.append(Sondage(grade=100, bois_altere_cm=2.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=2.0))
        snap = repartition_classes(a)
        diag = snap.diagnostic_global
        self.assertIsNotNone(diag)
        # Décomposition tuple — le contrat est (tR_moyen, classe_globale)
        assert diag is not None
        tR_moyen, classe_globale = diag
        self.assertAlmostEqual(tR_moyen, snap.tR_moyen)
        self.assertEqual(classe_globale, snap.classe_globale)


class ExtrapolationSummaryTests(unittest.TestCase):
    """Indicateurs de fiabilité de l'extrapolation (`Arbre.extrapolation_summary`)."""

    def test_aucun_sondage(self):
        a = Arbre(rayon_tronc_cm=20.0)
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 0)
        self.assertEqual(s["n_extrapolees"], 16)
        self.assertEqual(s["ecart_max_grades"], 0)

    def test_un_seul_sondage_ecart_max_400(self):
        # 1 seul sondage : aucun voisin → l'arc à extrapoler fait le
        # tour complet (400 gr). Convention : ecart_max == 400.
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 1)
        self.assertEqual(s["n_extrapolees"], 15)
        self.assertEqual(s["ecart_max_grades"], 400)

    def test_deux_sondages_opposes(self):
        # Sondages à 0 et 200 gr → écart max = 200 gr (un demi-pourtour
        # à extrapoler de part et d'autre).
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0))
        a.sondages.append(Sondage(grade=200))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 2)
        self.assertEqual(s["ecart_max_grades"], 200)

    def test_quatre_sondages_repartis(self):
        # Sondages à 0, 100, 200, 300 gr → écart max = 100 gr partout.
        a = Arbre(rayon_tronc_cm=20.0)
        for g in (0, 100, 200, 300):
            a.sondages.append(Sondage(grade=g))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 4)
        self.assertEqual(s["ecart_max_grades"], 100)

    def test_seize_sondages_complets(self):
        # 16 sondages → 25 gr d'écart partout (pas d'extrapolation).
        a = Arbre(rayon_tronc_cm=20.0)
        for g in GRADES:
            a.sondages.append(Sondage(grade=g))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 16)
        self.assertEqual(s["n_extrapolees"], 0)
        self.assertEqual(s["ecart_max_grades"], 25)

    def test_doublon_au_meme_grade_compte_une_seule_direction(self):
        # Deux sondages au même grade ne comptent que pour 1 direction
        # sondée — ils ne diminuent pas l'écart à extrapoler ailleurs.
        a = Arbre(rayon_tronc_cm=20.0)
        a.sondages.append(Sondage(grade=0))
        a.sondages.append(Sondage(grade=0))
        a.sondages.append(Sondage(grade=200))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 2)
        self.assertEqual(s["ecart_max_grades"], 200)

    def test_repartition_inegale_ecart_max_correct(self):
        # Sondages à 0, 25, 50 gr (concentrés en quart Nord). L'écart
        # max est entre 50 et 0 dans le sens horaire = 350 gr.
        a = Arbre(rayon_tronc_cm=20.0)
        for g in (0, 25, 50):
            a.sondages.append(Sondage(grade=g))
        s = extrapolation_summary(a)
        self.assertEqual(s["n_sondees"], 3)
        self.assertEqual(s["ecart_max_grades"], 350)


class DiagnosticSummaryLinesTests(unittest.TestCase):
    """Tests du résumé textuel utilisé par le panneau Diagnostic et par
    les exports."""

    def test_rayon_nul_renvoie_message_d_aide(self):
        a = Arbre(rayon_tronc_cm=0.0)
        lines = diagnostic_summary_lines(a)
        self.assertEqual(len(lines), 1)
        self.assertIn("rayon", lines[0].lower())

    def test_sans_sondage_signale_aucune_alteration(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        lines = diagnostic_summary_lines(a)
        joined = "\n".join(lines)
        self.assertIn("Aucune altération", joined)
        # Pas de répartition Vert/Orange/Rouge dans ce cas
        self.assertNotIn("Répartition", joined)

    def test_avec_alteration_inclut_classe_globale_et_repartition(self):
        # 3 sondages : seuil de fiabilité atteint → la répartition et la
        # classe globale sont publiées dans le résumé.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_sain_cm=2.0,
                                    bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=100, bois_sain_cm=2.0,
                                    bois_altere_cm=18.0))
        a.sondages.append(Sondage(grade=200, bois_sain_cm=2.0,
                                    bois_altere_cm=18.0))
        lines = diagnostic_summary_lines(a)
        joined = "\n".join(lines)
        # En-tête présent
        self.assertIn("Rayon : 20", joined)
        # Direction critique listée
        self.assertIn("t/R minimal", joined)
        # Répartition présente
        self.assertIn("Répartition", joined)
        # Classe globale finale (avec arbre très altéré → Rouge)
        self.assertIn("Classe globale", joined)
        self.assertIn("Rouge", joined)

    def test_inclut_extrapolation_summary_text_si_partiel(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=5.0))
        a.sondages.append(Sondage(grade=200, bois_altere_cm=5.0))
        lines = diagnostic_summary_lines(a)
        joined = "\n".join(lines)
        # 2/16 directions sondées → la ligne d'extrapolation apparaît
        self.assertIn("2/16", joined)

    def test_un_seul_sondage_masque_la_classe_globale(self):
        # Avec n=1, l'extrapolation est désactivée et toutes les autres
        # directions sont supposées saines : le t/R moyen serait alors
        # faussement Vert. On vérifie que ces deux indicateurs ne sont
        # PAS affichés et qu'un avertissement explicite les remplace.
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_altere_cm=18.0))
        lines = diagnostic_summary_lines(a)
        joined = "\n".join(lines)
        self.assertNotIn("t/R moyen", joined)
        self.assertNotIn("Classe globale", joined)
        self.assertIn("Diagnostic global indisponible", joined)
        # t/R minimal reste affiché : c'est une mesure réelle sur la
        # seule direction sondée.
        self.assertIn("t/R minimal", joined)


class BrinExtentTests(unittest.TestCase):
    """Rayon d'encombrement d'un brin (`Brin.extent_cm`), pour le cadrage."""

    def test_circulaire_nu_vaut_le_rayon(self):
        b = Brin(rayon_tronc_cm=20.0)
        self.assertAlmostEqual(b.extent_cm(), 20.0)

    def test_ajoute_l_ecorce(self):
        b = Brin(rayon_tronc_cm=20.0, epaisseur_ecorce_cm=2.0)
        self.assertAlmostEqual(b.extent_cm(), 22.0)

    def test_ajoute_la_plus_longue_saillie_de_contrefort(self):
        b = Brin(rayon_tronc_cm=20.0, epaisseur_ecorce_cm=1.0)
        b.contreforts.append(
            Contrefort(grade_centre=100, largeur_grades=50, longueur_cm=8.0))
        b.contreforts.append(
            Contrefort(grade_centre=200, largeur_grades=50, longueur_cm=5.0))
        # rayon + écorce + max(saillies) = 20 + 1 + 8
        self.assertAlmostEqual(b.extent_cm(), 29.0)

    def test_ovale_utilise_le_grand_axe(self):
        # Le demi-grand-axe (rayon_tronc_cm) est le rayon maximal.
        b = Brin(rayon_tronc_cm=20.0, rayon_petit_axe_cm=12.0,
                 orientation_grade=0)
        self.assertAlmostEqual(b.extent_cm(), 20.0)


class CepeeManagementTests(unittest.TestCase):
    """Ajout / suppression / étiquetage des brins d'une cépée."""

    def test_genet_mono_caule_a_un_brin_sans_label(self):
        a = Arbre(rayon_tronc_cm=20.0)
        self.assertEqual(len(a.brins), 1)
        self.assertEqual(a.brins[0].label, "")

    def test_ajouter_brin_herite_la_forme_pas_les_mesures(self):
        a = Arbre(rayon_tronc_cm=18.0, epaisseur_ecorce_cm=1.5)
        a.brins[0].rayon_petit_axe_cm = 12.0
        a.brins[0].orientation_grade = 100
        a.sondages.append(Sondage(numero=1, grade=0, bois_sain_cm=10.0,
                                   bois_altere_cm=8.0))
        nouveau = a.ajouter_brin()
        # Forme héritée
        self.assertAlmostEqual(nouveau.rayon_tronc_cm, 18.0)
        self.assertAlmostEqual(nouveau.rayon_petit_axe_cm, 12.0)
        self.assertEqual(nouveau.orientation_grade, 100)
        self.assertAlmostEqual(nouveau.epaisseur_ecorce_cm, 1.5)
        # Mesures NON héritées
        self.assertEqual(nouveau.sondages, [])
        self.assertEqual(nouveau.degradations_externes, [])
        self.assertEqual(nouveau.contreforts, [])

    def test_ajouter_brin_place_a_l_est_sans_recouvrement(self):
        a = Arbre(rayon_tronc_cm=16.0)
        b = a.ajouter_brin()
        # Le nouveau brin est à droite : son bord gauche dépasse le bord
        # droit du brin existant (pas de recouvrement).
        bord_droit_a = a.brins[0].pos_x_cm + a.brins[0].extent_cm()
        bord_gauche_b = b.pos_x_cm - b.extent_cm()
        self.assertGreater(bord_gauche_b, bord_droit_a)

    def test_labels_passent_a_abc_en_cepee(self):
        a = Arbre(rayon_tronc_cm=16.0)
        a.ajouter_brin()
        a.ajouter_brin()
        self.assertEqual([b.label for b in a.brins], ["a", "b", "c"])

    def test_supprimer_brin_reetiquette_et_refuse_sous_un(self):
        a = Arbre(rayon_tronc_cm=16.0)
        a.ajouter_brin()  # 2 brins : a, b
        self.assertTrue(a.supprimer_brin(1))
        self.assertEqual(len(a.brins), 1)
        # Retour mono-caule : label remis à vide.
        self.assertEqual(a.brins[0].label, "")
        # On ne descend pas sous 1 brin.
        self.assertFalse(a.supprimer_brin(0))
        self.assertEqual(len(a.brins), 1)

    def test_supprimer_brin_index_hors_bornes(self):
        a = Arbre(rayon_tronc_cm=16.0)
        a.ajouter_brin()
        self.assertFalse(a.supprimer_brin(5))
        self.assertEqual(len(a.brins), 2)


class GenetDiagnosticTests(unittest.TestCase):
    """Agrégation pire-brin du diagnostic d'un genet (cépée)."""

    def _brin(self, rayon: float, mesures: list) -> Brin:
        """Brin avec des sondages (grade, bois_sain) ; altéré = rayon − sain."""
        b = Brin(rayon_tronc_cm=rayon)
        for i, (g, sain) in enumerate(mesures):
            b.sondages.append(Sondage(numero=i + 1, grade=g, bois_sain_cm=sain,
                                       bois_altere_cm=max(0.0, rayon - sain)))
        return b

    def test_pire_classe(self):
        self.assertEqual(pire_classe(["Vert", "Rouge", "Orange"]), "Rouge")
        self.assertEqual(pire_classe(["Vert", "Orange"]), "Orange")
        self.assertEqual(pire_classe(["Vert"]), "Vert")
        self.assertIsNone(pire_classe([]))

    def test_mono_brin_coincide_avec_repartition_classes(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        for i, g in enumerate((0, 25, 50)):
            a.sondages.append(Sondage(numero=i + 1, grade=g,
                                       bois_sain_cm=18.0, bois_altere_cm=2.0))
        gd = genet_diagnostic(a)
        snap = repartition_classes(a)
        self.assertEqual(len(gd.brins), 1)
        self.assertEqual(gd.fiable, snap.diagnostic_fiable)
        assert snap.diagnostic_global is not None
        self.assertEqual(gd.classe_globale, snap.diagnostic_global[1])

    def test_repartition_classes_delegue_au_brin_courant(self):
        # repartition_classes(arbre) == repartition_classes_brin(brin[0], port)
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_sain_cm=10.0,
                                   bois_altere_cm=10.0))
        self.assertEqual(repartition_classes(a),
                         repartition_classes_brin(a.brins[0], a.port_arbre))

    def test_cepee_classe_globale_est_le_pire_brin(self):
        a = Arbre(port_arbre="libre", brins=[
            self._brin(20.0, [(0, 18.0), (25, 18.0), (50, 18.0)]),
            self._brin(20.0, [(0, 1.0), (25, 1.0), (50, 1.0),
                              (75, 1.0), (100, 1.0)]),
        ])
        gd = genet_diagnostic(a)
        cls = [bd.snapshot.diagnostic_global[1] for bd in gd.brins
               if bd.snapshot.diagnostic_global is not None]
        self.assertEqual(gd.classe_globale, pire_classe(cls))
        self.assertTrue(gd.fiable)

    def test_brin_non_fiable_exclu_de_la_classe_globale(self):
        # Un brin à 1 sondage très altéré ne doit PAS déclasser le genet.
        a = Arbre(port_arbre="libre", brins=[
            self._brin(20.0, [(0, 18.0), (25, 18.0), (50, 18.0)]),
            Brin(rayon_tronc_cm=20.0, sondages=[
                Sondage(grade=0, bois_sain_cm=1.0, bois_altere_cm=19.0)]),
        ])
        gd = genet_diagnostic(a)
        self.assertFalse(gd.brins[1].fiable)
        self.assertTrue(gd.fiable)  # le 1er brin est fiable
        assert gd.brins[0].snapshot.diagnostic_global is not None
        self.assertEqual(gd.classe_globale,
                         gd.brins[0].snapshot.diagnostic_global[1])

    def test_aucun_brin_fiable_classe_none(self):
        a = Arbre(port_arbre="libre", brins=[
            Brin(rayon_tronc_cm=20.0, sondages=[
                Sondage(grade=0, bois_sain_cm=10.0, bois_altere_cm=10.0)]),
        ])
        gd = genet_diagnostic(a)
        self.assertIsNone(gd.classe_globale)
        self.assertFalse(gd.fiable)

    def test_genet_summary_mono_brin_identique(self):
        a = Arbre(rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_sain_cm=15.0,
                                   bois_altere_cm=5.0))
        self.assertEqual(genet_summary_lines(a), diagnostic_summary_lines(a))

    def test_genet_summary_cepee_a_un_bloc_par_brin(self):
        a = Arbre(port_arbre="libre", brins=[
            self._brin(20.0, [(0, 18.0), (25, 18.0), (50, 18.0)]),
            self._brin(20.0, [(0, 2.0), (25, 2.0), (50, 2.0)]),
        ])
        a._relabel_brins()
        txt = "\n".join(genet_summary_lines(a))
        self.assertIn("cépée à 2 brins", txt)
        self.assertIn("Classe globale (pire brin fiable)", txt)
        self.assertIn("──── Brin a ────", txt)
        self.assertIn("──── Brin b ────", txt)

    def test_synthese_cepee_ligne_genet_plus_sous_lignes(self):
        from model import Chantier
        a = Arbre(numero_arbre="12", essence="Charme", port_arbre="libre",
                  brins=[
                      self._brin(16.0, [(0, 14.0), (100, 14.0), (200, 14.0)]),
                      self._brin(16.0, [(0, 2.0), (100, 2.0), (200, 2.0)]),
                  ])
        a._relabel_brins()
        rows = mission_synthesis_rows(Chantier(arbres=[a]))
        # 1 ligne genet (brin_label="") + 2 sous-lignes (a, b).
        self.assertEqual([r.brin_label for r in rows], ["", "a", "b"])
        genet = rows[0]
        # Classe genet = pire brin ; t/R moyen non publié au niveau genet.
        self.assertIsNone(genet.tR_moyen_pct)
        cls_brins = [r.classe_globale for r in rows[1:]]
        from diagnostic import pire_classe
        self.assertEqual(genet.classe_globale, pire_classe(cls_brins))

    def test_synthese_mono_reste_une_seule_ligne(self):
        from model import Chantier
        a = Arbre(numero_arbre="1", rayon_tronc_cm=20.0, port_arbre="libre")
        for g in (0, 100, 200):
            a.sondages.append(Sondage(grade=g, bois_sain_cm=18.0,
                                       bois_altere_cm=2.0))
        rows = mission_synthesis_rows(Chantier(arbres=[a]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].brin_label, "")

    def test_comparaison_detaillee(self):
        # Référence : bois sain 8 cm partout ; courant : 5 cm → perte 3 cm.
        ref = Arbre(numero_arbre="1", rayon_tronc_cm=20.0, port_arbre="libre")
        cur = Arbre(numero_arbre="1", rayon_tronc_cm=20.0, port_arbre="libre")
        for g in (0, 100, 200, 300):
            ref.sondages.append(Sondage(grade=g, bois_sain_cm=8.0,
                                        bois_altere_cm=12.0,
                                        compartimentation="active"))
            cur.sondages.append(Sondage(grade=g, bois_sain_cm=5.0,
                                        bois_altere_cm=15.0,
                                        compartimentation="absente"))
        det = comparaison_detaillee(ref, cur, annees=3.0)
        self.assertEqual(len(det.directions), 4)
        self.assertAlmostEqual(det.delta_prbs_moy, -3.0)
        self.assertAlmostEqual(det.taux_cm_an, 1.0)            # 3 cm / 3 ans
        self.assertEqual(det.compart_aggravees, 4)            # active→absente
        self.assertIsNotNone(det.pire)
        self.assertAlmostEqual(det.pire.delta, -3.0)

    def test_comparaison_sans_annees_pas_de_taux(self):
        ref = Arbre(rayon_tronc_cm=20.0)
        cur = Arbre(rayon_tronc_cm=20.0)
        for g in (0, 100, 200):
            ref.sondages.append(Sondage(grade=g, bois_sain_cm=8.0))
            cur.sondages.append(Sondage(grade=g, bois_sain_cm=6.0))
        det = comparaison_detaillee(ref, cur, annees=None)
        self.assertIsNone(det.taux_cm_an)
        self.assertAlmostEqual(det.delta_prbs_moy, -2.0)

    def test_comparaison_directions_non_communes_ignorees(self):
        ref = Arbre(rayon_tronc_cm=20.0)
        cur = Arbre(rayon_tronc_cm=20.0)
        ref.sondages.append(Sondage(grade=0, bois_sain_cm=8.0))
        cur.sondages.append(Sondage(grade=100, bois_sain_cm=5.0))  # autre dir.
        det = comparaison_detaillee(ref, cur, annees=1.0)
        self.assertEqual(det.directions, [])      # aucune direction commune
        self.assertIsNone(det.delta_prbs_moy)

    def test_evolution_classe(self):
        self.assertEqual(evolution_classe("Vert", "Rouge"), 1)    # aggravation
        self.assertEqual(evolution_classe("Rouge", "Vert"), -1)   # amélioration
        self.assertEqual(evolution_classe("Orange", "Orange"), 0)  # stable
        self.assertIsNone(evolution_classe(None, "Vert"))
        self.assertIsNone(evolution_classe("Vert", None))

    def test_arbre_compare_summary_mono(self):
        a = Arbre(numero_arbre="1", rayon_tronc_cm=20.0, port_arbre="libre")
        for g in (0, 100, 200):
            a.sondages.append(Sondage(grade=g, bois_sain_cm=20.0,
                                       bois_altere_cm=0.0))
        s = arbre_compare_summary(a)
        self.assertEqual(s.classe, "Vert")
        self.assertEqual(s.n_sondees, 3)
        self.assertEqual(s.rayon_cm, 20.0)
        self.assertTrue(s.fiable)
        self.assertIsNotNone(s.tR_moyen_pct)

    def test_arbre_compare_summary_non_fiable(self):
        a = Arbre(numero_arbre="2", rayon_tronc_cm=20.0, port_arbre="libre")
        a.sondages.append(Sondage(grade=0, bois_sain_cm=20.0,
                                   bois_altere_cm=0.0))
        s = arbre_compare_summary(a)
        self.assertIsNone(s.classe)        # < 3 sondages → non publié
        self.assertFalse(s.fiable)

    def test_synthese_porte_la_preconisation_au_niveau_genet(self):
        from model import Chantier
        a = Arbre(numero_arbre="1", rayon_tronc_cm=20.0, port_arbre="libre",
                  urgence="Immédiate", echeance="01/09/2026",
                  preconisation="Abattage")
        for g in (0, 100, 200):
            a.sondages.append(Sondage(grade=g, bois_sain_cm=18.0,
                                       bois_altere_cm=2.0))
        row = mission_synthesis_rows(Chantier(arbres=[a]))[0]
        self.assertEqual(row.urgence, "Immédiate")
        self.assertEqual(row.echeance, "01/09/2026")
        self.assertEqual(row.preconisation, "Abattage")

    def test_synthese_cepee_preconisation_sur_tete_pas_sous_lignes(self):
        from model import Chantier
        a = Arbre(numero_arbre="12", port_arbre="libre",
                  urgence="Surveillance", preconisation="Revoir dans 2 ans",
                  brins=[
                      self._brin(16.0, [(0, 14.0), (100, 14.0), (200, 14.0)]),
                      self._brin(16.0, [(0, 2.0), (100, 2.0), (200, 2.0)]),
                  ])
        a._relabel_brins()
        rows = mission_synthesis_rows(Chantier(arbres=[a]))
        self.assertEqual(rows[0].urgence, "Surveillance")          # tête
        self.assertEqual(rows[0].preconisation, "Revoir dans 2 ans")
        self.assertEqual([r.urgence for r in rows[1:]], ["", ""])  # sous-lignes
        self.assertEqual([r.preconisation for r in rows[1:]], ["", ""])

    def test_brin_rayon_nul_non_fiable(self):
        a = Arbre(port_arbre="libre", brins=[
            Brin(rayon_tronc_cm=0.0, sondages=[
                Sondage(grade=0, bois_sain_cm=0.0, bois_altere_cm=0.0),
                Sondage(grade=25, bois_sain_cm=0.0, bois_altere_cm=0.0),
                Sondage(grade=50, bois_sain_cm=0.0, bois_altere_cm=0.0)]),
        ])
        gd = genet_diagnostic(a)
        self.assertFalse(gd.brins[0].fiable)
        self.assertFalse(gd.fiable)


if __name__ == "__main__":
    unittest.main()
