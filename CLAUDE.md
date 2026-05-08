# Pénétromètre — Projet Silvavenir

Application desktop d'expertise arboricole. Logiciel d'aide à la décision
pour les expertises au pénétromètre (mesure de cavités dans les troncs).
Utilisé en interne par le cabinet **Silvavenir** (foresterie urbaine).

## Stack

- **Python 3.9+** (3.12 recommandé)
- **Tkinter** (UI) — bibliothèque standard, pas d'install à part
- **Pillow** (rendu PNG/PDF + chargement logo) — seule dépendance externe

Aucun framework, aucun build system. C'est volontaire : l'app doit pouvoir
être lancée d'un double-clic sur n'importe quel poste avec Python installé.

## Structure

Tout le code tient dans un fichier unique de ~3400 lignes :

```
resistographe.py        ← l'application complète
silvavenir_logo.jpg     ← logo affiché dans le header et les PDF
Lancer_Penetrometre.bat ← lanceur double-clic Windows
```

Le nom de fichier `resistographe.py` reste celui-ci pour des raisons
historiques même si le produit s'appelle « Pénétromètre » (Résistographe
est une marque déposée).

## Architecture du fichier

Le fichier est organisé en sections séparées par des bandeaux de
commentaires :

1. **Constantes** (palette couleurs, grades, ports)
2. **Modèle de données** — dataclasses :
   - `Sondage` — une mesure ponctuelle dans une direction
   - `DegradationExterne` — un arc d'écorce dégradée
   - `Contrefort` — empattement à la base (cloche cosinus²)
   - `Arbre` — un arbre avec ses sondages, dégradations et contreforts
   - `Chantier` — une mission qui regroupe plusieurs arbres
3. **Helpers géométrie contreforts** (module-level) :
   - `bell_max_at_grade(grade, contreforts)` — hauteur max de cloche
     en un point angulaire donné, en parcourant tous les contreforts
   - `contrefort_zones(contreforts)` — fusion des intervalles
     angulaires qui se chevauchent ou se touchent (pour dessiner une
     seule cloche unifiée par groupe au lieu d'un V entre deux
     contreforts proches)
4. **Logique métier** sur `Arbre` (méthodes) :
   - `recompute_alteration_from_sondages()` — extrapolation par moyenne
     pondérée linéaire entre voisins
   - `prbs_par_grade()` — PRBS ajustée (intègre dégrad. externes)
   - `repartition_classes()` — Vert/Orange/Rouge sur le pourtour
5. **Rendu Tkinter** — `class SectionCanvas(tk.Canvas)` : dessine la
   section transversale en temps réel dans la fenêtre
6. **Application** — `class App(tk.Tk)` : fenêtre principale, onglets,
   sync UI ↔ modèle, actions
7. **Rendu PIL** — `render_arbre_to_pil_image()` et
   `render_fiche_arbre_to_pdf_page()` : génération PNG et PDF.
   Helpers associés : `_pil_load_fonts()`, `_fit_text()` (troncature
   ellipsis pour rester dans une largeur), `_draw_horizontal_legend_pil()`
   (légende sur une ligne, sous l'échelle).
   **Le code de rendu PIL est volontairement parallèle au rendu Tkinter**
   (mêmes calculs de positions, palettes communes). Quand tu modifies
   un aspect visuel, **modifie systématiquement les deux**.

## Conventions métier importantes

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens
  horaire. **Pas de symbole `°`** — afficher `100 gr` (gradian).
- **PRBS** = Paroi Résiduelle de Bois Sain = épaisseur de bois sain
  mesurée par le foret. C'est la mesure invariante (physique) — quand
  le rayon change, la PRBS reste, c'est `bois_altéré` qui s'ajuste.
- **t/R** = PRBS / Rayon, ratio entre 0 et 1.
- **Classe globale** = barème Silvavenir appliqué au **t/R moyen** sur
  les 16 directions (pas au minimum, ni au pourcentage de directions).
- Les **dégradations externes consomment** du bois sain :
  `PRBS_ajustée = bois_sain − profondeur_dégradation_externe`.
- **Écorce du tronc** : épaisseur `epaisseur_ecorce_cm` ajoutée vers
  l'extérieur du rayon (purement visuel, n'intervient pas dans la PRBS
  ni le diagnostic). Rayon externe = `R + ep`.
- **Contreforts** : un contrefort = noyau de bois (cloche cosinus² qui
  culmine à `R + longueur` au centre, redescend à `R` aux extrémités)
  recouvert d'une couche d'écorce de **même épaisseur** que celle du
  tronc (sommet externe à `R + longueur + ep`).
- **Fusion des contreforts adjacents** : quand plusieurs contreforts se
  chevauchent ou se touchent, ils sont rendus comme **une seule cloche
  unifiée** dont la hauteur en chaque grade est le max des hauteurs
  individuelles. Cette fusion (helpers `bell_max_at_grade` /
  `contrefort_zones`) évite l'encoche en V qui apparaissait quand
  chaque contrefort était dessiné isolément.
- **Dégradations externes et contreforts** : la dégradation suit la
  surface réelle de l'arbre — son bord externe est à `R + ep + cloche`
  et son bord interne à `outer − profondeur`. Une dégradation qui
  traverse un contrefort y mord à concurrence de sa profondeur.
- **Règle graduée** sous la section : étendue de `-R_ext` à `+R_ext`.
  La portion bois `[-R, +R]` est en trait noir fin ; les portions
  écorce sont des barres brun foncé épaisses.
