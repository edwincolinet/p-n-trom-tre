---
name: run-penetrometre
description: >
  Lancer et piloter l'app desktop Pénétromètre Silvavenir (Tkinter) pour vérifier
  un export réel — fiche d'expertise PDF (arbre ou mission), PNG, XLSX/CSV.
  Utiliser pour « lancer l'app », « vérifier l'export PDF », « screenshot de la
  fiche », « tester l'export » sans cliquer manuellement. Pilote = driver.py
  (charge une mission, déclenche l'action d'export, vérifie le PDF).
---

# Lancer / piloter Pénétromètre Silvavenir

Pénétromètre Silvavenir est une app **Tkinter** (mono-fenêtre, lancée par `python3 penetrometre.py`).
On ne l'automatise pas au clic : on la pilote via
`.claude/skills/run-penetrometre/driver.py`, qui instancie la **vraie `App`**, charge
une mission comme le ferait *Fichier → Ouvrir* (`_open_path`), puis déclenche
l'**action d'export réelle** (`action_export_pdf_arbre` / `action_export_pdf_mission`)
— seule la boîte « Enregistrer sous » (`filedialog.asksaveasfilename`) et les
modals de confirmation sont neutralisés. Tout le reste est le code de production.

> **Chemins ci-dessous : relatifs à la racine du repo.** L'app est Tkinter →
> il faut un `DISPLAY`. Sur cette machine c'est le bureau réel `:0` (une fenêtre
> apparaît une fraction de seconde). Sur une machine sans écran, préfixer par
> `xvfb-run -a` (paquet `xvfb`).

## Prérequis

L'export PDF vectoriel a besoin de **fpdf2** dans l'interpréteur de lancement.
Le `python3` système est « externally-managed » (PEP 668) → installer en
**espace utilisateur** (aucun paquet système touché, réversible) :

```bash
python3 -m pip install --user --break-system-packages "fpdf2>=2.8,<3"
```

Vérification du PDF produit (texte + rendu) via **poppler** (déjà présent ici) :
`pdftotext`, `pdftoppm`. Sinon : `apt-get install -y poppler-utils`.

Pillow est déjà disponible pour le `python3` système (`python3-pil`).

## Run (chemin agent) — piloter un export

**Fiche d'un arbre** (choisi par n° ; défaut = 1er de la mission) :

```bash
DISPLAY=:0 PYTHONPATH=$PWD python3 .claude/skills/run-penetrometre/driver.py \
  --arbre 3 --out /tmp/penetrometre_a3.pdf
```

**Fiche mission complète** (tous les arbres, PDF multi-pages) :

```bash
DISPLAY=:0 PYTHONPATH=$PWD python3 .claude/skills/run-penetrometre/driver.py \
  --mission-pdf --out /tmp/penetrometre_mission.pdf
```

Options : `--mission <fichier.json>` (défaut `exemples/mission_demo.json`),
`--no-sondages` (masque les pastilles du dessin), `--no-render`.

Le driver imprime des lignes `KEY=VALUE` et se termine en code ≠ 0 si l'export
échoue. Sortie attendue (fiche arbre) :

```
MISSION=Square des Tilleuls — exemple
ARBRES=5
ARBRE=Arbre n°3 — Tilleul à grandes feuilles
PDF_OK=True
PDF_BYTES=57252
PDF_MAGIC_OK=True
PDF_TEXT_LINES=127          # > 0 ⟹ texte sélectionnable (rendu VECTORIEL)
PDF_PNG=/tmp/penetrometre_a3_p-1.png
RESULT=OK
```

**Regarde le `PDF_PNG`** (rendu de la 1re page) — un cadre blanc = échec de
rendu. `PDF_TEXT_LINES=0` = le PDF n'est plus vectoriel (régression).

## Direct invocation — rendu sans GUI

Pour un changement qui ne touche que le **rendu** (`fiche_pdf.py`,
`pil_render.py`), pas besoin de lancer Tk (ni de `DISPLAY`) :

```bash
PYTHONPATH=$PWD python3 - <<'PY'
from persistence import load_chantier
from fiche_pdf import _new_pdf, render_fiche_arbre
c = load_chantier("exemples/mission_demo.json")
a = next(x for x in c.arbres if x.numero_arbre == "3")
pdf = _new_pdf(); render_fiche_arbre(pdf, a, c)
open("/tmp/direct.pdf", "wb").write(bytes(pdf.output()))
d = open("/tmp/direct.pdf", "rb").read()
print("bytes", len(d), "%PDF", d[:4] == b"%PDF", "pages", len(pdf.pages))
PY
```

## Run (chemin humain)

```bash
python3 penetrometre.py     # ouvre la fenêtre ; Ctrl-C ou fermer pour quitter
```

Inutile en headless (fenêtre interactive). L'export se fait via l'onglet
Diagnostic / le menu Fichier / `Ctrl+E`.

## Test

```bash
python3 -m pytest tests -q            # suite complète (~1m40)
python3 -m pytest tests/test_export.py -k FichePdf -q   # ciblé fiche PDF
```

## Gotchas

- **`filedialog` bloque.** Toute action d'export ouvre une vraie boîte
  « Enregistrer sous ». Le driver la remplace par un chemin fixe. Ne PAS
  déclencher un export sans ce monkeypatch → l'app fige, en attente d'un clic.
- **L'export MISSION ouvre un `askyesno` modal** (`_check_completeness`) dès que
  la mission a un arbre incomplet (la démo en a un : Orme n°4, 2 sondages). Le
  driver y répond « oui ». Sans ça → gel silencieux (juste l'en-tête s'affiche,
  aucun PDF). C'est ce qui bloquait la 1re tentative mission.
- **fpdf2 doit être dans l'interpréteur de LANCEMENT.** L'app est faite pour un
  double-clic (⇒ `python3` système). fpdf2 dans un venv non utilisé pour lancer
  ne sert à rien. Depuis l'adoption fpdf2, l'import est **paresseux**
  (`fiche_pdf.HAS_FPDF`) : l'app démarre même sans fpdf2, mais l'export affiche
  « fpdf2 requis » (`app_exports._need_fpdf`). `PDF_TEXT_LINES` vérifie qu'on est
  bien en vectoriel.
- **`PYTHONPATH=$PWD` obligatoire** : le driver vit dans `.claude/skills/…`, donc
  `sys.path[0]` = ce dossier, pas la racine → sans `PYTHONPATH` les imports
  projet (`penetrometre`, `app_exports`) échouent.
- **Pas de xvfb ici** → on passe par `DISPLAY=:0`. Le check de licence est sauté
  hors bundle PyInstaller (`license.is_bundled()` faux en dev) → aucun blocage.

## Troubleshooting

| Symptôme | Cause / fix |
|---|---|
| `ModuleNotFoundError: penetrometre` | `PYTHONPATH=$PWD` manquant devant la commande. |
| `ERREUR : aucun DISPLAY` | Ajouter `DISPLAY=:0` (bureau) ou `xvfb-run -a` (headless). |
| Le driver ne rend plus la main (mode `--mission-pdf`) | Un modal non neutralisé s'est ouvert ; vérifier les stubs `askyesno`/`showinfo` dans `driver.py`. |
| `SHOWERROR=(...)` + code 4 | L'export a levé une exception (souvent fpdf2 absent) ; installer fpdf2 (cf. Prérequis). |
| `PDF_TEXT_LINES=0` | Le rendu n'est plus vectoriel (régression fiche_pdf) — le texte devrait être extractible. |
