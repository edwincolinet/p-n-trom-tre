# Refonte des comparaisons (ré-inspection) — plan

> **Statut** (26/11/2026) : **lots 0 à 4 implémentés** (non publiés) ; lot 5 à
> faire. Le constat du §1 décrit la v3.8.0.

## 1. Constat

### Sur le fond (calcul et saisie)

Avec R = rayon sous écorce et ρ = rayon d'altération (R − PRBS) :
`ΔPRBS = ΔR (croissance) − Δρ (progression) − Δ(bois perdu en externe)`.

Un diamètre de +5 cm donne ΔR = **+2,5 cm**. À cavité inchangée, la PRBS
augmente donc de 2,5 cm, pas de 5.

1. **La croissance masque la progression.** `diagnostic_comparaison` ne juge que
   la PRBS et le t/R. Réf. Ø 80, PRBS 20 ; courant Ø 85, PRBS 21,5 : la cavité a
   gagné 1 cm de rayon, le verdict annonce « AMÉLIORATION ».
2. **Valeurs reconduites.** La ré-inspection recopie les anciens sondages. Une
   direction non re-mesurée garde sa PRBS alors que le rayon augmente
   (`set_rayon`) : fausse progression, comptée « mesurée aux deux dates ».
3. **Aucune tolérance de mesure** réaliste (seuil actuel : 0,1 cm).
4. **Titre faux** possible : « la paroi saine la plus mince a diminué » alors
   que seul le t/R baisse (PRBS 20 → 20,5, Ø 80 → 85).
5. Une cavité qui rétrécit est présentée comme une amélioration, au lieu d'être
   signalée comme un écart à vérifier.
6. Directions extrapolées et mesurées pèsent pareil dans le verdict.
7. La hauteur de sondage n'est pas comparée.

### Sur l'usage

- Fenêtre séparée, menu dédié, entrées d'export grisées.
- Référence gardée en mémoire seulement : perdue à la fermeture.
- Deux campagnes au maximum ; appariement des brins par position.

## 2. Principes

1. **Deux réponses distinctes, jamais fusionnées** :
   - *État actuel* : t/R minimal et classe, évolution.
   - *Dégradation* : a-t-elle progressé, où, de combien ?
2. **Seul le mesuré aux deux dates conclut.** L'extrapolé est montré, à part.
3. **Aucune tolérance de mesure** supposée (trop variable) : les écarts sont
   rapportés tels que mesurés.
4. **L'incohérence se signale**, elle ne devient pas un résultat.
5. **On compare dans un repère fixe** (centre du tronc, en cm), pour la cavité
   comme pour les dégradations externes (position R − profondeur).

Hypothèse à écrire dans le livrable : croissance centrée. Le diamètre seul ne
permet pas de mesurer un déplacement du cœur.

## 3. Données : l'historique dans la mission

- `Arbre.campagnes` : liste d'instantanés figés (date, opérateur, hauteur de
  sondage, mèche, port, barème, brins complets, photos).
- Identifiants stables d'arbre et de brin (appariement sans n° ni position).
- Le fichier est autonome : plus de référence à recharger, N campagnes.
- « Importer une ancienne mission comme campagne précédente » pour les fichiers
  existants, avec appariement proposé puis validé.
- `format_version` 4. À vérifier avant : une version 3.8 qui ouvre puis
  enregistre un fichier v4 perdrait l'historique ; prévoir la mise à jour de
  tous les postes.
- `photos_comparaison_ref/_cur` migrées vers les campagnes.

## 4. Parcours

1. **Nouvelle campagne** (un bouton) : fige l'état courant dans l'historique,
   demande la date, **vide les mesures**. Géométrie et identité reprises ; le
   diamètre est marqué « à re-mesurer ».
2. **Saisie** dans l'onglet Sondages habituel, avec l'ancienne valeur en gris et
   l'écart en direct :

```text
Dir.  PRBS préc.  PRBS   Croissance  Cavité
N        20,0     22,5      +2,5     = stable
NE       19,0     20,0      +2,5     ▲ +1,5
E        21,0      —                 non re-mesuré
S        18,0     25,0      +2,5     ? à vérifier (−4,5)
```

3. **Onglet « Évolution »** dans la fenêtre principale : choix des deux dates,
   les deux réponses du principe 1, tableau par direction, alertes, courbe dans
   le temps à partir de trois campagnes.
4. **Dessin principal** : sélecteur `Actuel | Précédent | Évolution`. En mode
   Évolution : même échelle en cm, anneau de bois neuf, ancienne cavité en
   pointillé, progression en orange, écarts douteux hachurés, cernes masqués.
5. **Liste d'arbres** : repère d'évolution et filtre « en progression ».
6. **Export** : entrée normale, disponible dès qu'il existe une campagne
   précédente ; PDF vectoriel dans le style de la fiche.

Suppressions : fenêtre `comparaison.py`, menu Comparaison, référence en session.

## 5. Découpage

