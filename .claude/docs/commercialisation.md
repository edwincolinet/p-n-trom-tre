# Chantier commercialisation — Pénétromètre v3.x

Analyse critique du 20/06/2026. Objectif : commercialiser Pénétromètre
auprès de cabinets arboricoles extérieurs (projet personnel d'Edwin Colinet).

**Mise à jour du statut : 28/06/2026** — les items P1-B/C/D et P2-A/B/C/D
ont tous été implémentés (voir cases ✅ ci-dessous). P1-A (signature de code)
requiert des certificats payants à obtenir par Edwin.

---

## Priorités — Phase 1 : vendre à 1-2 cabinets (≈ 2 semaines)

### P1-A — Signature de code (BLOQUANT immédiat) — ⚠ À FAIRE (certificats payants)
**Problème** : installeurs Windows et macOS non signés → SmartScreen bloque
l'exécution, Gatekeeper empêche l'ouverture. Aucun client pro ne peut
recevoir un logiciel qui déclenche une alerte antivirus.

**Solution** :
- Windows : certificat EV Code Signing (~300 €/an, ex. Sectigo, DigiCert)
  → intégrer `signtool.exe` dans `.github/workflows/build.yml` après
  création du `.exe` PyInstaller.
- macOS : Apple Developer Program (~100 €/an) → `codesign` + `notarytool`
  dans le job macOS du workflow.
- Linux : AppImage non signé est acceptable (pas de Gatekeeper Linux).

**Fichiers concernés** : `.github/workflows/build.yml`

---

### P1-B — EULA + politique de confidentialité ✅ FAIT
**Problème** : aucun contrat d'utilisation, aucun `LICENSE` logiciel (seul
DejaVu a le sien). Impossible de facturer sans CGV/EULA. Requis par les
App Stores si distribution future.

**Solution** :
- Rédiger `LICENSE` (ex. propriétaire, tous droits réservés Edwin Colinet, ou
  AGPL si open-source assumé).
- Créer `PRIVACY.md` : données stockées localement uniquement, aucun
  télémétrie, aucun cloud, backups dans `~/.penetrometre/`.
- Afficher un lien « Licence & Confidentialité » dans **Aide → À propos**.
- Intégrer l'acceptation EULA dans l'installeur Inno Setup (checkbox avant
  installation, `build/installer.iss`).

**Fichiers concernés** : `LICENSE` (nouveau), `PRIVACY.md` (nouveau),
`build/installer.iss`, `penetrometre.py` (dialog À propos).

---

### P1-C — Mission d'exemple + guide de démarrage rapide ✅ FAIT
**Problème** : un nouvel utilisateur sans formation ne sait pas par où
commencer. Aucun tutoriel, aucune donnée d'exemple.

**Solution** :
- Créer `exemples/mission_demo.json` : mission fictive avec 5 arbres,
  variété de cas (sondages complets, incomplets, cépée, dégradation
  externe, préconisation remplie).
- Accessible via **Fichier → Ouvrir la mission d'exemple** (entrée dédiée
  dans le menu, ouvre en lecture seule ou copie dans Documents).
- Créer `docs/demarrage_rapide.pdf` : 2 pages, captures d'écran annotées
  (créer mission → saisir rayon → saisir sondages → export PDF).
- Lien dans **Aide → Guide de démarrage**.

**Fichiers concernés** : `exemples/` (nouveau), `app_menu.py`,
`app_fichier.py` (action_open_demo), `docs/` (nouveau).

---

### P1-D — Barème configurable ✅ FAIT
**Problème** : seuils t/R (Vert/Orange/Rouge par port) codés en dur dans
`bareme.py`. Chaque cabinet peut utiliser des référentiels différents
(VTA France, norme ISA, barème propriétaire). Impossible de vendre sans
recompiler.

**Solution envisagée** : exposer les seuils dans `~/.penetrometre/bareme.json`
(généré au premier lancement depuis les valeurs actuelles). Un dialog
**Fichier → Barème…** permet de les éditer (tableau : port → seuil Orange,
seuil Rouge). Un bouton « Restaurer les valeurs par défaut » recharge les
défauts.

**Impact** : `bareme.py` (charger depuis JSON si présent, fallback
hard-coded), `dialogs_settings.py` (nouveau dialog barème),
`app_menu.py` (entrée menu), `app_settings.py` (ou nouveau
`bareme_store.py`), `persistence.py` (migration : rien à migrer, barème
est indépendant des fichiers mission).

**Goldens** : non impactés (le barème courant reste le défaut).

---

