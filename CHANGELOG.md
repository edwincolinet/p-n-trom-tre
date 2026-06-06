# Journal des versions — Pénétromètre

La version applicative vit dans `penetrometre.__version__` (affichée
dans « À propos » et journalisée au démarrage). Format : `MAJEUR.MINEUR.CORRECTIF`.

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
