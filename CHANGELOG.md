# Journal des versions — Pénétromètre

La version applicative vit dans `penetrometre.__version__` (affichée
dans « À propos » et journalisée au démarrage). Format : `MAJEUR.MINEUR.CORRECTIF`.

## En développement (depuis 3.6.0)

### Sécurité

- **Chemins de photos confinés** (`photo_paths.py`, nouveau module pur) : un
  `.json` de mission reçu d'un tiers ne peut plus faire ouvrir ni embarquer
  un fichier arbitraire du poste. Whitelist d'extensions, chemins relatifs
  jailés dans le dossier de la mission (`..` et symlinks sortants
  neutralisés), chemins absolus tolérés pour compat mais signalés. La
  visionneuse système ne reçoit un fichier qu'après vérification qu'il est
  **réellement décodable comme image** (un `.desktop` renommé `.png` était
  exécuté par `xdg-open`). Le motif de refus est affiché sur la vignette.
- **Licence durcie** (`license.py`) : toutes les décisions de date passent
  par `today_effectif()`, plancherée par un repère monotone
  (`~/.penetrometre/state.json`) — reculer l'horloge ne ressuscite plus une
  licence expirée ni un essai consommé ; une licence est refusée avant sa
  date d'émission (signée) ; la date de début d'essai est écrite en double
  pour qu'un `rm trial.json` ne rende pas 30 jours ; **le bouton « Essai
  gratuit » ne réapparaît plus après expiration** (`essai_deja_consomme()`,
  là où `get_trial_info()` renvoyait `None` aussi bien pour « jamais
  démarré » que pour « terminé » — un essai relançable indéfiniment depuis
  l'UI). `license.key`, `trial.json` et `state.json` en 0600, dossier 0700
  — **y compris sur les installations existantes** :
  `durcir_config_existante()` tourne à chaque démarrage et resserre ce qui
  est trop permissif. Une licence déjà installée n'étant jamais réécrite,
  elle serait autrement restée lisible par tous les comptes du poste.
- **Émission de licences** : `--machine-id` devient **requis**
  (`--any-machine` pour y renoncer sciemment) — une clé non liée valait
  pour un nombre illimité de postes. La clé privée vit désormais hors du
  dépôt (`~/.penetrometre-keys/`, ou `$PENETROMETRE_LICENSE_KEY`), `keygen` refuse
  d'écrire dans un dépôt git, et le hook `pre-push` bloque tout fichier de
  clé suivi par git.
- **Journal sans données personnelles** : l'email du titulaire est masqué
  (`license.masquer_email`) et les chemins de fichiers réduits au nom —
  le log est explicitement destiné à être envoyé au support.
- **URL de mise à jour validée** (`update_checker.url_de_release_sure`) :
  `html_url` vient d'une réponse HTTP distante et finissait dans
  `webbrowser.open` sans contrôle de schéma ni d'hôte.
- **CI** : actions épinglées par SHA de commit (dont l'action tierce
  `softprops/action-gh-release`, dans le job qui porte `contents: write` et
  les secrets de signature) + `permissions: contents: read` par défaut.

### Performance

- **Export PDF de mission non bloquant** : fenêtre de progression avec
  **Annuler** (`dialogs.ProgressDialog`) et boucle qui rend la main à Tk
  entre chaque fiche. Une mission de 300 arbres gelait la fenêtre ~20 s,
  jusqu'à la faire déclarer « ne répond pas » par l'OS. L'écriture du
  fichier n'a lieu qu'une fois **toutes** les fiches produites : une
  annulation ne laisse aucun PDF partiel.
- **Rendu PIL 2,5× plus rapide** : les objets police sont mémorisés
  (`pil_render._pil_font`, `lru_cache`). Chaque `d.text(...)` rouvrait le
  `.ttf` et repartait d'un cache de glyphes vide ; le halo des lettres
  cardinales tire 24 tracés par lettre. Fiche PDF : 130 → 63 ms par arbre.
  Goldens PIL byte-identiques.
- **Liste d'arbres** : `_arbre_etat` (donc `genet_diagnostic`) n'est plus
  calculé deux fois par arbre quand un filtre de risque est actif — ~60 →
  ~30 ms par frappe dans le champ de recherche sur 300 arbres.
- **Redimensionnement débouncé** : `SectionCanvas` regroupe ses
  `<Configure>` (80 ms) au lieu de se redessiner intégralement à chaque
  pixel de glissement d'une poignée de la `PanedWindow`.

### Fiabilité du livrable

- **Barème tracé dans les livrables** : les seuils Vert/Orange/Rouge sont un
  réglage de poste ; rien n'indiquait lesquels avaient produit une classe.
  Ils sont désormais enregistrés dans la mission (`Chantier.bareme_seuils`)
  et cités en pied de fiche PDF, dans les exports XLSX/HTML et en tête des
  CSV. Ouvrir une mission n'applique **pas** son barème (ce serait
  reconfigurer le poste) : l'écart est signalé en barre d'état.
