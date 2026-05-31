# Rendu et pièges

## Pendants Tk ↔ PIL (helpers de rendu)

Chaque couche a deux implémentations parallèles, à modifier ensemble :

| Couche               | Tk (`SectionCanvas`)                  | PIL (`pil_render`)         |
|----------------------|---------------------------------------|----------------------------|
| placeholder          | `_draw_placeholder`                   | `_pil_draw_placeholder`    |
| bois sain            | `_draw_bois_sain`                     | `_pil_draw_bois_sain`      |
| cernes               | `_draw_cernes`                        | `_pil_draw_cernes`         |
| cavité d'altération  | `_draw_cavite`                        | `_pil_draw_cavite`         |
| écorce               | `_draw_ecorce`                        | `_pil_draw_ecorce`         |
| contreforts          | `_draw_contreforts_canvas`            | `_pil_draw_contreforts`    |
| dégradations ext.    | `_draw_degradation_externe_canvas`    | `_pil_draw_degradations`   |
| ticks 16 grades      | `_draw_ticks`                         | `_pil_draw_ticks`          |
| lettres cardinales   | `_draw_cardinales`                    | `_pil_draw_cardinales`     |
| sondages             | `_draw_sondages`                      | `_pil_draw_sondages`       |
| règle graduée        | `_draw_regle`                         | `_pil_draw_regle`          |
| titre + méta         | `_draw_titre`                         | `_pil_draw_titre`          |

Géométrie partagée via `geometry.py`. Constantes de layout tunées
indépendamment (hinting, épaisseurs de trait, semantics outline+width).

## Ordre global des couches (Tk et PIL alignés)

1. disque bois sain
2. cernes de croissance
3. cavité d'altération (spline interne)
4. anneau d'écorce
5. contreforts fusionnés (une cloche par zone connectée)
6. **dégradations externes en DERNIER** — bord externe suit la surface
   (`R + ep + cloche`), mord dans écorce et contreforts

## Pièges connus

### Deux moteurs de rendu distincts
La géométrie partagée (`geometry.py`) empêche la divergence des formes.
Restent à synchroniser à la main : palette/typographie, API de dessin,
écorce/anneau, et tout ce qui est spécifique renderer.

### Positions hors-tronc
Lettres cardinales, pastilles de sondage, règle graduée : en **pixels
absolus** (pas en cm) pour rester constantes quel que soit le rayon.

### Titre et lettre N
Le titre + méta sont au-dessus de la zone de la lettre N. Toujours
laisser une marge suffisante pour ne pas tronquer N.

### Différence `outline + width` sur ellipse (Tk vs PIL)
- **Tkinter** : trait centré sur la frontière du bounding box →
  bbox à `R + ep/2` pour que l'outline couvre `[R, R_ext]`.
- **PIL** : trait entièrement à l'intérieur du bbox →
  bbox à `R_ext` pour que l'outline de largeur `ep_px` tombe sur `[R, R_ext]`.

### Ordre de dessin des contreforts
1. Couche écorce du contrefort (bord interne à `R` constant → fusionne avec anneau tronc)
2. Polygone bois par-dessus (révèle le noyau)
3. `cf_inner_r = R - 1/scale` pour éviter les trous pixel

### Règle graduée symétrique
La règle va de -R à +R (centrée sous le tronc), avec barres d'écorce
brunes et tirets aux extrémités. Graduations et labels en miroir des
deux côtés. Éléments en pixels (tirets, labels, offsets) scalés par
`_ds` côté PIL pour suivre la résolution de l'image.

### Légende des exports
- PNG : bande sous la règle graduée (`show_legend=True`). Tailles
  proportionnelles à la hauteur, polices via `f_base` (non scalées par
  `_ds` car déjà proportionnelles).
