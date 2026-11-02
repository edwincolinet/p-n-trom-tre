# Conventions métier — référence détaillée

> Extrait de CLAUDE.md (2026-11-02) pour l'alléger. Le « pourquoi », les dates et les pièges
> corrigés vivent ici ; les règles essentielles restent résumées dans CLAUDE.md.

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens horaire.
  Afficher `100 gr` (pas de symbole °).
  **Unité d'affichage (option, 2026-10-20)** : Affichage → *Unité des angles*
  (Grades / Degrés), réglage de poste `SettingsStore.angle_unit`. **Le modèle,
  les fichiers et le diagnostic restent TOUJOURS en grades** (400 gr = 360°,
  25 gr = 22,5°) : l'option ne change que l'affichage, la saisie et les
  exports. Source unique `angle_units.py` (pur) : toute chaîne d'angle passe
  par `fmt`/`nombre`/`valeur`/`suffixe`/`titre_colonne` — **jamais de « gr » en
  dur** — et toute saisie par `angle_units.parse`/`depuis_unite` (retour en
  grades). `dialogs_shared.grade_choices`/`find_grade_choice`/`parse_grade`
  (libellés `100 gr — E` ou `90° — E`), `angle_head`/`largeur_head`/
  `largeur_label`/`largeur_grades_saisie` pour les champs. Bascule à chaud
  (`App.action_set_angle_unit`) via `refresh_unit()` des panes Sondages/
  Contreforts/Dégradations + `_redraw_all` (diagnostic) ; dialogues et exports
  lisent l'unité à l'ouverture/génération. Les exports (PDF, XLSX, HTML, CSV,
  synthèse, comparaison) suivent l'unité choisie. **Piège** : `_(variable)`
  est invisible au test d'i18n — les libellés d'unité sont des littéraux dans
  `angle_head`/`largeur_*`, mais l'en-tête d'export « Angle (°) » passe par
  `_(h)` (vérifié à la main : traduction ajoutée en EN/IT).
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante).
  Quand le rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon **local** (0–1). **Chaque direction** (sondée ou
  extrapolée) est classée individuellement Vert/Orange/Rouge par le barème
  (`DiagnosticSnapshot.vert/orange/rouge`, répartition en % du périmètre).
  La **classe mise en avant** (publiée) est celle du **t/R minimal** des 16
  directions (biomécanique : la rupture part de la paroi la plus mince —
  **aucun t/R moyen** n'est calculé ni publié ; décision 2026-10-18, remplace
  l'ancienne règle « moyen »). `classe_globale` reste le nom du champ (cépée :
  pire brin fiable). Les seuils du barème n'ont pas à être « revalidés » : ils
  s'appliquent à chaque direction, le minimum ne fait que désigner celle qui
  est mise en avant.
