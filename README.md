# Pénétromètre — Application d'expertise arboricole

Application desktop Python pour le cabinet **Silvavenir**, dédiée au dessin
et à l'analyse de section transversale des troncs d'arbres sondés au
pénétromètre (Résistographe™ ou tout autre appareil équivalent).

## Aperçu

L'application reproduit la logique d'un classeur Excel d'expertise et
permet, pour chaque arbre d'une mission, de :

- saisir les caractéristiques (essence, rayon, port, longueur de mèche…) ;
- enregistrer des sondages au pénétromètre dans 16 directions
  (de 0 à 375 grades, par pas de 25 gr) ;
- documenter les dégradations externes visibles (arcs sur l'écorce) ;
- visualiser en temps réel la section transversale du tronc avec
  cernes de croissance, cavité d'altération et flèches de sondage ;
- obtenir un diagnostic complet avec PRBS, ratio t/R, classification
  Vert / Orange / Rouge ;
- exporter une fiche d'expertise PDF par arbre, un PNG du dessin ou un CSV
  de toute la mission.

## Installation

```bash
# Prérequis : Python 3.9 ou plus récent (Python 3.12 recommandé)
pip install Pillow
```

Tkinter doit être disponible. C'est le cas par défaut sur Windows et macOS.
Sur Linux : `sudo apt install python3-tk`.

## Lancement

```bash
python resistographe.py
```

Sur Windows, tu peux double-cliquer sur `Lancer_Penetrometre.bat`.

## Fichiers à conserver ensemble

```
mon-dossier/
├── resistographe.py            ← le programme
├── silvavenir_logo.jpg         ← le logo (header app + fiche PDF)
└── Lancer_Penetrometre.bat     ← double-clic Windows (optionnel)
```

Les missions sont enregistrées au format JSON.

## Fonctionnalités

### Mission multi-arbres

Une **mission** regroupe plusieurs arbres dans un seul fichier `.json`.
Liste à gauche, ajout / duplication / suppression d'arbres en un clic.

### Identification d'un arbre

- N° d'arbre, essence
- Diamètre sous écorce ↔ rayon (lien automatique : Ø ÷ 2 = rayon)
- Hauteur du sondage, hauteur de l'arbre
- Longueur de mèche du pénétromètre (limite la profondeur des flèches)
- Port de l'arbre : libre / semi-libre / architecturé / traumatique

### Sondages

Chaque sondage est associé à une direction (16 grades disponibles).
La PRBS (bois sain) et le bois altéré sont liés par le rayon
(`sain + altéré = rayon`) avec calcul automatique. La compartimentation
peut être renseignée (active / absente / -).

**Robustesse** : si le rayon est corrigé après saisie de sondages, la PRBS
(mesure physique du pénétromètre) est conservée et le bois altéré est
recalculé automatiquement (`altéré = rayon − sain`).

### Extrapolation

Pour les directions non sondées, le bois altéré est estimé par
**moyenne pondérée linéaire** entre les deux sondages voisins
(à partir de 2 sondages minimum).

### Dégradations externes

Une dégradation externe est un arc continu sur l'écorce, défini par :
- un grade de début et un grade de fin (sens horaire) ;
- une profondeur radiale en cm depuis l'écorce.

Trois modes de saisie liés automatiquement : grade de fin, largeur en
grades ou largeur en cm sur l'écorce. Les dégradations externes sont
**intégrées au calcul PRBS** : elles soustraient leur profondeur de la
PRBS de la direction concernée.

### Diagnostic

- **PRBS ajustée** par sondage (= bois sain mesuré – dégradation externe
  qui couvre la direction)
- **Ratio t/R** = PRBS / Rayon, et classification Vert / Orange / Rouge
  selon le port (barème Silvavenir)
- **Répartition** sur les 16 directions du pourtour (extrapolées)
- **Classe globale** = barème Silvavenir appliqué au **t/R moyen**
  sur les 16 directions

### Visualisation

- Bois sain en beige doré, dégradations en brun foncé uniforme
- Cernes de croissance en trait fin noir (effacés naturellement par
  la cavité dans la zone dégradée)
- Pastilles colorées (Vert / Orange / Rouge) à l'intérieur du tronc,
  juste sous l'écorce, indiquant la classe de chaque sondage
- Lettres cardinales (N, NE, E, SE, S, SO, O, NO) à l'extérieur
- Règle graduée sous le tronc, symétrique de −R à +R cm
- Section ronde (interpolation Catmull-Rom des points de sondage)

### Exports

- **PDF** : fiche complète A4 avec en-tête mission, logo Silvavenir,
  identité de l'arbre, dessin annoté, tableau PRBS coloré, diagnostic
  avec barre de répartition Vert / Orange / Rouge
- **PNG** : dessin haute résolution
- **CSV** : tous les sondages de la mission, séparateur `;`,
  encodage UTF-8 avec BOM (compatible Excel)

## Barème PRBS (Silvavenir)

Application du barème selon le port de l'arbre :

| Port de l'arbre | Vert | Orange | Rouge |
|---|---|---|---|
| libre / semi-libre | t/R > 30% | 15–30% | < 15% |
| architecturé / traumatique | t/R > 20% | 10–20% | < 10% |

## Format de fichier

Les missions sont enregistrées en **JSON lisible** (`.json`). Les fichiers
des versions précédentes sont migrés automatiquement à l'ouverture.

Note technique : la classe Python interne s'appelle toujours `Chantier`
pour rester compatible avec les fichiers déjà enregistrés. Seuls les
libellés affichés à l'utilisateur ont été changés en « Mission ».

## Crédits

- Algorithme d'interpolation : Catmull-Rom spline fermée (Catmull & Rom, 1974)
- Convention PRBS : méthode VTA de Mattheck & Breloer (1994)
- Barème de classification : convention Silvavenir
- Logo : Silvavenir, Foresterie urbaine