- **CSV des sondages : les cépées ne sont plus tronquées.**
  `export_csv_mission` bouclait sur `Arbre.sondages`, propriété-relais vers
  `brins[0]` : les sondages des brins b, c… disparaissaient du fichier sans
  le moindre signal. L'export itère les brins et ajoute une colonne
  « Brin » (vide en mono-caule).
- **Rectangle blanc dans l'écorce à rayon variable** : peindre un anneau
  (écorce, contreforts) comme un seul polygone « contour externe + interne
  inversé » refermait la forme via deux jointures à des angles légèrement
  différents au lieu du même angle aller-retour, laissant un fin coin non
  rempli — toujours au Nord, visible dès qu'un diamètre local ou un
  contrefort était modifié. Nouveau helper `geometry.ring_polygon_points`
  (technique du trou de serrure correcte), utilisé dans les deux renderers
  (Tk + PIL).
- **Éditeur de disposition de cépée : le chevauchement réel est enfin
  visible.** `dialogs.ask_cepee_layout` ne traçait que le contour du bois,
  jamais l'écorce : deux brins qui se chevauchaient une fois l'écorce
  comptée semblaient avoir un écart. L'éditeur trace maintenant l'anneau
  d'écorce et le rayon de détection au clic/glisser en tient compte.

### Fonctionnel — Commercialisation & distribution

- **Système de licence offline Ed25519** : activation par clé + identifiant
  machine (SHA-256[:12] de `/etc/machine-id` / `ioreg` / registre Windows).
  Dialog d'activation bloquant au démarrage (bundle uniquement, sauté en
  développement). `license.py` + `dialogs_license.py`.
- **Mode essai 30 jours** : bouton dans le dialog d'activation (caché si
  essai déjà démarré) ; bannière persistante dans l'app avec compte à rebours
  et lien vers l'activation. Fichier `~/.penetrometre/trial.json` (atomique).
- **Machine binding** : option `--machine-id` dans `gen_license.py` pour
  lier une clé à une machine précise. Sous-commande `machine-id` pour obtenir
  l'ID sans lancer l'app.
- **Guide de démarrage** : `docs/guide_demarrage.html` autonome (2 pages A4,
  CSS embarqué, bouton Imprimer). Accessible via **Aide → Guide de démarrage**.
- **Canal de support intégré** : **Aide → Contacter le support** → dialog
  avec email/Machine ID/version (boutons Copier), lien `mailto:` pré-rempli,
  accès direct au fichier de log. Contact : `e.colinet@silvavenir.fr`.
- **Barème t/R configurable par groupes de ports librement composés** :
  l'expert compose lui-même les groupes de ports partageant un seuil
  Vert/Orange/Rouge — un port individuel, ou plusieurs regroupés, au choix
  (`bareme.GroupeBareme`). Éditeur revu (**Réglages → Barème…**,
  `dialogs_settings.ask_bareme_settings`) : liste de groupes éditables +
  tableau d'assignation port → groupe où l'appartenance à un seul groupe
  est garantie par construction (boutons radio partageant une variable par
  port), jamais par validation a posteriori. La répartition d'origine
  (libre/semi-libre/délaissé vs architecturé/traumatique) reste la valeur
  par défaut. Persisté dans `~/.penetrometre/bareme.json` ; migration
  silencieuse de l'ancien format à 2 groupes fixes (postes et missions
  existants).
- **Vérification des mises à jour** : `update_checker.py` interroge l'API
  GitHub Releases au démarrage (timeout 2 s, best-effort). Désactivable via
  **Aide → Vérification automatique au démarrage**.
- **EULA & confidentialité** : `PRIVACY.md` + `EULA.txt` ; lien dans
  **Aide → À propos**.
- **Workflow de signature de code** (`.github/workflows/build.yml`) :
  support conditionnel `signtool.exe` (Windows) et `codesign` + `notarytool`
  (macOS) — actif si les secrets `CODESIGN_P12_BASE64` sont configurés.

### Fonctionnel — Internationalisation

