# Journal des versions — Pénétromètre

La version applicative vit dans `penetrometre.__version__` (affichée
dans « À propos » et journalisée au démarrage). Format : `MAJEUR.MINEUR.CORRECTIF`.

## 3.5.0

### Fonctionnel (accessibilité & lisibilité)

- **Pastilles d'état à glyphes distincts** : la liste d'arbres utilise
  désormais `○` (vide) · `◐` (partiel) · `●` (fiable) au lieu d'un `●`
  unique coloré. La **forme** porte la complétude → lisible même en cas
  de daltonisme rouge-vert (fréquent chez les opérateurs) ; la couleur
  ne fait que renforcer.
- **Classe de risque dans la liste d'arbres** : dès qu'un arbre est
  fiable (≥3 sondages), la couleur de son `●` encode la **classe globale
  Silvavenir** (vert/orange/rouge) — on repère les arbres à risque d'un
  coup d'œil sans ouvrir l'onglet Diagnostic.
- **Contraste du texte secondaire** : `COLOR_MUTED` assombri
  (`#6E7B73` → `#55605A`) pour repasser au-dessus du seuil WCAG AA
  (≈6.5:1 sur blanc). Les libellés d'aide ⓘ en 9 px et les labels
  d'échelle du dessin (Tk + exports PNG/PDF) deviennent lisibles sur un
  laptop de terrain en plein jour. Golden-tests Tk régénérés
  (changement de couleur uniquement).

### Interne

- `_arbre_diag_fiable(a)` extrait pour le compteur du footer (≥3
  sondages) ; `_arbre_etat` consulte `repartition_classes` pour la
  couleur de classe. Tests `_arbre_etat` étendus (glyphes + classe).

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