## Priorités — Phase 2 : mise à l'échelle (≈ 1 mois)

### P2-A — Mise à jour automatique (in-app update check) ✅ FAIT
**Problème** : aucun mécanisme de mise à jour. Les corrections de bugs
n'atteignent pas les clients déjà installés.

**Solution minimale** :
- Au démarrage (ou **Aide → Vérifier les mises à jour**), interroger
  l'API GitHub Releases : `https://api.github.com/repos/…/releases/latest`
  → comparer `tag_name` avec `__version__`.
- Si version disponible : bandeau discret en barre d'état + lien de
  téléchargement. Pas d'installation automatique (risque sécurité).
- Timeout court (2 s), échec silencieux (pas de connexion → rien affiché).
- Option **Aide → Ne plus vérifier les mises à jour** (flag dans settings).

**Fichiers concernés** : `penetrometre.py` (check au démarrage via
`after(3000, …)`, `app_menu.py`, `app_settings.py`).

---

### P2-B — Internationalisation anglaise (expansion marché) ✅ FAIT (EN + IT)
**Problème** : 100 % français. Marché limité à la France/Belgique/Suisse
romande.

**État** : aucune infra i18n. ~150 chaînes UI à extraire.

**Solution** :
- Adopter `gettext` (stdlib Python) : `_("Texte")` sur toutes les chaînes
  visibles, catalogues `.po`/`.mo` dans `locale/fr/`, `locale/en/`.
- Sélecteur de langue dans **Affichage → Langue** (redémarre l'app).
- Les exports PDF/XLSX s'adaptent à la langue de l'interface (noms de
  colonnes, libellés classe).
- **Effort estimé** : 3-4 semaines (extraction + traduction + tests).

**Note** : chantier lourd, reporter après P1 complet.

---

### P2-C — Multi-utilisateur léger (cabinets multi-agents) ✅ FAIT (profil opérateur)
**Problème** : un seul opérateur par installation. Pas de profils, pas de
droits.

**Solution minimale** (sans serveur) :
- Profil « opérateur » par nom (choix au démarrage ou dans les réglages).
  Le nom apparaît dans les exports PDF (« Réalisé par : Prénom NOM »).
- Les fichiers missions restent locaux, pas de sync.

**Solution complète** (serveur requis) : non prévue dans ce chantier.

---

### P2-D — Import données externes ✅ FAIT (import CSV)
**Problème** : saisie 100 % manuelle. Aucune connexion avec les outils
terrain (IML RESI-PD, ArborPix, CSV tiers).

**Solution envisagée** :
- Import CSV paramétrable (colonnes : N° arbre, rayon, sondages par grade).
  Dialog de mapping colonnes → champs modèle.
- Pas d'intégration native RESI-PD (format propriétaire).

**Effort** : 2-3 semaines.

---

## Non-priorités (by design)

| Fonctionnalité | Pourquoi pas maintenant |
|----------------|------------------------|
| Cloud sync | Complexité architecture, coût infra, hors scope desktop |
| Mobile app | Tkinter non portable mobile |
| SaaS multi-tenant | Refactoring complet, 4-6 mois, nécessite décision business |
| Chiffrement des fichiers | Données non sensibles (pas de PII), overkill |
| Screen reader | Tkinter accessibility API très limitée |

---

## Ordre d'exécution suggéré

```
P1-B (EULA/Privacy)          → 1 jour   → base légale
P1-C (Mission demo)          → 3 jours  → onboarding immédiat
P1-D (Barème configurable)   → 1 semaine → déblocage commercial
P1-A (Signature de code)     → 2 jours  → distribution propre
─────────────────────────────────────────────────────────────────
P2-A (Update checker)        → 3 jours  → fidélisation clients
P2-C (Profil opérateur)      → 3 jours  → cabinets multi-agents
P2-B (i18n anglais)          → 4 semaines → expansion marché
P2-D (Import CSV)            → 2 semaines → confort terrain
```

---

## Décisions (tranchées le 20/06/2026)

| # | Question | Décision |
|---|----------|----------|
| 1 | Licence | **Propriétaire** — Edwin Colinet contrôle la distribution et la revente |
| 2 | Barème configurable | **Dialog in-app** avec validation (pas de JSON brut) |
| 3 | Update checker | **GitHub Releases** — gratuit, sans serveur propre |
| 4 | Profil opérateur | **Historique par opérateur** — nom dans exports + traçabilité |
| 5 | Mission d'exemple | **Lecture seule** — protège le fichier d'exemple, ouvre sans `current_file` |