- **i18n anglais + italien** : infrastructure `i18n.py` (`_("…")` wrapper
  gettext) + catalogues `translations/en.py` et `translations/it.py`.
  Couvre UI complète, exports PDF/XLSX, dialogues, labels d'état, aide.
  Sélecteur **Affichage → Langue** (redémarre l'app). Verrouillé par
  `test_i18n.I18nCompletenessTests`.

### Fonctionnel — Nouvelles fonctionnalités

- **Galerie photos par arbre** (`photo_gallery.py`) : onglet Identification,
  dossier compagnon `<mission>_photos/`, undo-able. Page photo optionnelle
  dans la fiche PDF (intégrée via `fiche_pdf.py`).
- **Modèles de mission** (`template_store.py`) : **Fichier → Nouveau depuis
  un modèle…** sauvegarde/charge un gabarit (méta, opérateur, barème)
  sans les arbres.
- **Profil opérateur** : historique des opérateurs récents (combobox
  pré-remplie), nom visible dans les exports PDF.
- **Import CSV terrain** : **Fichier → Importer des données CSV…** — dialog
  de mapping colonnes → champs modèle (N° arbre, rayon, sondages par grade).
- **Champs Client et Référence chantier** sur la mission (méta).
- **Filtres avancés dans la liste d'arbres** : filtre par échéance +
  complétude (en plus du filtre texte et classe de risque existants).
- **Checkliste de complétude avant export mission** : avertissement si des
  arbres sont incomplets ou sans préconisation.
- **Marquage sondage incertain** : flag par sondage, visible sur la grille.
- **Colonne Commentaire inline** dans la grille des sondages.
- **Dégradation externe par clic-glissé** : tracer un arc directement sur
  le canvas en maintenant le clic (sans ouvrir le dialog).
- **Raccourcis clavier découvrables** via tooltips sur les boutons principaux.
- **Écran de bienvenue** : panneau central au démarrage (pas de mission
  ouverte) avec affordances contreforts et raccourcis.
- **Sauvegardes glissantes** (`persistence.write_backup`) : copie horodatée
  à chaque enregistrement réussi (`~/.penetrometre/backups/`, 12 max/mission).
  **Fichier → Ouvrir le dossier des sauvegardes…**.
- **Infobulle de commentaire** au survol des sondages/dégradations/contreforts
  sur le canvas.
- **Diamètre local par direction** : un tronc n'est jamais parfaitement
  cylindrique. Colonne « Ø local (cm) » dans la grille Sondages,
  **indépendante de tout sondage** (utilisable même sans PRBS mesurée à
  cette direction — méplat repéré entre deux sondages sans mesure au
  résistographe supplémentaire). Interpolation lissée par cosinus entre
  directions mesurées voisines (contour naturel, jamais de dépassement des
  valeurs mesurées). Un Ø local ne peut jamais donner un rayon inférieur au
  bois sain déjà saisi sur la même ligne (relevé au minimum valide,
  signalé). A remplacé le tronc ovale à 2 axes (jusqu'à 16 points mesurés
  au lieu de 2).
- **En-tête de mission compacté** : Client/Opérateur/Date remontés sur la
  même ligne que Mission/Adresse (gain de place et de lisibilité).

### Interne / Architecture

- **Extraction de 2 mixins supplémentaires** : `app_layout.LayoutMixin`
  (construction de l'UI) + `app_reglages.ReglagesMixin` (préférences +
  mises à jour). `App` passe de 4 à **6 mixins**.
- **Undo scopé** : `capture_undo_snapshot()` produit un snapshot arbre seul
  `{"_type":"arbre","_idx":int,"_arbre":Arbre}` (O(1)) au lieu d'un JSON
  complet du chantier. `push_undo_snapshot()` + `set_live_tip()` idempotent.
- **Cache `_etat_cache`** : `dict[int, tuple[str, str, str]]` keyed by
  `id(arbre)` évite les doublons de `genet_diagnostic()` entre
  `_refresh_tree_arbres` et `_update_etat_footer`.
- **mypy propre sur 40 fichiers** (exit 0, `python_version = 3.10`).
  Stubs PIL via `[mypy-PIL.*] ignore_missing_imports = True`.
- Retrait de toutes les références à "Silvavenir" (projet personnel d'Edwin
  Colinet — contact `e.colinet@silvavenir.fr`).

## 3.6.0

### Fonctionnel (accessibilité & ergonomie)

- **Taille du texte réglable** (menu **Affichage → Taille du texte** :
  Petit / Normal / Grand / Très grand). Agrandit tout le texte de
  l'interface pour rester lisible sur écran HiDPI ou laptop de terrain
  en plein soleil. Réglage persisté dans `~/.penetrometre/settings.json`
  (`app_settings.SettingsStore`, pur). Implémenté en multipliant la
  taille des polices (`ui_fonts`) — `tk scaling` s'avérant inopérant sur
  plusieurs builds Tk/Linux. Appliqué à chaud ; un redémarrage garantit
  une mise à jour complète. Le dessin de section n'est pas affecté.
- **Progression visible dans les onglets** : les onglets de l'étape sont
  préfixés d'un glyphe d'avancement (`○` à faire · `◐` en cours · `●`
  prêt) — Identification, Sondages, Diagnostic. Le notebook transmet
  désormais le sens du protocole (identifier → sonder → diagnostiquer),
  avec le même vocabulaire de formes que les pastilles de la liste
  d'arbres (lisible en daltonisme).

### Interne

- `app_settings.py` et `ui_fonts.py` (sections mypy strictes) ; tests
  `TestSettingsStore` (défaut, persistance, bornage, JSON corrompu),
  `TestUiFonts` (mise à l'échelle, identité à 1.0) et test de
  progression des onglets (`_refresh_tab_progress`). Total : 221 tests.

## 3.5.0

### Fonctionnel (accessibilité & lisibilité)

- **Pastilles d'état à glyphes distincts** : la liste d'arbres utilise
  désormais `○` (vide) · `◐` (partiel) · `●` (fiable) au lieu d'un `●`
  unique coloré. La **forme** porte la complétude → lisible même en cas
  de daltonisme rouge-vert (fréquent chez les opérateurs) ; la couleur
  ne fait que renforcer.
- **Classe de risque dans la liste d'arbres** : dès qu'un arbre est
  fiable (≥3 sondages), la couleur de son `●` encode la **classe globale
  Pénétromètre** (vert/orange/rouge) — on repère les arbres à risque d'un
  coup d'œil sans ouvrir l'onglet Diagnostic.
- **Contraste du texte secondaire** : `COLOR_MUTED` assombri
  (`#6E7B73` → `#55605A`) pour repasser au-dessus du seuil WCAG AA
  (≈6.5:1 sur blanc). Les libellés d'aide ⓘ en 9 px et les labels
  d'échelle du dessin (Tk + exports PNG/PDF) deviennent lisibles sur un
  laptop de terrain en plein jour. Golden-tests Tk régénérés
  (changement de couleur uniquement).

- **Aide contextuelle repliable** : les libellés d'aide ⓘ qui restaient
  affichés en permanence (identification, sondages, canevas) passent
  derrière un en-tête cliquable « ⓘ Aide ▸ » — repliés par défaut (écran
  désencombré pour l'opérateur expérimenté), dépliables d'un clic à la
  première utilisation. Nouveau widget réutilisable `AideRepliable`
  (`aide_repliable.py`).

### Interne

- `_arbre_diag_fiable(a)` extrait pour le compteur du footer (≥3
  sondages) ; `_arbre_etat` consulte `repartition_classes` pour la
  couleur de classe. Tests `_arbre_etat` étendus (glyphes + classe).
- `aide_repliable.py` + tests `TestAideRepliable` (replié par défaut,
  toggle). Total : 212 tests.

## 3.4.0

### Fonctionnel

- **Export XLSX (tableau d'un arbre)** aligné cellule pour cellule sur la
  fiche de référence du cabinet : 3ᵉ entrée de légende pour le glyphe
  « — » (« Non renseignée/pas d'altération »), légende des classes
  « Classe verte/orange/rouge » colorée sous le pied, et légende collée
  au tableau (sans ligne vide). Données et calculs inchangés (déjà
  conformes). Verrouillé par `test_legendes_calquees_sur_la_fiche_du_cabinet`.

### Interne (pas de changement fonctionnel)

- **Découpage de la classe `App`** (`penetrometre.py` : ~1370 → ~940 l.)
  par responsabilité, pour contenir la croissance du fichier
  d'orchestration :
  - `app_arbres.ArbreListMixin` — panneau « Arbres de la mission »
    (filtre, pastilles d'état, navigation clavier, CRUD).
  - `app_recovery.RecoveryMixin` — autosave anti-crash + récupération
    de session (détient aussi `_RECOVERY_PATH` / `_AUTOSAVE_INTERVAL_MS`).
  - `app_export_actions.ExportActionsMixin` — les `action_export_*`.
  - `app_recent.RecentFilesStore` — historique des fichiers récents
    (composition, module pur testable sans Tk).
- **Tests** : +27 (`tests/test_app.py`) couvrant `RecentFilesStore`,
  `_arbre_etat` et les mixins de `App` en headless. Total : 209.
- mypy : nouveaux modules typés et ajoutés à la liste curée
  (`app_recent` strict ; mixins Tk au régime souple des panes).

## ≤ 3.3.0

Historique antérieur non formalisé (cf. `git log`). Jalons notables :
filtre de recherche d'arbres, ajout en série (hériter du précédent),
synthèse mission / hiérarchisation du risque, autosave anti-crash,
grille de saisie 16 directions, undo/redo, écriture atomique.