- PDF : rendue directement par `fiche_pdf` (pleine largeur A4, pas dans l'image tronc).

### Dimensionnement adaptatif du PDF
Au-delà de 8/12 sondages, hauteur de ligne et police se resserrent
(38/35/32 px, 17/16/15 pt) pour tenir sur une page A4.

### XLSX et cellules fusionnées
Utiliser `openpyxl.utils.get_column_letter(i)` — **pas**
`ws.cell(...).column_letter` (échoue sur `MergedCell` en ligne 1 fusionnée).

### Pastille du sondage
= PRBS **ajustée** (jamais brute). Les deux renderers calculent
`prbs_adj = max(0, s.prbs_cm - deg_ext_par_grade[grade])` puis
`classer_prbs(prbs_adj / R, port)`.

### Pas de cache `alteration_par_grade` sur `Arbre`
Calcul uniquement par `compute_alteration_par_grade()` (pure).
Verrouillé par `test_arbre_n_expose_plus_de_cache_alteration`.

### set_rayon : jamais pendant la frappe
`Arbre.set_rayon` est destructif : il cap `bois_sain_cm` à `min(sain, new_R)`,
irréversible. Pendant la frappe dans les champs Diamètre/Rayon, on met à
jour `rayon_tronc_cm` directement (aperçu live) sans appeler `set_rayon`.
`set_rayon` n'est appelé qu'au **focus-out** via `_commit_rayon`, avec push
undo. Si le champ est invalide au focus-out (texte non numérique), le rayon
et le diamètre sont revertés à leur valeur d'avant le focus-in.

### Chevauchement des dégradations externes
Deux arcs sont en chevauchement si ils couvrent au moins un grade en
commun, SAUF si ce grade est uniquement un point de contact (fin d'un
arc = début de l'autre). La validation utilise `couvre_grade` sur les
16 grades, en excluant les grades qui sont le début du candidat et la
fin de l'existant (ou inversement).

### `ttk.Treeview` ignore les `tag_configure(foreground=…)` (bpo-36468)

Depuis Python 3.7, des entrées par défaut dans `style.map` priment sur
les tags d'item — résultat : `tree.tag_configure("rouge",
foreground="#A62A1F")` n'a aucun effet visible. Workaround dans
`app_style._fixed_map` : retire les entrées `("!disabled",
"!selected", …)` du mapping de `Treeview` et `Side.Treeview`. Sans ce
correctif, les pastilles d'état de la liste d'arbres restent
blanches/grises. Vérifier l'effet du workaround : `style.map("Side.
Treeview", query_opt="foreground")` doit renvoyer `[]` (ou ne
contenir que des entrées non par-défaut).

### Dialogue Tk modal vide quand ouvert depuis un événement de clic

Appeler `grab_set()` sur un `tk.Toplevel` AVANT que le WM ait mappé
la fenêtre fait apparaître le dialogue vide sur Linux/X11 (race entre
le grab et le rendu des enfants). Symptôme : titre OK, fenêtre OK,
mais aucun widget visible. Fix dans `dialogs._make_modal(dlg,
parent)` : séquence canonique `update_idletasks → transient →
wait_visibility → grab_set → focus_set`, appelée APRÈS la création
des widgets. Tous les dialogues d'édition passent par ce helper. Pour
le canvas interactif (`section_canvas`), l'ouverture du dialogue est
en plus différée via `after_idle` pour laisser la boucle Tk finaliser
l'événement de clic avant de créer le Toplevel.

### Menu contextuel `tk_popup` + `grab_release()` immédiat

Anti-pattern courant copié des vieilles docs Tcl/Tk : appeler
`menu.grab_release()` juste après `menu.tk_popup(x, y)`. Sur
Linux/X11, `tk_popup` ne pose pas de grab automatique → l'appel
immédiat à `grab_release()` annule le seul mécanisme qui fermerait le
menu au clic externe. Fix : NE PAS appeler `grab_release()` après
`tk_popup`, et binder `<FocusOut>` sur le menu pour fermeture
explicite.

## Limites connues

- **Duplication Tk ↔ PIL au-delà de la géométrie** : écorce/anneau,
  cernes, règle, pastilles, ticks, lettres cardinales restent dupliqués.
  Les deux jeux sont symétriques par nom → modifier LES DEUX fichiers.
- **Couverture visuelle Tk** : golden-fixtures = dump JSON des items Canvas
  (structure, pas rendu pixel). Un changement de police système ne
  régresse pas (voulu).
