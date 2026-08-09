# Chantier multi-poste / partage cabinet — cadrage

> **Statut** : 📋 **CADRAGE UNIQUEMENT** (08/07/2026). Ce document ne décide
> rien et n'implémente rien — il pose les options pour trancher plus tard,
> à la demande d'un client réel. Suite à `.claude/docs/commercialisation.md`
> (section 5).

## Constat

L'analyse commercialisation du 08/07/2026 relève qu'un cabinet à plusieurs
experts n'a aujourd'hui aucun moyen de **partager une mission** ou une base
d'arbres entre postes : chaque mission est un fichier `.json` isolé, ouvert
par un seul poste à la fois. `commercialisation.md` (P2-C) a déjà traité un
besoin voisin mais plus léger — le **profil opérateur** (nom affiché dans les
exports, historique local) — qui ne couvre pas le partage réel de données
entre plusieurs personnes.

Le même document liste explicitement **« Cloud sync »** en
**non-priorité** :

> Cloud sync — Complexité architecture, coût infra, hors scope desktop

Ce cadrage ne remet pas en cause cette décision. Il documente les options
**en dessous** du seuil « cloud sync », pour le jour où un cabinet
multi-agents devient un client réel (cf. priorité n°2 de l'analyse du
08/07 : valider avec 2-3 pilotes avant d'investir).

## Tension à préserver : le positionnement vie privée

`PRIVACY.md` et l'EULA (`LICENSE`, §5) affirment aujourd'hui : **« Le
Logiciel ne transmet aucune donnée à des serveurs tiers »**. C'est un
argument de vente concret (RGPD zéro-collecte) pour des cabinets
sensibles à la confidentialité des missions clients. Toute option
impliquant un serveur/cloud propre à Pénétromètre **casse cette promesse** et
doit être un choix produit assumé (changement de modèle, pas un ajout
incrémental) — pas quelque chose à faire « en passant ».

## Options, par niveau d'investissement

### Option 0 — Dossier réseau partagé (doc utilisateur, zéro code)
Le cabinet pose ses fichiers `.json` sur un lecteur partagé existant (SMB,
Google Drive, OneDrive…) déjà utilisé pour d'autres documents. Pénétromètre
n'a rien à faire de spécial : `persistence.py` écrit déjà de façon atomique
(`.tmp` + `os.replace`).

**Risque non couvert** : aucun verrou. Si deux personnes ouvrent la même
mission en même temps, la dernière à enregistrer écrase le travail de
l'autre silencieusement — pas de détection.

**Garde-fou minimal envisageable (petit dev)** : à l'ouverture, comparer
l'horodatage/hash du fichier sur disque à celui lu en mémoire avant chaque
`action_save` ; si le fichier a changé sous les pieds de l'utilisateur,
avertir au lieu d'écraser (pattern « conflit détecté », proposer
Enregistrer sous). Ne résout pas la fusion, évite juste la perte
silencieuse.

### Option 1 — Import/export « fusion » entre missions
Un cabinet où deux experts travaillent hors-ligne sur des copies
séparées (ex. terrain sans réseau) exporte/réimporte en fusionnant
arbre par arbre (par n°), avec résolution de conflit manuelle affichée
(« cet arbre a été modifié des deux côtés — lequel garder ? »).

**Effort** : modéré — logique de fusion pure testable (`persistence.py`
ou nouveau module), UI de résolution de conflit dans `dialogs.py`.
**N'exige aucun serveur.**

### Option 2 — Base partagée sur lecteur réseau (SQLite ou équivalent)
Remplacer le fichier JSON par mission par une base partagée (arbres +
missions dans un seul magasin de données) posée sur le même lecteur
réseau que l'option 0. Donne une vraie vue « base clients » du cabinet.

**Risque** : SQLite sur un partage SMB/NFS est **connu pour être fragile**
sous écriture concurrente (verrous fichier peu fiables sur ces
protocoles) — corruption possible. Nécessiterait soit un serveur SQLite
minimal (déjà un mini-backend), soit accepter la limite « un seul poste
écrit à la fois ».

**Effort** : important — refonte de `persistence.py`, migration du
format, UI de sélection multi-mission.

### Option 3 — Vrai backend cloud (sync temps réel, comptes)
Un service propre à Pénétromètre (serveur + comptes utilisateurs + sync).
Résout proprement le partage et la conurrence, mais :

- Contredit frontalement le positionnement « 100 % offline, zéro
  transmission » actuel — à retraiter dans `PRIVACY.md`/l'EULA/le
  discours commercial, pas juste techniquement ;
- Change le modèle économique (coût d'infra récurrent, hébergement,
  responsabilité sur des données clients hébergées) ;
- Chantier de plusieurs mois, non raisonnable avant d'avoir des clients
  payants qui le demandent explicitement.

**Non retenu tant qu'aucun client réel ne le réclame** (cf. décision
existante dans `commercialisation.md`).

## Recommandation

Ne rien construire avant un signal client concret. Si le besoin se
confirme avec un pilote réel :

1. Commencer par l'**option 0 + garde-fou anti-écrasement** (le plus
   petit changement qui évite le pire scénario — perte silencieuse de
   travail) ;
2. Ne passer à l'option 1 (fusion) que si le pilote travaille
   effectivement hors-ligne sur des copies séparées ;
3. Ne considérer les options 2/3 que si plusieurs cabinets structurés
   (pas un seul) le demandent — à ce stade, c'est un changement de
   produit qui mérite sa propre décision business, pas une itération.

## Décisions à trancher (plus tard, pas aujourd'hui)

| # | Question | Statut |
|---|----------|--------|
| 1 | Un pilote a-t-il exprimé ce besoin, ou est-ce anticipé ? | À vérifier avant tout dev (cf. priorité « 2-3 pilotes réels ») |
| 2 | Le garde-fou anti-écrasement (option 0) suffit-il pour le premier cabinet multi-agents ? | À trancher avec le client au moment venu |
| 3 | Si l'option 3 (cloud) devient nécessaire, qui héberge/porte la responsabilité RGPD ? | Hors périmètre technique — décision business |
