# Chantier commercialisation — Pénétromètre v3.x

Analyse critique du 20/06/2026. Objectif : commercialiser Pénétromètre Silvavenir
auprès de cabinets arboricoles extérieurs (projet personnel d'Edwin Colinet).

**Mise à jour du statut : 28/06/2026** — les items P1-B/C/D et P2-A/B/C/D
ont tous été implémentés (voir cases ✅ ci-dessous). P1-A (signature de code)
requiert des certificats payants à obtenir par Edwin.

**Mise à jour du statut : 08/07/2026** — nouvelle analyse critique orientée
commercialisation (repo privé, 0 release publiée, aucune page de vente —
constat : produit techniquement mûr mais go-to-market inexistant). Deux
actions lancées suite à cette analyse :

- **EULA (`LICENSE`)** : ajout d'une clause « Nature du logiciel — outil
  d'aide à la décision » (§7) précisant que le Logiciel ne se substitue pas
  au jugement professionnel de l'expert, et nuance de la limitation de
  responsabilité (§8) pour les cas où la loi française l'exclut
  (dommage corporel, faute lourde/dolosive). **Rédaction non-juriste** —
  à faire relire par un avocat avant toute vente réelle, vu l'enjeu
  sécurité (diagnostic de risque arboricole).
- **Statut juridique/facturation** : pas encore de structure enregistrée
  (auto-entrepreneur/EI/SASU) côté Edwin — nécessaire avant de facturer des
  clients pro (SIRET souvent exigé). Laissé de côté pour l'instant, hors
  périmètre technique.
- **Multi-poste / partage cabinet** revisité en cadrage (pas d'implémentation)
  dans `.claude/docs/multi-poste-plan.md` — options en dessous du seuil
  « cloud sync » (toujours non-priorité, cf. tableau ci-dessous), à activer
  seulement si un cabinet pilote réel le demande.

**Mise à jour du statut : 07/08/2026** — nouvelle analyse critique, cette
fois stratégique (go-to-market) plutôt que tactique : le produit est
techniquement mûr mais **aucune dépendance business n'est débloquée**
(pas de pilote réel connu, pas de structure juridique, pas de prix, pas de
signature de code). Détail en fin de document :
[§ Analyse critique du 07/08/2026 — angles morts stratégiques](#analyse-critique-du-07082026--angles-morts-stratégiques).

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
| Cloud sync | Complexité architecture, coût infra, hors scope desktop — options intermédiaires cadrées dans `.claude/docs/multi-poste-plan.md` |
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

---

## Analyse critique du 07/08/2026 — angles morts stratégiques

> Analyse orientée commercialisation, complémentaire du plan tactique
> P1/P2 ci-dessus (largement exécuté). Basée sur l'état du repo au
> 07/08/2026 : code, historique git, `LICENSE`/`PRIVACY.md`,
> `gen_license.py`, dossier `Communication/`.

### Photo chiffrée

- Solo dev, ~3 mois d'activité (08/05 → 06/07/2026), 295 commits,
  ~25k lignes Python hors `venv/`, 16 modules de test (goldens PIL+Tk,
  property-tests, mypy/ruff en CI).
- Repo **privé**, **0 tag/release publié** — aucun installeur n'a donc
  jamais été distribué à un tiers via le canal prévu (GitHub Releases).
- **Aucun prix nulle part** (code, docs, README) : ni tarif catalogue, ni
  palier, ni mode de facturation.
- Licence : Ed25519 offline + essai 30 jours, mais émission de clé
  **100 % manuelle en CLI** (`gen_license.py issue`) — pas de paiement en
  ligne, pas de flux self-service.
- `Communication/` (dossier dédié au matériel commercial) est **vide**.
- Aucune trace dans le repo (mémoire, docs, code) d'un client pilote,
  d'une facture ou d'un retour terrain externe.

### Ce qui est un vrai atout — à préserver

Le produit est sérieusement construit : undo/redo, autosave anti-crash +
sauvegardes glissantes, migration de format bidirectionnelle,
accessibilité (contraste, échelle de texte), i18n FR/EN/IT, barème
configurable, comparaison inter-missions avec export PDF, préconisation
exploitable en synthèse de mission. Un cabinet qui l'essaie sérieusement
verra un logiciel fini, pas un script interne. Le positionnement
« zéro télémétrie / 100 % offline » (`PRIVACY.md`) est un vrai argument
RGPD face à des concurrents cloud. **Le problème n'est donc pas
technique.**

### Angles morts critiques, par ordre d'impact

**1. Aucune validation marché.** Rien n'indique qu'un cabinet extérieur a
utilisé l'outil sur un vrai chantier et donné un retour. Les décisions
produit (cépées, comparaison inter-missions, barème configurable…)
semblent prises en solo sans boucle terrain. Ce document recommande
lui-même de « valider avec 2-3 pilotes réels avant d'investir » (cf.
recommandation multi-poste ci-dessus) — rien ne prouve que ça a été fait.
C'est le risque n°1 : continuer à construire sans savoir si ça répond à
un vrai frein d'achat.

**2. Le vrai concurrent n'est pas un logiciel, c'est le gratuit.** Les
fabricants de pénétromètres (IML/Resistograph en tête) fournissent en
général leur propre logiciel avec l'appareil — un cabinet qui a déjà payé
le matériel a donc déjà « un » outil, à coût marginal nul. L'autre
concurrent est le classeur Excel, cité par le README lui-même comme
référence historique. Vendre Pénétromètre Silvavenir suppose un discours de rupture très
concret (gain de temps sur la fiche PDF, fiabilité du calcul, image de
marque du rapport client) — rien n'indique que ce discours a été formulé
ni testé face à un cabinet.

**3. Facturation légalement impossible en l'état.** Pas de structure
enregistrée (auto-entrepreneur/EI/SASU) → pas de SIRET → pas de facture.
Déjà noté plus haut mais laissé « hors périmètre technique » sans
échéance — c'est pourtant bloquant avant toute vente réelle, même au
premier pilote.

**4. EULA non relu par un juriste, sur un produit à enjeu sécurité.** Le
§7 ajouté au `LICENSE` (« outil d'aide à la décision ») est un bon
réflexe mais reste une rédaction non-juriste sur un outil qui influence
des décisions d'abattage/sécurité publique (chute d'arbre = dommage
corporel possible). Une relecture avocat n'est pas du confort ici, c'est
un prérequis **avant la première facture** (le mode essai gratuit peut
continuer sans).

**5. Zéro distribution de confiance.** Signature de code non faite
(P1-A). Sans elle, un cabinet non technophile qui reçoit l'installeur
voit SmartScreen/Gatekeeper hurler à l'infection — ça tue la première
impression avant même l'ouverture de l'app. Coût faible (~400 €/an
cumulé Windows+macOS) pour un blocage total de conversion.

**6. Bus factor = 1, et pas à temps plein.** Le contact de licence
(`e.colinet@silvavenir.fr`) est distinct de l'e-mail pro d'Edwin — Pénétromètre Silvavenir
est un projet personnel séparé (cf. mémoire `project_penetrometre_perso`). Un
cabinet qui migre ses missions terrain vers ce format prend un risque de
continuité (support, correctifs, pérennité du format JSON) sur un projet
solo, non-officiel. Objection commerciale réelle à anticiper dans le
discours de vente ; l'export CSV/XLSX déjà présent est un bon filet de
secours à mettre en avant.

**7. Aucun canal de vente ni de visibilité.** Pas de site, pas de page
produit, pas de vidéo de démo, pas de témoignage. `docs/guide_demarrage.html`
sert l'onboarding *après* achat, rien n'amène un cabinet à découvrir
l'outil *avant*. Marché de niche (experts pénétromètre) qui se travaille
plutôt par réseau professionnel / salons / forums métier que par SEO —
aucune approche construite en ce sens à ce jour.

**8. Pas de mesure d'usage réel, par choix RGPD assumé.** Le
zéro-télémétrie est un bon argument de vente mais prive aussi Edwin de
tout signal produit (fonctionnalités réellement utilisées, points de
blocage). Compromis acceptable, mais qui referme la boucle sur le point 1
— sans pilotes actifs, aucune source de vérité produit.

### Recommandation priorisée

Ordre de **dépendances business**, pas d'ordre technique :

1. **Trouver 1 cabinet pilote réel** (pas hypothétique) et lui faire
   utiliser l'outil sur une vraie mission, avant d'ajouter quoi que ce
   soit. Seul levier qui débloque le reste (pricing crédible,
   priorisation des features, preuve pour convaincre d'autres cabinets).
2. **Statut juridique minimal** (auto-entrepreneur suffit pour démarrer)
   — sans ça, aucun euro facturable légalement, même au premier pilote.
3. **Fixer un prix**, même approximatif (licence annuelle par poste ? par
   cabinet ?) — actuellement inexistant, donc invendable même à un client
   convaincu.
4. **Signature de code** avant tout envoi à un cabinet non technique —
   ROI immédiat sur le taux de conversion « j'installe / je jette ».
5. **Relecture juridique de l'EULA** avant la première facture (pas
   avant le premier essai gratuit).

Tout le reste (i18n, cépées, comparaison inter-missions, multi-poste…)
est déjà au niveau, voire en avance sur le besoin réel d'un premier
client. Le risque principal aujourd'hui n'est pas « manque de
features », c'est **construire dans le vide sans boucle de vente**.
