# Chantier fpdf2 — fiche PDF vectorielle

> **Statut** : planifié, approche **validée par Edwin**, pas encore implémenté.
> **Branche de travail** : `adopt-fpdf2` (créée, ne contient que ce plan).
> Reprendre avec `git checkout adopt-fpdf2`.

## Objectif

Réécrire la **fiche d'expertise PDF** (`fiche_pdf.py`) en **PDF vectoriel via
fpdf2**, à la place de la rasterisation Pillow actuelle (page A4 = image PNG
collée dans un PDF). Gains : **texte sélectionnable/cherchable**, **net à
l'impression et au zoom**, **fichier bien plus léger** (~5-10×). C'est le
livrable principal du logiciel → l'endroit où ça compte le plus.

`fpdf2` est **déjà déclarée** en dépendance runtime (`requirements.txt`,
`fpdf2>=2.8,<3`) mais **inutilisée** à ce jour — ce chantier est son adoption.

## Décision d'architecture validée : approche HYBRIDE + doc FPDF partagé

1. **Hybride** : tout le **texte + le tableau PRBS + la mise en page** passent
   en **vectoriel fpdf2**. Le **dessin de section** (rose des vents) **reste
   rendu par Pillow** (`pil_render.render_arbre_to_pil_image`) et est **collé
   comme image** dans la page via `pdf.image(pil_image, x, y, w=…)`.
   - Vérifié : `fpdf2.FPDF.image()` accepte directement une `PIL.Image`.
   - Réécrire le dessin de section en vectoriel serait énorme et sans gain
     réel → hors périmètre. Idem la comparaison inter-missions
     (`comparaison_render.py`) reste **raster** (hors périmètre).

2. **Changement d'API** — passer d'un `List[PILImage]` retourné à un
   **document FPDF partagé** dans lequel on **ajoute des pages** :
   ```python
   # AVANT : render_fiche_arbre_to_pdf_page(arbre, chantier, …) -> List[PILImage]
   # APRÈS :
   def render_fiche_arbre(pdf: FPDF, arbre, chantier, *,
                          show_sondages=True, logo_path=None,
                          cabinet_name="", mission_file=None) -> None:
       """Ajoute la/les page(s) de l'arbre au document `pdf`."""
   ```
   - **1 arbre** : `pdf = _new_pdf(); render_fiche_arbre(pdf, a, …); pdf.output(path)`
   - **Mission** : `pdf = _new_pdf(); for a: render_fiche_arbre(pdf, a, …); pdf.output(path)`
     → concaténation **native** (fini le `append_images` de Pillow).
   - Prévoir un helper `_new_pdf()` qui crée le `FPDF` (format A4 portrait,
     unité mm ou pt — voir ci-dessous) **et enregistre les polices** (§ suivant).

## Polices (piège majeur)

fpdf2 par défaut (Helvetica/Arial) est **latin-1 uniquement** → casse les
**accents français** ET les glyphes **✔/✘** de la compartimentation. Il FAUT
enregistrer les **DejaVu embarquées** (déjà dans `assets/fonts/`, utilisées par
le rendu PIL) :
```python
pdf.add_font("DejaVu", "", "assets/fonts/DejaVuSans.ttf")
pdf.add_font("DejaVu", "B", "assets/fonts/DejaVuSans-Bold.ttf")
# DejaVuSerif-Bold.ttf existe aussi (titres façon serif de l'actuel).
```
DejaVu porte accents + ✔ (U+2714) + ✘ (U+2718) + — (U+2014) + Ø + • + ● →
tout ce qu'utilise la fiche. Symboles compartimentation : **source unique**
`dialogs_shared.compart_glyph` / `compart_color` (déjà en place).

## Cartographie de `fiche_pdf.py` à réécrire (828 lignes)

| Fonction | Lignes | Rôle → action fpdf2 |
|---|---|---|
| `_fit_text` | 65 | tronque à la largeur (ellipsis) → équivalent fpdf2 (mesure via `pdf.get_string_width`) |
| `_wrap_lines` | 83 | wrap par mots (préconisation) → `pdf.multi_cell` peut remplacer, ou garder le helper avec `get_string_width` |
| `_estimate_preco_height` | 115 | réserve la hauteur préco → à réévaluer (fpdf2 gère le flux ; peut simplifier) |
| `render_fiche_arbre_to_pdf_page` | **150-558** | **cœur** : en-tête mission+logo, identité arbre, dessin collé, légende horizontale, **tableau PRBS**, diagnostic, préconisation, pied. **~400 lignes à réécrire** en cells/rects fpdf2 |
| `_resolve_photo` | 559 | résout un chemin photo (garde tel quel) |
| `_draw_mono_diagnostic` | 577 | bloc diagnostic mono → texte fpdf2 |
| `_draw_cepee_diagnostic` | 688 | bloc diagnostic cépée → texte fpdf2 |
| `_render_photos_page` | 740 | 2ᵉ page grille photos → `pdf.add_page()` + `pdf.image()` par photo |

Contenu métier à préserver **à l'identique** (ne PAS changer la donnée, juste
le rendu) :
- En-tête vert `COLOR_ACCENT`, logo cabinet à droite (fond blanc), version.
- Identité : `Arbre n°X — essence`, rayon/Ø/hauteur/port.
- Dessin de section (collé), légende horizontale (bois sain/dégradé/écorce/sondage).
- **Tableau PRBS** : colonnes N° · Direction · PRBS ajustée · t/R · Classe
  (couleur) · **Compart. (glyphe ✔/✘/— coloré, centré)** — cf. le rendu actuel
  lignes ~404-418 déjà migré vers `compart_glyph`/`compart_color`.