| Lot | Contenu | Valeur seule |
|-----|---------|--------------|
| 0 | Correctif : progression calculée sur ρ, tolérance, alertes d'incohérence, titres | oui (3.8.x) |
| 1 | Module pur `evolution.py` + tests des scénarios ci-dessous | socle |
| 2 | Campagnes dans le modèle, migration, import | socle |
| 3 | Nouvelle campagne + valeurs précédentes dans la saisie | oui |
| 4 | Onglet Évolution + mode du dessin ; retrait de la fenêtre | oui |
| 5 | Export PDF/PNG, guide, traductions EN/IT | oui |

Lots 2 à 5 : une même version majeure.

Scénarios de test : croissance seule ; progression masquée par la croissance ;
progression sans croissance ; valeur non re-mesurée ; cavité qui rétrécit ;
diamètre en baisse ; dégradation externe stable sous croissance ; plaie
recouverte ; cépée avec brin supprimé ; hauteurs de sondage différentes ; trois
campagnes.

## 6. Décisions (Edwin, 26/11/2026)

1. Historique dans le fichier mission : oui.
2. Pas de tolérance de mesure fixée.
3. Le bois dégradé ne redevient pas sain ; le recouvrement est un progrès.
4. Hauteurs de sondage différentes : refus de conclure.
5. Lot 0 tout de suite.

Question ouverte (lot 2) : une dégradation externe recouverte reste du bois
perdu. Si l'expert la retire de la saisie, le t/R la compte comme saine ; il
faudra pouvoir la garder avec l'état « recouverte ».

Constat du lot 1, à traiter au lot 2 : `supprimer_brin` réétiquette les brins,
et la fenêtre actuelle apparie par rang. Après suppression d'un brin, elle
compare donc des tiges différentes. `evolution.appariement_par_defaut` ne
devine rien si le nombre de brins change ; seuls des identifiants stables
règlent aussi le cas suppression + ajout.

## 7. Lot 2 (fait) et reports

Fait : `Arbre.id`, `Brin.id`, `Arbre.campagnes`, format v4, `campagnes.py`
(archiver, proposer/importer depuis une ancienne mission),
`DegradationExterne.recouverte` (modèle, fichier, calcul). Aucun poste n'ayant
le logiciel, pas de précaution vis-à-vis des anciennes versions.

Reporté :

- **Lot 3** : case « recouverte » dans la saisie des dégradations (vérifier que
  l'édition ne la perd pas) ; dessin de la couche sous le cal (il faudra
  décider comment connaître l'épaisseur du cal) ; mention dans la fiche et les
  exports ; boutons « Nouvelle campagne » et « Importer » (confirmation de
  l'appariement) ; la ré-inspection actuelle n'archive encore rien.
- **Lot 4** : `photos_comparaison_ref/_cur` (restent en place jusqu'au retrait
  de la fenêtre).

## 8. Plaie recouverte : décisions (Edwin, 26/11/2026)

- L'épaisseur du cal n'est en général **pas mesurée** : aucun champ obligatoire.
- La profondeur saisie est l'**épaisseur de bois dégradé sous le cal**, cal non
  compris (et donc sans déduction d'écorce).
- Dessin proposé (à valider) : avec un relevé antérieur, placer la couche à sa
  position d'alors (repère fixe) ; sinon la dessiner à la surface avec un trait
  « recouverte », sans inventer d'épaisseur de cal.

## 9. Lot 3 (fait) et reports

Fait : nouvelle campagne, import d'un relevé antérieur, colonne « Préc. /
écart », zone « Recouverte (cal) » et son dessin (section, PNG, PDF,
évolution), diagnostic de comparaison alimenté par l'historique (pont jusqu'au
lot 4).

Reporté :

- Largeur de la grille Sondages : déjà trop large avant (709 px requis pour
  659 disponibles, fenêtre de 1700 px), 795 px avec la nouvelle colonne.
- Appariement des **brins** à l'import : automatique, les brins sans
  correspondance sont seulement signalés.
- Photos des relevés importés : chemins relatifs à l'ancienne mission, à
  traiter avant de les afficher (lot 4).
- « Faire une comparaison (ré-inspection) » subsiste ; à retirer au lot 4.

## 10. Lot 4 (fait) et reports

Fait : onglet Évolution, modes du dessin, repère et filtre dans la liste,
export depuis l'onglet, retrait de `comparaison.py`.

Écarts avec le §4 : les écarts douteux sont en violet plein (pas hachurés) ;
les photos de comparaison restent sur l'arbre courant (pas de migration) ; la
courbe montre le t/R minimal, pas la progression cumulée.

Lot 5 : PDF vectoriel dans le style de la fiche (aujourd'hui raster),
mention des plaies recouvertes dans les exports, guide de démarrage.

## 11. Retours d'usage (Edwin, 26/11/2026) — remplacent les §8 et §9

- Une plaie recouverte ne perd rien : zone et profondeur inchangées, le cal
  est posé par-dessus (bourrelet). « Recouverte » est une case à part.
- Une nouvelle campagne ne supprime rien : « tout garder, à confirmer ».
  Choix d'implémentation : les valeurs non confirmées restent dans le
  diagnostic courant (avertissement avant export), pas dans la comparaison.

