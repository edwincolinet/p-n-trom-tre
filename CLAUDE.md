# Pénétromètre — Projet Silvavenir

Application desktop d'expertise arboricole (mesure de cavités dans les
troncs au pénétromètre). Utilisé en interne par le cabinet Silvavenir.

## Stack

- **Python 3.9+** (3.12 recommandé), **Tkinter** (UI stdlib), **Pillow** (PNG/PDF)
- Aucun framework, aucun build system — lancement par double-clic.
- Dépendance optionnelle : openpyxl (export XLSX).

## Structure

```text
penetrometre.py        ← App Tk + main (~580 l.)
section_canvas.py      ← SectionCanvas (rendu Tk section, ~430 l.)
pane_identification.py ← onglet Identification
pane_sondages.py       ← onglet Sondages
pane_degradations.py   ← onglet Dégradations externes
pane_contreforts.py    ← onglet Contreforts
pane_diagnostic.py     ← onglet Diagnostic (exports + résumé)
app_exports.py         ← actions d'export (adaptateur Tk)
app_menu.py            ← barre de menu Tk
app_style.py           ← thème ttk
dialogs.py             ← dialogues Tk (Sondage, Dégradation, Contrefort)
model.py               ← dataclasses + mutateurs de cohérence
diagnostic.py          ← fonctions pures de diagnostic
persistence.py         ← I/O JSON (save/load + migration)
geometry.py            ← briques géométriques pures (spline, polaire)
bareme.py              ← barème métier (classer_prbs, ports)
pil_render.py          ← rendu PNG de la section transversale
fiche_pdf.py           ← layout fiche expertise PDF (page A4)
palette.py             ← couleurs partagées Tk ↔ PIL
export.py              ← exports XLSX/HTML tableau PRBS
tests/                 ← 146 tests (golden PIL + golden Tk)
```

**Graphe de dépendances** (chaque module importe uniquement vers le bas) :

```text
geometry.py + bareme.py   (stdlib)
   ↑
model.py + palette.py
   ↑
diagnostic.py
   ↑
export.py + pil_render.py + persistence.py + dialogs.py
   ↑
fiche_pdf.py
   ↑
section_canvas.py + pane_*.py + app_exports.py + app_menu.py + app_style.py
   ↑
penetrometre.py  (Tk + main)
```

## Conventions métier

- **Grades** : 0 à 375 par pas de 25 (16 directions). 0 = Nord, sens horaire.
  Afficher `100 gr` (pas de symbole °).
- **PRBS** = Paroi Résiduelle de Bois Sain (mesure physique invariante).
  Quand le rayon change, la PRBS reste, `bois_altéré` s'ajuste.
- **t/R** = PRBS / Rayon (0–1). **Classe globale** = barème sur t/R **moyen** 16 dir.
- **Diagnostic non fiable si < 2 sondages** → exports masquent t/R moyen + classe.
- **Dégradations externes** consomment du bois sain : `PRBS_ajustée = sain − profondeur_deg`.
- **Pastille sondage = PRBS ajustée** (jamais brute). `ratio_tR_brut` = CSV uniquement.
- **Contreforts** = cloche cosinus², fusion si adjacents (`contrefort_zones`).
- **Écorce** = purement visuel (n'intervient pas dans diagnostic). R_ext = R + ep.
- **COLOR_BARK ≠ COLOR_ROT** : ne jamais unifier (contraste dégradation/écorce).

## Conventions de code

- Pas de dépendance sans bonne raison. Compat Python 3.9+.
- Tout en français (UI + docstrings).
- Pas de `print` — logger applicatif (`~/.penetrometre/penetrometre.log`).
- Exports : `log.exception(...)` avant `messagebox.showerror`.
- Compat fichier bidirectionnelle : ajout champ = OK (default) ; renommage/suppression = migration explicite dans `persistence.chantier_from_dict`.

## Commandes utiles

```bash
python penetrometre.py                      # Lancer l'app
python -m unittest discover tests           # 146 tests
ruff check .                                # Lint
python -m mypy bareme.py geometry.py palette.py model.py diagnostic.py \
  persistence.py export.py pil_render.py fiche_pdf.py app_exports.py app_menu.py \
  pane_identification.py pane_sondages.py pane_degradations.py \
  pane_contreforts.py pane_diagnostic.py dialogs.py section_canvas.py
```

Golden-tests :
- PIL : `python -m tests.test_render --update`
- Tk : `xvfb-run -a python -m tests.test_section_canvas --update`

## Quand tu modifies l'app

1. **Repérer le bon module** :
   - Barème métier → `bareme.py`
   - Géométrie pure → `geometry.py`
   - Modèle / mutateurs → `model.py` ; migration JSON → `persistence.py`
   - Diagnostic (calculs purs) → `diagnostic.py`
   - Rendu PNG section → `pil_render.py` ; layout PDF A4 → `fiche_pdf.py`
   - Couleurs → `palette.py` ; exports tableau → `export.py`
   - Dialogues Tk → `dialogs.py` ; onglet UI → `pane_*.py`
   - Actions export → `app_exports.py` ; rendu Tk section → `section_canvas.py`
   - Orchestration App → `penetrometre.py`
2. **Géométrie partagée** : modifier `geometry.py` une fois, les deux renderers héritent. Pour le visuel spécifique (traits, polices, écorce) → modifier Tk **et** PIL.
3. **Modèle** : ajout de champ = OK. Renommage/suppression → migration dans `persistence.py`.
4. **Tests** : lancer la suite avant tout commit touchant modèle/géométrie/exports.
5. **Valider** : lancer l'app + sauvegarder/recharger un `.json`.

Pour les détails d'architecture, de rendu et les pièges, voir :
- `.claude/docs/architecture.md` — description détaillée de chaque module
- `.claude/docs/rendu-et-pieges.md` — pendants Tk↔PIL, pièges, ordre des couches
