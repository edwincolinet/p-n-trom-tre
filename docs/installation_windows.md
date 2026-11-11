# Pénétromètre Silvavenir — Installation sur Windows 11

Logiciel interne du cabinet. Version 3.7.0.

## 1. Installer

1. Récupérez `Penetrometre-X.Y.Z-Setup.exe` dans le dossier partagé des
   installeurs du cabinet (indiqué par Edwin Colinet).
2. Double-cliquez dessus. **Aucun droit administrateur n'est nécessaire** :
   l'application s'installe pour votre session Windows seulement
   (`%LOCALAPPDATA%\Penetrometre`).
3. Cochez « Créer une icône sur le Bureau » si vous le souhaitez, puis
   *Installer* et *Terminer*.

### Si Windows affiche « Windows a protégé votre PC »

L'installeur n'est pas (encore) signé numériquement, ce qui déclenche
l'écran bleu SmartScreen. Cliquez sur **Informations complémentaires**, puis
sur **Exécuter quand même**. Ce message n'apparaît qu'une fois par installeur.

## 2. Premier lancement

Au premier démarrage, le nom du cabinet (**Silvavenir**) et son logo sont
déjà renseignés pour les exports. Vous pouvez les modifier à tout moment
(**Affichage → Logo et nom du cabinet…**). Les autres réglages (langue,
taille du texte, unité des angles grades/degrés, barème) sont aussi dans le
menu **Affichage**.

Pour découvrir le logiciel : **Aide → Guide de démarrage**, ou ouvrez la
mission d'exemple (**Fichier → Ouvrir la mission d'exemple…**).

## 3. Où sont mes données ?

| Quoi | Où |
|---|---|
| Vos missions | là où **vous** les enregistrez (fichiers `.json`) |
| Réglages, logo, barème du poste | `%USERPROFILE%\.penetrometre\` |
| Sauvegardes automatiques (12 dernières par mission) | `%USERPROFILE%\.penetrometre\backups\` |
| Reprise après plantage | `%USERPROFILE%\.penetrometre\recovery\` |
| Journal (pour le support) | `%USERPROFILE%\.penetrometre\penetrometre.log` |

Désinstaller l'application **ne supprime pas** ces données ni vos missions.

## 4. Travailler à plusieurs sur une mission

- Une mission = un fichier. **Une seule personne à la fois** devrait
  l'éditer.
- Si le fichier a été modifié ailleurs depuis que vous l'avez ouvert, le
  logiciel **le détecte à l'enregistrement** et vous propose : écraser (la
  version de l'autre est conservée dans les sauvegardes), enregistrer sous un
  autre nom, ou annuler. Il ne fusionne pas les deux versions.
- Pour les missions partagées, privilégiez le dossier réseau du cabinet plutôt
  qu'une copie sur le Bureau ou sur une clé USB.

## 5. Mises à jour

À chaque démarrage, le logiciel cherche un installeur plus récent dans le
dossier partagé (**Aide → Dossier des mises à jour…** pour le choisir si
besoin). Une bannière « Nouvelle version disponible » ouvre ce dossier :
lancez le nouvel installeur, il remplace l'ancienne version et conserve vos
réglages. **Enregistrez vos missions avant** de mettre à jour.

## 6. En cas de problème

- **Aide → Contacter le support…** prépare un e-mail avec la version.
- **Aide → Ouvrir le fichier de log** ouvre le journal : joignez-le à votre
  message (il ne contient ni e-mail ni chemin complet de mission).
- Après un plantage, relancez l'application : elle propose de **récupérer** le
  travail non enregistré.

## 7. Désinstaller

*Paramètres → Applications → Applications installées → Pénétromètre
Silvavenir → Désinstaller.*