- Diagnostic (t/R moyen + min, répartition, classe globale ; mono ET cépée).
- Préconisation (urgence colorée `_URGENCE_COLOR`, échéance, texte libre).
- `show_sondages` gouverne les pastilles **du dessin** (le tableau reste).
- Page photos si `arbre.photos`.
- Pied : « Pénétromètre • Édité le … » + `cabinet_name`.

## Appelants à mettre à jour (`app_exports.py`)

Les 3 font aujourd'hui `pages[0].save(p, "PDF", resolution=150.0,
save_all=True, append_images=pages[1:])` :
- `export_pdf_arbre` (≈ l.149-155) → `pdf=_new_pdf(); render_fiche_arbre(pdf,…); pdf.output(p)`
- `print_pdf_arbre` (≈ l.180-192) → idem vers un fichier temp
- `export_pdf_mission` (≈ l.239-246) → 1 seul `pdf`, boucle sur les arbres,
  `pdf.output(p)` (supprime `all_pages.extend(...)` / `append_images`)

Import à changer : `from fiche_pdf import render_fiche_arbre` (au lieu de
`render_fiche_arbre_to_pdf_page`).

## Tests

- **2 tests à rediriger** (ils inspectaient la PIL de la page, or l'info qu'ils
  vérifient est dans le **dessin**, resté PIL) :
  - `test_export.FichePdfSondagesTests::test_show_sondages_false_omet_les_pastilles_du_dessin`
    → tester `pil_render.render_arbre_to_pil_image(a, show_sondages=on/off)`
    (`.tobytes()` diffèrent, `.size` identiques).
  - `test_export.FichePdfCepeeLayoutTests::test_dessin_cepee_pleine_largeur`
    → tester `render_arbre_to_pil_image(build_arbre("cepee"))` (pleine largeur).
- **Ajouter un smoke PDF** : `render_fiche_arbre(pdf, a, c)` puis
  `pdf.output()` → octets non vides, commence par `%PDF`, bon nombre de pages
  (2 si photos). Éventuellement vérifier que du **texte** est présent (ex. via
  un parseur léger, ou juste la taille/heuristique) — l'important est « ça
  produit un PDF valide ».
- **Goldens** : la fiche PDF **n'est PAS golden-testée au pixel**
  (les goldens `test_render` concernent `comparaison_render`, séparé) → rien à
  régénérer côté fiche. Ne PAS toucher aux goldens.

## Étapes d'implémentation (ordre conseillé)

1. **Helper polices + `_new_pdf()`** (format A4, marges, DejaVu enregistrées).
2. **`render_fiche_arbre`** : en-tête → identité → dessin collé → légende →
   tableau PRBS → diagnostic → préconisation → pied. Réécrire par blocs, en
   réutilisant les calculs métier existants (imports diagnostic déjà là).
3. **Page photos** (`_render_photos_page` → ajoute une page au doc).
4. **`app_exports`** : les 3 appelants + l'import.
5. **Tests** : rediriger les 2 + ajouter le smoke.
6. **Validation visuelle** : générer un vrai PDF depuis `mission_demo.json`
   (Tilleul n°3), le **rendre en image** pour contrôle (pdf2image absent →
   utiliser un moyen dispo, ou au moins vérifier octets/pages + ouvrir à la
   main). Comparer la mise en page à l'actuelle.
7. **Docs** : mettre à jour `CLAUDE.md` (section fiche PDF), `README`,
   `.claude/docs/architecture.md` (fiche_pdf), et **retirer fpdf2 de la liste
   « déclarées mais inutilisées »**. Régénérer `docs/exemple_fiche_arbre.pdf` +
   `docs/apercu_fiche_pdf.png` (le PDF est maintenant vectoriel — l'aperçu PNG
   se fait via un rendu de la page).

## Pièges & notes

- **Unités** : choisir mm ou pt et s'y tenir. L'actuel raisonne en px (1240×1754
  @150 DPI). En fpdf2, A4 = 210×297 mm. Le dessin collé : calculer sa largeur en
  mm pour occuper la zone voulue (garder le ratio de l'image PIL).
- **Couleurs** : `palette` donne des hex `#RRGGBB`. fpdf2 veut des RGB (0-255) :
  `pdf.set_fill_color(r, g, b)` / `set_text_color`. Prévoir un mini-helper
  `_rgb("#2D7A3E") -> (45,122,62)`.
- **Le dessin reste PIL** : `render_arbre_to_pil_image(...)` inchangé ; on colle.
  `show_sondages` continue de gouverner CE dessin.
- **Compart. = source unique** `dialogs_shared` (✔/✘/— + couleurs), déjà en place.
- **Ne PAS toucher** `comparaison_render.py` (raster, hors périmètre).
- **fiche_pdf importe déjà** `compart_color`/`compart_glyph`,
  `diagnostic.*`, `palette.*`, `pil_render.render_arbre_to_pil_image`.
- **Compat 3.10+** : fpdf2 2.8 exige Python ≥ 3.10 (déjà le plancher).
- **Estimation d'effort** : gros (réécriture ~400 lignes + 3 appelants + tests +
  polices + page photos + validation). Prévoir plusieurs passes ; une seule PR.

## Validation de fin

- `ruff check .` clean, mypy (fiche_pdf.py est dans la liste CI), `pytest tests`
  vert.
- Un vrai PDF ouvert : texte **sélectionnable**, accents corrects, ✔/✘ visibles,
  tableau lisible, dessin net, poids réduit vs l'ancien.