- **Couleurs `BARK` et `ROT` distinctes** : `COLOR_BARK = #5C3A1E`
  (écorce intacte) ≠ `COLOR_ROT = #3E2510` (bois dégradé, bien plus
  foncé). C'est essentiel pour que la « plaie » d'une dégradation soit
  lisible quand elle traverse l'écorce. **Ne jamais réunifier les deux
  couleurs** — la légende des exports les présente comme deux entrées
  distinctes (« Bois dégradé » vs « Écorce »).

## Conventions de code

- Pas de dépendance ajoutée sans bonne raison. Tkinter pur + Pillow.
- Compatibilité Python 3.9+ (annotations `Optional[X]` plutôt que `X | None`
  pour les positions critiques, mais `tuple[str, str]` est OK car Python 3.9
  supporte le PEP 585 dans ce contexte).
- Tout en français côté UI et docstrings (le projet est franco-français).
- Pas de `print` en production — tout passe par `messagebox`.

## Compatibilité ascendante des fichiers

Les missions sont enregistrées en JSON. Le format évolue mais l'app doit
**toujours pouvoir ouvrir les anciens fichiers**. La migration se fait
silencieusement dans `Chantier.from_dict` (par ex. mapping des anciens
libellés de port `"Libre, semi-libre ou traumatique"` → `"libre"`).
**Ne jamais casser cette compatibilité** sans ajouter une migration.

## Commandes utiles

```bash
# Vérifier la syntaxe avant commit
python -c "import ast; ast.parse(open('resistographe.py').read())"

# Lancer l'app
python resistographe.py
```

## Pièges connus

- Le rendu Tkinter et le rendu PIL sont **deux moteurs distincts** mais
  doivent rester visuellement identiques. Toute modif d'un côté doit
  être répercutée de l'autre.
- Les positions des éléments hors-tronc (lettres cardinales, pastilles
  de sondage, règle graduée) sont en **pixels absolus** (pas en cm)
  pour rester constantes quel que soit le rayon de l'arbre.
- Le titre + méta-données du dessin sont placés au-dessus de la zone
  de la lettre N (tout en haut). Toujours laisser une marge suffisante
  pour ne pas que la lettre N soit tronquée.
- **Différence Tkinter ↔ PIL pour `outline + width` sur ellipse** :
  Tkinter `create_oval(outline, width)` centre le trait sur la
  frontière du bounding box ; PIL `d.ellipse(outline, width)` dessine
  le trait **entièrement à l'intérieur** du bounding box. Conséquence
  pour l'anneau d'écorce : en PIL, le bbox doit être à `R_ext`
  (= `R + ep`) pour que l'outline de largeur `ep_px` tombe exactement
  sur `[R, R_ext]`. En Tkinter, le bbox est à `R + ep/2` (pour que
  l'outline centré couvre `[R, R_ext]`).
- **Ordre de dessin des contreforts** : pour éviter toute raie visible
  entre le contrefort et l'anneau d'écorce du tronc, on dessine
  d'abord la couche d'écorce du contrefort avec bord interne à `R`
  constant (fusionne avec l'anneau du tronc), puis le polygone bois
  par-dessus pour révéler le noyau. Le polygone bois descend à
  `cf_inner_r = R - 1/scale` pour ne laisser aucun trou pixel.
- **Ordre global des couches** dans la section (Tkinter et PIL doivent
  rester alignés) :
  1. disque bois sain
  2. cernes de croissance
  3. cavité d'altération (spline interne)
  4. anneau d'écorce
  5. contreforts fusionnés (une cloche par zone connectée)
  6. **dégradations externes en DERNIER** — leur bord externe suit la
     surface (`R + ep + cloche`) afin de mordre dans l'écorce et les
     contreforts qu'elles traversent.
- **Légende des exports** : `render_arbre_to_pil_image(...,
  show_legend=True)` réserve une bande **sous la règle graduée** pour
  une légende horizontale sur une ligne. Pour le PDF, la légende est
  rendue **directement par `render_fiche_arbre_to_pdf_page`** (et non
  dans l'image du tronc) afin de profiter de la pleine largeur de la
  page A4 — sinon les items à droite sont tronqués.
- **Dimensionnement adaptatif du PDF** : `render_fiche_arbre_to_pdf_page`
  estime la place que prendront le tableau, le diagnostic, la légende
  et le pied de page, puis alloue le reste au dessin (entre 420 et
  900 px). Au-delà de 8/12 sondages, la hauteur de ligne et la police
  du tableau se resserrent (38/35/32 px, 17/16/15 pt) pour que la
  page reste sur une feuille A4 unique.

## Quand tu modifies l'app

1. **Avant** de toucher au code : lire la zone concernée (ce fichier
   est gros, ~3400 lignes — utiliser `grep -n` pour localiser).
2. Pour les changements visuels : **mettre à jour Tkinter ET PIL**.
3. Pour les changements de modèle : penser à la migration JSON.
4. Tester en lançant l'app et en sauvegardant / rechargeant un `.json`.
5. Pour valider les exports PNG/PDF, générer un échantillon avec
   plusieurs cas (avec/sans écorce, avec/sans contreforts, avec/sans
   sondages, avec une dégradation externe traversant un contrefort) —
   les bugs de raster PIL n'apparaissent pas toujours dans Tkinter.
6. Pour les changements de légende : tester en condition « stress »
   (16 sondages + commentaire long) pour s'assurer que la fiche
   reste sur une seule page.
