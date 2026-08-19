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
| échelle radiale      | `_draw_echelle_radiale`               | `_pil_draw_echelle_radiale`|
| titre + méta         | `_draw_titre`                         | `_pil_draw_titre`          |
| section d'1 brin     | `_draw_brin`                          | `_pil_draw_brin`           |
| label de brin        | `_draw_brin_label`                    | `_pil_draw_brin_label`     |
| composition cépée    | `_draw_cepee`                         | `_pil_draw_cepee`          |

Géométrie partagée via `geometry.py`. Constantes de layout tunées
indépendamment (hinting, épaisseurs de trait, semantics outline+width).
`_draw_brin` regroupe les couches per-brin (bois → pastilles) centrées sur
`(cx, cy)` ; `_draw_cepee` les compose pour une cépée. **Toujours les DEUX.**

## Ordre global des couches (Tk et PIL alignés)

1. disque bois sain
2. cernes de croissance
3. cavité d'altération (spline interne)
4. anneau d'écorce
5. contreforts fusionnés (une cloche par zone connectée)
6. **dégradations externes en DERNIER** — bord externe suit **toujours** la
   cloche des contreforts (`+ bell`) ; rayon de départ `R + bell + ep` si la
   dégradation comprend l'écorce (`comprend_ecorce`, défaut), `R + bell` si
   elle commence sous l'écorce (écorce intacte). Léger recouvrement vers
   l'extérieur (`_BARK_SEAM_PX`) pour souder la couture (cf. piège ci-dessous)

## Pièges connus

### Deux moteurs de rendu distincts
La géométrie partagée (`geometry.py`) empêche la divergence des formes.
Restent à synchroniser à la main : palette/typographie, API de dessin,
écorce/anneau, et tout ce qui est spécifique renderer.

### Couture d'anti-aliasing entre remplissages jointifs
Deux polygones/formes qui se touchent au **même rayon** (ici dégradation
externe vs anneau d'écorce) laissent un liseré d'~1 px de fond visible entre
eux, en Tk **comme** en PIL (mesuré : la dégradation s'arrêtait 1 px avant le
bord de l'écorce). Parade : prolonger le bord partagé d'un léger recouvrement
vers l'extérieur (`geometry._BARK_SEAM_PX`, en px → converti en cm via
`scale`). Le recouvrement ne déborde **que** vers l'extérieur — il ne change
ni la profondeur creusée ni le diagnostic. Vaut pour toute future forme
abutée à une autre.

### Anneau peint en UN polygone (« contour externe + interne inversé ») : jointure à deux angles
Peindre un anneau (écorce à rayon variable, bande de contrefort) comme un
seul polygone simple `outer + inner[::-1]` (pas d'API de trou côté PIL/Tk)
referme la forme via **deux ponts d'angles légèrement différents** — le
dernier échantillon d'`outer` (~397.5 gr) et le premier d'`inner`/`outer`
(0 gr), soit l'écart d'échantillonnage (`contour_polygon`, 160 pts/400 gr) —
au lieu du **même** angle aller-retour. Résultat : un fin coin non rempli à
la jointure, systématiquement au grade 0 (le point de départ de
l'échantillonnage) → **rectangle blanc au Nord**, visible dès que la section
a un rayon variable (`a_rayon_variable`), donc invisible sur le cas
circulaire (primitive native, pas de polygone). Corrigé une fois pour toutes
par `geometry.ring_polygon_points(outer, inner)` : reboucle `outer` sur
lui-même avant le pont vers `inner[0]`, si bien que les deux ponts sont
l'aller-retour du **même** segment (largeur nulle). Toute nouvelle
construction d'anneau par cette technique doit passer par ce helper —
jamais un `outer + inner[::-1]` écrit à la main.

### Positions hors-tronc
Lettres cardinales, pastilles de sondage, tirets de l'échelle radiale :
en **pixels absolus** (pas en cm) pour rester constants quel que soit le
rayon.

### Titre et lettre N
Le titre + méta sont au-dessus de la zone de la lettre N. Toujours
laisser une marge suffisante pour ne pas tronquer N.

### Cépée : mono-brin centré = chemin verbatim (goldens)
`render_arbre_to_pil_image` / `SectionCanvas.redraw` **dérivent tôt** vers le
chemin cépée (`_pil_draw_cepee` / `_draw_cepee`) dès que `len(brins) > 1` OU
qu'un brin est décentré. Le cas mono-brin centré (99 %) garde son cadrage et
son arithmétique **dédiés** (à l'ULP près) → fixtures circulaires/ovales
byte-identiques. Ne JAMAIS router le mono-brin par `brins_layout` (l'ordre des
divisions diffère, ce qui décalerait d'un pixel et casserait les goldens). La
**boussole globale** d'une cépée est tracée sur le RECTANGLE de la bbox (N/S/E/O
sur les bords, diagonales aux coins) — une cépée large déborderait d'un cercle
de rayon = demi-diagonale ; la place de la boussole est réservée dans les marges
passées à `brins_layout`. Les **ticks** restent par brin ; les **cardinales**
sont globales (`_draw_brin(..., draw_cardinales=False)` par brin).

### Différence `outline + width` sur ellipse (Tk vs PIL)
- **Tkinter** : trait centré sur la frontière du bounding box →
  bbox à `R + ep/2` pour que l'outline couvre `[R, R_ext]`.
- **PIL** : trait entièrement à l'intérieur du bbox →
  bbox à `R_ext` pour que l'outline de largeur `ep_px` tombe sur `[R, R_ext]`.

### Ordre de dessin des contreforts
1. Couche écorce du contrefort (bord interne à `R` constant → fusionne avec anneau tronc)
2. Polygone bois par-dessus (révèle le noyau)
3. `cf_inner_r = R - 1/scale` pour éviter les trous pixel

### Échelle radiale par brin
Échelle **asymétrique** graduée du centre au bout de l'écorce, le long de
l'axe **Est** (100 gr) — ou de la direction libre la plus proche si un
sondage est rendu à l'Est **et que les sondages sont affichés**
(`geometry.radial_ruler_grade` : alternance 125, 75, 150, 50, … ; les
sondages et la rotation des brins étant par pas de 25 gr, l'esquive trouve
toujours une direction libre sauf 16/16 sondées → retombe sur l'Est, le
halo garde l'échelle lisible ; sondages masqués via la case sous le
canevas / `show_sondages` → pas de flèche à éviter, échelle plein Est).
Graduations : « 0 » au centre, multiples du pas adaptatif (tiret à moins
d'un pas du terminal omis — étiquettes télescopées) avec **repli médian**
si aucun ne tient (toujours ≥ 1 segment intermédiaire), terminal
« N cm » au **bout de l'écorce** (R+ep, arrondi au mm — l'ellipse à
l'angle d'esquive produit des décimales). Dessinée **en dernier dans
`_draw_brin`/`_pil_draw_brin`** (premier plan : halo blanc sous les
traits + halo des étiquettes). Pour un brin pivoté, le rayon affiché est
le rayon local à `grade_monde - rotation`. A remplacé la règle -R..+R
(mono-brin) et la barre « N cm » (cépée). Éléments en pixels (tirets,
labels, offsets) scalés par `_ds` côté PIL.

### Légende des exports
- PNG : bande basse réservée (`show_legend=True`). Tailles
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
