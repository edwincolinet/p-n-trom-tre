# Politique de confidentialité — Pénétromètre

**Logiciel :** Pénétromètre — Expertise arboricole au pénétromètre  
**Auteur :** Edwin Colinet  
**Date de mise à jour :** juin 2026

---

## 1. Principe général

Pénétromètre est une application **desktop autonome, 100 % hors ligne**.
Le logiciel **ne transmet aucune donnée** à des serveurs distants,
à des services cloud ou à des tiers. Aucune connexion réseau n'est
établie pendant votre travail, à l'exception de la vérification
optionnelle des mises à jour (voir §5).

---

## 2. Données stockées localement

Toutes les données générées par Pénétromètre sont stockées sur votre poste
dans le dossier `~/.penetrometre/` (Linux/macOS) ou
`%APPDATA%\Penetrometre\` (Windows) :

| Fichier / Dossier | Contenu | Durée de conservation |
|---|---|---|
| `settings.json` | Réglages UI (échelle, contraste, barème, opérateurs récents) | Conservé jusqu'à désinstallation |
| `recent.json` | Chemins des 8 derniers fichiers ouverts | Conservé jusqu'à désinstallation |
| `bareme.json` | Seuils t/R personnalisés (si modifiés) | Conservé jusqu'à suppression manuelle |
| `penetrometre.log` | Journal technique (erreurs, actions clés) | Rotation quotidienne, 5 fichiers max |
| `backups/` | Copies horodatées des missions (12 max par mission) | Supprimées automatiquement au-delà de 12 |
| `recovery/autosave.json` | Sauvegarde anti-crash temporaire | Supprimé dès l'enregistrement normal |

Les **fichiers de mission** (`.json`) sont enregistrés à l'emplacement
choisi par l'utilisateur — Pénétromètre n'impose pas de dossier.

---

## 3. Contenu des données

Les fichiers de mission contiennent des **données techniques
d'expertise arboricole** : numéros d'inventaire, essences, mesures de
sondage (rayon, PRBS, grade) et préconisations. Ces données ne
constituent pas des données personnelles au sens du RGPD, sauf si le
champ « Opérateur » ou « Adresse » est renseigné avec des informations
identifiantes.

---

## 4. Aucune collecte, aucun partage

- ✅ Aucune télémétrie d'utilisation
- ✅ Aucun identifiant de machine ou d'utilisateur collecté
- ✅ Aucune donnée transmise à l'auteur du logiciel ou à des tiers
- ✅ Aucun cookie, aucun tracker, aucun SDK d'analyse

---

## 5. Vérification des mises à jour (optionnelle)

Si la vérification automatique des mises à jour est activée
(Aide → Vérification automatique au démarrage), le logiciel interroge
**une seule fois au démarrage** l'API publique de GitHub Releases :

```
https://api.github.com/repos/edwincolinet/p-n-trom-tre/releases/latest
```

Cette requête transmet uniquement la **version courante du logiciel**
dans l'en-tête `User-Agent`. Aucune donnée personnelle n'est transmise.
La vérification peut être désactivée à tout moment depuis le menu Aide.

---

## 6. Journal technique (log)

Le fichier `penetrometre.log` enregistre les erreurs techniques et les
actions clés (ouverture/fermeture de fichiers, exports). Il ne contient
pas de contenu de mission ni de données personnelles, mais peut inclure
des chemins de fichiers locaux. Ce fichier reste sur votre poste et
n'est jamais transmis.

---

## 7. Droits de l'utilisateur

Conformément au RGPD (si applicable), vous pouvez à tout moment :

- **Consulter** les données stockées en ouvrant le dossier
  `~/.penetrometre/` (Aide → Ouvrir le fichier de log pour y accéder).
- **Supprimer** l'ensemble des données en supprimant ce dossier et vos
  fichiers de mission.
- **Exporter** vos données via les fonctions d'export intégrées
  (PDF, XLSX, CSV).

---

## 8. Contact

Pour toute question relative à la confidentialité :

**Edwin Colinet**  
e.colinet@silvavenir.fr