- **Genet / brin (ramet)** : `Arbre` = individu inventorié (= *genet*) ; il porte
  l'identité partagée + une liste de `Brin` (= *ramets*, ≥ 1). Un arbre mono-caule
  = un genet à brin unique ; une **cépée** = plusieurs brins. La géométrie et les
  mesures (rayon, sondages, dégradations, contreforts, position) vivent sur le
  **brin** ; des propriétés-relais sur `Arbre` (→ `brins[0]`) gardent le code écrit
  avant les cépées fonctionnel. **Cépée** : `Arbre.ajouter_brin` / `supprimer_brin`
  (boutons « ＋ Brin » / « − Brin » de l'onglet Identification) ; les brins sont
  composés par `_pil_draw_cepee` / `SectionCanvas._draw_cepee` via le cadrage pur
  `geometry.brins_layout` (mono-brin centré = chemin verbatim → goldens intacts).
  Une cépée étant large, `brins_layout` la cadre sur la largeur ; les deux
  renderers **centrent ensuite verticalement** les brins (post-ajustement de
  `origin_y`) ; en **export PNG** (`show_legend`), la **légende** occupe la
  bande basse. **Échelle radiale par brin** : chaque brin (mono-brin compris)
  porte sa propre échelle graduée — « 0 » au centre, multiples du pas
  adaptatif (repli : graduation **médiane** si aucun multiple ne tient →
  toujours ≥ 1 segment intermédiaire), terminal « N cm » au **bout de
  l'écorce** (R+ep) — le long de l'axe **Est**, ou de la direction libre la
  plus proche si un sondage y est rendu **et que les sondages sont affichés**
  (esquive pure `geometry.radial_ruler_grade`, conditionnée à
  `show_sondages` — masqués, pas de flèche à éviter → plein Est ; géométrie
  `geometry.radial_ruler_data` ; dessin `_pil_draw_echelle_radiale` /
  `SectionCanvas._draw_echelle_radiale`).
  Dessinée **en dernier** (premier plan) avec halo blanc pour rester lisible
  par-dessus cavité/dégradations. A remplacé la règle -R..+R du mono-brin et
  la barre « N cm » de la cépée (les brins ont des rayons distincts — une
  échelle par brin est la seule lecture fiable).
  **Diagnostic cépée** : `diagnostic.genet_diagnostic(arbre)` agrège un
  `repartition_classes_brin(section, port)` par brin → classe globale = **pire
  classe parmi les brins fiables** (rayon + ≥3 sondages) ; un brin non fiable
  est rapporté mais ne bloque pas (fiabilité par brin). Propagé partout
  (pastille de liste, onglet, fiche PDF, synthèse mission, exports PRBS) avec
  un détail par brin. **Chantier cépées/formes : Étapes 0-4 FAITES** (brin +
  ovale + rendu/saisie + diagnostic multi-brins + sélecteur de brin + éditeur
  de disposition souris) ; détail dans la mémoire `project_cepees-formes` et
  `.claude/docs/archives/cepees-plan.md`. **Brin courant (4a)** : `App._current_brin()` /
  `_current_brin_idx` (remis à 0 au changement d'arbre, borné si un brin est
  retiré) / `set_current_brin(idx)` ; barre « Brin a/b/c » au-dessus des onglets
  (`_refresh_brin_selector`, masquée pour un mono-caule). Les onglets
  **Sondages/Dégradations/Contreforts** et la **géométrie** de l'onglet
  Identification (rayon/diamètre/écorce/forme) éditent `_current_brin()` ;
  l'identité (n°, essence, port, hauteurs, mèche) reste **genet**. Les dialogues
  `edit_sondage/degradation/contrefort` acceptent `Section = Union[Arbre, Brin]`.
  En complément du sélecteur, les grilles **Sondages/Dégradations/Contreforts**
  affichent en tête un **écho du brin courant** (`_brin_title`, accent, « ▸ Saisie
  du brin b ») — au plus près des yeux pendant la saisie, pour ne pas remplir une
  grille sur le mauvais brin ; dépacké (invisible) en mono-caule → pane inchangé.
  **Disposition de la cépée (4b)** : `dialogs.ask_cepee_layout` (canvas,
  glisser-déposer les brins → `pos_x/pos_y` ; brin « a » = ancre fixe en (0,0) ;
  contour fidèle via `contour_polygon`, **écorce comprise** si mesurée
  (anneau via `geometry.ring_polygon_points`, comme les renderers — sans ça
  deux brins qui se chevauchaient une fois l'écorce comptée semblaient avoir
  un écart, seul le bois était tracé ; le rayon de détection au clic/glisser
  compte aussi l'écorce), cadrage figé par `brins_layout` ; travail
  sur copie → Annuler = no-op). `App.edit_cepee_layout` applique (undo + redraw) ;
  bouton « Disposition… » de l'onglet Identification (activé si ≥ 2 brins). La
  **rotation** d'un brin (`rotation_grades`) est éditable à la **molette** dans
  cet éditeur et **appliquée au rendu** (Tk + PIL) : les helpers purs
  `contour_polygon` / `cavity_polygon` / `contrefort_zone_outline` /
  `degradation_externe_outline` / `diagnostic.sondage_render_data` prennent un
  `rotation_grades` (défaut 0.0) qui **décale l'angle de placement** tout en
  évaluant le rayon au grade LOCAL → la forme (rayon variable comprise), la
  cavité, les sondages, contreforts et dégradations pivotent ensemble ; la
  **boussole** (ticks/cardinales) reste au Nord du monde. Un **cercle étant
  invariant par rotation**, le cas circulaire garde sa primitive native
  (`create_oval`/`d.ellipse`) → goldens byte-identiques (`rotation_grades=0`
  ⟹ `g+0.0==g`). Le diagnostic (classes, t/R) est inchangé : la rotation est
  purement visuelle.
- **Diamètre local par direction** : un tronc n'est jamais parfaitement
  cylindrique. `Brin.diametres_locaux: Dict[int, float]` (grade → diamètre
  cm) porte les diamètres mesurés à certaines des 16 directions — **INDÉPENDANT
  de tout sondage** : une direction peut avoir un diamètre local sans PRBS
  mesurée là (p. ex. un méplat repéré au pied à coulisse entre deux sondages,
  sans multiplier les mesures au résistographe — sinon les directions
  intermédiaires retombent sur le diamètre général et le contour « vague »
  au lieu de suivre le méplat réel). Une direction absente de la table
  retombe sur le diamètre général du brin (`Brin.rayon_tronc_cm`, onglet
  Identification). Source unique : `Brin.rayon_a_grade(grade)` — lecture
  exacte de la table des 16 rayons locaux (`Brin._rayon_locaux`) aux grades
  canoniques (sondages, dégradations, contreforts, diagnostic) ; entre deux
  directions mesurées voisines, **interpolation lissée par cosinus**
  (`(1-cos(π·t))/2`) — raccord à dérivée nulle à chaque direction mesurée
  (pas d'angle vif, contour moins « facetté » qu'une interpolation linéaire
  pure) tout en restant **strictement bornée** entre les deux valeurs
  voisines (jamais de dépassement, contrairement à une spline type
  Catmull-Rom) — pour le contour dessiné, échantillonné à des grades
  quelconques (`geometry.contour_polygon`). D'où le t/R local ci-dessus.
  `Brin.a_rayon_variable` (True si un rayon local diffère du général)
  pilote, comme l'ancien `est_ovale`, le choix entre la primitive cercle
  native et `contour_polygon` dans les deux renderers. Saisie **en ligne**
  dans la grille Sondages (colonne « Ø local (cm) », optionnelle, **toujours
  active** — pas de dépendance à un sondage sur la ligne) via
  `Brin.set_diametre_local(grade, diametre_cm)` (réaligne le bois altéré du
  sondage éventuellement présent à cette direction, **sans jamais retoucher
  sa PRBS** ; borne la profondeur des dégradations co-localisées) — pas
  d'éditeur séparé (a remplacé le tronc ovale à 2 axes,
  `rayon_petit_axe_cm`/`orientation_grade`/`ask_forme_tronc`, strictement
  moins expressif : jusqu'à 16 points mesurés au lieu de 2). Fichiers
  antérieurs à cette fonctionnalité : la forme ovale n'est pas migrée, ils
  repassent en section circulaire au chargement (clés JSON orphelines
  silencieusement ignorées) ; un diamètre local qui vivait encore sur le
  `Sondage` (version transitoire du 2026-08-19) est migré vers
  `Brin.diametres_locaux` au chargement (`persistence._brin_from_dict`).
- **Diagnostic non fiable si < 3 sondages** → exports masquent t/R minimal + classe.
  **Couverture angulaire (2026-10-28)** : avec ≥ 3 sondages mais un secteur > 180° (200 gr) sans aucun sondage, la classe reste publiée et un **avertissement non bloquant** s'affiche (`diagnostic.couverture_insuffisante` / `couverture_avertissement` ; onglet Diagnostic, fiche PDF, tableau PRBS, colonne « Couverture sondages » de la synthèse).
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain −
  profondeur_bois_deg`. **L'écorce n'est jamais du bois sain** (le rayon est
  déjà sous écorce) — invariant. Le champ `DegradationExterne.comprend_ecorce:
  bool = True` décrit la **géométrie** de la dégradation. Saisi via le
  sélecteur **« Zone dégradée »** (combobox *readonly* « Écorce + bois »
  [True, défaut] / « Bois seul » [False]) de la grille **et** du dialogue
  `edit_degradation` — libellés et helpers source-unique dans `dialogs`
  (`ZONE_DEGRADEE_CHOICES` reste la forme française canonique, comparée
  telle quelle ; `zone_degradee_label`/`zone_degradee_choices()` traduisent
  à l'affichage via `_()`, `zone_degradee_to_bool` reconvertit — même piège
  que les filtres avancés : ces trois helpers passent une **variable** à
  `_()`, invisible au test `test_i18n.py`, vérifié à la main),
  rappel `ZONE_DEGRADEE_AIDE` sous la grille. A remplacé une case à cocher
  nue dont le sens et l'impact PRBS étaient illisibles sur le terrain :
  - **comprend l'écorce** (défaut) : la zone dégradée part de la **surface
    extérieure** (écorce visuellement dégradée). La bande d'écorce traversée
    ne réduit pas la PRBS → `profondeur_bois = max(0, profondeur −
    épaisseur_écorce)`.
  - **commence sous l'écorce** : l'écorce reste **intacte** au dessin, la
    dégradation part de la **surface du bois** → toute la profondeur est du
    bois perdu.
  Pilote à la fois le **calcul** (helper pur
  `DegradationExterne.profondeur_bois_cm(ep)`, utilisé par
  `diagnostic.degradation_externe_par_grade`/`degradation_ecretee`) **et le
  rendu** (`geometry.degradation_externe_outline`). **Rendu** : la dégradation
  suit **toujours** la saillie des contreforts (cloche `bell_max(g)`, le bois
  gonfle), dans les deux modes ; le rayon de départ est `R + bell + ep` si elle
  comprend l'écorce, `R + bell` sinon. Le bord externe est prolongé d'un léger
  **recouvrement anti-couture** (`geometry._BARK_SEAM_PX`, ~1 px, dans les deux
  modes) : deux remplissages jointifs (dégradation / écorce ou / bord
  d'écorce) laissent sinon un liseré d'anti-aliasing (bois ou fond) visible
  entre eux. Cas par défaut (True) ⟹ dessin **inchangé** → goldens intacts.
  Fichiers antérieurs corrigés rétroactivement (défaut True au load).
  **Convention confirmée (protocole terrain)** : le sondage mesure la paroi
  **totale** en ignorant la dégradation externe (mèche posée à côté de la
  zone dégradée) — l'app déduit ensuite la profondeur. **Fusion** : les deux
  zones dégradées (altération centrale + bande périphérique) ne peuvent pas
  cumuler plus que le rayon — `prbs_par_grade` écrête à 0 (= union des
  zones), valeur utilisée partout (pastille, tableaux, exports). L'écrêtage
  est **signalé, pas silencieux** : garde-fou non bloquant « ⚠ » ambre
  (`COLOR_WARN`) sur la colonne Altéré de la grille de sondages, sur la
  ligne de dégradation fautive (tooltip) et dans le tableau PRBS de
  l'onglet Diagnostic. Helpers purs `diagnostic.fusion_ecretee_par_grade`
  (par direction) / `degradation_ecretee` (par objet — ne marque pas la
  voisine mitoyenne d'un arc profond). Recalcul via
  `refresh_fusion_warnings()` des deux panes, câblé sur `App._redraw_all`
  (labels en lecture seule uniquement → sûr pendant la frappe).
- **Pastille sondage = PRBS ajustée** (jamais brute).
- **Contreforts** = cloche cosinus², fusion si adjacents (`contrefort_zones`).
- **Écorce** = visuelle pour le rayon (R_ext = R + ep, le bois sain reste
  mesuré sous écorce). **Seule incidence sur le diagnostic** : son épaisseur est
  déduite de la profondeur des dégradations externes qui **comprennent l'écorce**
  (cf. ci-dessus) — l'écorce abîmée ne compte pas comme bois sain perdu.
- **COLOR_BARK ≠ COLOR_ROT** : ne jamais unifier (contraste dégradation/écorce).
- **Barème configurable par groupes de ports** : les seuils Vert/Orange/Rouge
  sont un réglage de **poste** (`~/.penetrometre/bareme.json`), organisé en
  **groupes de ports librement composés par l'expert** — `bareme.GroupeBareme`
  (`nom`, `ports: Tuple[str,...]`, `seuil_vert`, `seuil_orange`), `_groupes`
  (état module, remplace un ancien binôme figé « libre »/« strict »). Un
  **port individuel** n'est qu'un groupe à un seul port : aucune distinction
  de code entre « régler port par port » et « regrouper des ports » — c'est
  la même mécanique. `GROUPES_DEFAUT` (2 groupes, mêmes seuils qu'avant cette
  fonctionnalité) reste la **valeur par défaut** de tout nouveau poste et du
  bouton « Restaurer » de l'éditeur. `classer_prbs(ratio, port)` cherche le
  groupe courant contenant ce port (`groupe_pour_port`) ; si aucun (config
  altérée à la main) retombe sur le groupe de `GROUPES_DEFAUT` couvrant ce
  port — jamais de crash, jamais un classement arbitraire silencieux.
  **Éditeur** (`Affichage → Barème…`, `dialogs_settings.ask_bareme_settings`) :
  une ligne éditable par groupe (nom, seuils Vert/Orange, suppression) +
  un **tableau d'assignation port → groupe** (une `tk.StringVar` par port,
  partagée par ses `Radiobutton` dans chaque colonne-groupe) — l'exclusivité
  Tk native **garantit par construction** qu'un port appartient à exactement
  un groupe, jamais par validation a posteriori (même philosophie que la
  grille Sondages). Supprimer un groupe réaffecte ses ports au groupe
  précédent (jamais d'orphelin) ; un dernier groupe ne peut pas être
  supprimé. Seule validation a posteriori : chaque groupe a ≥ 1 port et
  `0 < orange < vert ≤ 1`.
  **Traçabilité** (inchangée dans son principe) : deux opérateurs aux
  réglages différents classent les mêmes mesures différemment. Les groupes
  **en vigueur à l'enregistrement** sont écrits dans la mission
  (`Chantier.bareme_seuils`, forme brute JSON — liste de
  `{"nom":.., "ports":[...], "vert":.., "orange":..}`, un par groupe ; champ
  **duck-typé**, `model.py` ne dépend pas de `bareme.py`) et **cités dans
  chaque livrable** : pied de la fiche PDF, bannière des exports XLSX/HTML,
  ligne `# Barème appliqué` en tête des CSV. Source unique des libellés :
  `bareme.description_seuils` / `description_seuils_mission`. Frontière
  JSON : `groupes_vers_brut`/`seuils_depuis_brut` (ce dernier **migre
  silencieusement** l'ancien format à 2 groupes fixes — postes et missions
  antérieurs à cette fonctionnalité — et comble tout port manquant d'une
  config incomplète par un groupe de secours). **Ouvrir une mission
  n'applique JAMAIS son barème** (ce serait reconfigurer le poste en douce) :
  l'écart est seulement signalé en barre d'état par
  `App._avertir_bareme_different`. Liste vide = mission antérieure à cette
  trace ⟹ « inconnu », pas de migration.
- **Unicité** : un seul sondage par direction, pas de dégradations qui se
  chevauchent (arcs mitoyens bout-à-bout autorisés), un seul contrefort par
  grade central. Sondages et contreforts : **garantie par construction**
  (grilles 16 directions, une ligne par grade). Dégradations : helper pur
  `model.degradations_chevauchements` (exclut les grades-frontières
  mitoyens), partagé entre `dialogs.edit_degradation` (clic Valider) et la
  saisie en place de `pane_degradations` (valeur fautive rétablie).
