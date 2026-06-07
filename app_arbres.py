"""
Gestion de la liste d'arbres de la mission (mixin de `App`).

Regroupe tout ce qui touche au panneau gauche « Arbres de la mission » :
filtre de recherche, rafraîchissement de la `Treeview`, indicateurs
d'état (pastilles colorées + footer), navigation clavier, et les
actions CRUD (ajouter vierge / hériter, dupliquer, supprimer,
renommer). La sélection pilote `current_idx` ; les `iid = a{index}`
restent indexés sur la position réelle dans `chantier.arbres` (le filtre
ne fait que masquer des lignes, jamais muter le modèle).

Mixin de `App` : s'appuie sur les attributs/méthodes Tk déclarés en
`TYPE_CHECKING`, fournis par l'hôte.
"""

from __future__ import annotations

import copy
import tkinter as tk
from tkinter import messagebox, ttk
from typing import TYPE_CHECKING, Optional

from bareme import CLASSE_ORANGE, CLASSE_ROUGE, CLASSE_VERT
from diagnostic import repartition_classes
from dialogs import ask_string
from model import Arbre

# Cf. note dans `app_recovery` : base `tk.Tk` pour mypy (self = widget),
# `object` au runtime.
if TYPE_CHECKING:
    _MixinBase = tk.Tk
else:
    _MixinBase = object

# Tags de classe de risque pour un arbre au diagnostic fiable (≥3
# sondages) : la couleur du `●` plein encode alors la classe globale
# Silvavenir. Les couleurs hexa associées sont posées dans `App`
# (`tag_configure`, cf. penetrometre.py) — ici on ne nomme que les tags.
_CLASSE_TAG = {
    CLASSE_VERT: "etat_ok_vert",
    CLASSE_ORANGE: "etat_ok_orange",
    CLASSE_ROUGE: "etat_ok_rouge",
}


class ArbreListMixin(_MixinBase):
    """Méthodes du panneau « Arbres de la mission ». Mixin de `App`."""

    if TYPE_CHECKING:
        from model import Chantier
        from pane_identification import IdentificationPane

        # Fournis par App (déclarés pour le type-check du mixin).
        chantier: Chantier
        current_idx: int
        tree_arbres: ttk.Treeview
        var_filter: tk.StringVar
        lbl_etat_footer: ttk.Label
        _tree_arbres_ctx_menu: tk.Menu
        pane_id: IdentificationPane

        def push_undo(self) -> None: ...
        def _current_arbre(self) -> Optional[Arbre]: ...
        def _load_arbre_to_ui(self) -> None: ...

    # --- Liste d'arbres ---------------------------------------------

    def _arbre_matches_filter(self, a: Arbre) -> bool:
        """Vrai si l'arbre concorde avec le filtre courant (sous-chaîne,
        insensible à la casse, sur le n° OU l'essence). Filtre vide =
        tout passe. Tolérant si appelé avant la construction du champ."""
        q = getattr(self, "var_filter", None)
        if q is None:
            return True
        needle = q.get().strip().lower()
        if not needle:
            return True
        return (needle in a.numero_arbre.lower()
                or needle in a.essence.lower())

    def _refresh_tree_arbres(self) -> None:
        self.tree_arbres.delete(*self.tree_arbres.get_children())
        # Le compteur footer reste sur TOUTE la mission (vue macro), pas
        # sur la sous-liste filtrée.
        n_ok = sum(1 for a in self.chantier.arbres
                   if self._arbre_diag_fiable(a))
        for i, a in enumerate(self.chantier.arbres):
            if not self._arbre_matches_filter(a):
                continue
            # Affichage compact : "n°X" (l'essence est dans la 2e colonne)
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, tag = self._arbre_etat(a)
            # iid = position réelle dans chantier.arbres (cf.
            # _on_select_arbre) — préservée même quand des lignes sont
            # masquées par le filtre.
            self.tree_arbres.insert("", "end", iid=f"a{i}",
                                    text=label,
                                    values=(a.essence, glyph),
                                    tags=(tag,))
        self._update_etat_footer(n_ok, len(self.chantier.arbres))
        # Re-sélectionne l'arbre courant s'il est visible dans la liste
        # filtrée (sinon on laisse la sélection vide : le panneau de droite
        # continue d'afficher l'arbre courant).
        target = f"a{self.current_idx}"
        if target in self.tree_arbres.get_children():
            self.tree_arbres.selection_set(target)
            self.tree_arbres.focus(target)

    def _update_etat_footer(self, n_ok: int, n_total: int) -> None:
        """Met à jour le footer « X/N arbres complets » sous la liste."""
        if not hasattr(self, "lbl_etat_footer"):
            return
        self.lbl_etat_footer.configure(
            text=f"● {n_ok}/{n_total} arbres avec diagnostic fiable")

    @staticmethod
    def _arbre_diag_fiable(a: Arbre) -> bool:
        """Diagnostic global publiable : rayon défini ET ≥3 directions
        sondées. Seuil métier de fiabilité (cf. `_arbre_etat`), utilisé
        pour le compteur du footer."""
        return a.rayon_tronc_cm > 0 and len(a.sondages) >= 3

    @staticmethod
    def _arbre_etat(a: Arbre) -> tuple[str, str]:
        """Renvoie `(glyphe, tag)` pour la colonne État d'un arbre.

        **Glyphes distincts** : la FORME porte la complétude, donc reste
        lisible même en cas de daltonisme rouge-vert (fréquent chez les
        opérateurs de terrain) — la couleur ne fait que renforcer.
          - `○` (cercle vide)  : pas de rayon OU aucun sondage
          - `◐` (demi-cercle)  : 1-2 sondages (diagnostic non fiable)
          - `●` (cercle plein) : ≥3 sondages (diagnostic fiable)

        On évite les emojis couleur (🔴🟠🟢) qui s'affichent souvent en
        monochrome dans ttk.Treeview selon la police système.

        **Couleur du `●` plein = classe de risque.** Dès que le
        diagnostic est fiable (≥3 sondages, seuil aligné sur
        `diagnostic.DiagnosticSnapshot`), la couleur du `●` encode la
        classe globale Silvavenir (vert/orange/rouge) via les tags
        `etat_ok_<classe>` : l'opérateur repère les arbres à risque d'un
        coup d'œil dans la liste, sans ouvrir l'onglet Diagnostic. Repli
        sur `etat_ok` (vert) si la classe est indisponible.

        NB : l'extrapolation géométrique de la cavité reste active dès 2
        sondages (son minimum mathématique) — découplé du seuil de
        fiabilité à 3.
        """
        if a.rayon_tronc_cm <= 0 or not a.sondages:
            return "○", "etat_vide"
        if len(a.sondages) < 3:
            return "◐", "etat_partiel"
        diag = repartition_classes(a).diagnostic_global
        if diag is None:
            return "●", "etat_ok"
        _, classe = diag
        return "●", _CLASSE_TAG.get(classe, "etat_ok")

    def _refresh_current_arbre_etat(self) -> None:
        """Met à jour la pastille d'état + le footer après une mutation
        sur l'arbre courant. N'agit que sur la ligne sélectionnée pour
        éviter de reconstruire toute la tree (préserve la sélection et
        la position de scroll)."""
        a = self._current_arbre()
        if a is None:
            return
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, tag = self._arbre_etat(a)
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence, glyph),
                                  tags=(tag,))
        n_ok = sum(1 for x in self.chantier.arbres
                   if self._arbre_diag_fiable(x))
        self._update_etat_footer(n_ok, len(self.chantier.arbres))

    def _on_tree_arbres_right_click(self, event: "tk.Event[tk.Misc]") -> None:
        """Sélectionne la ligne sous le curseur puis affiche le menu
        contextuel. Sélectionner avant l'action garantit que les
        commandes (Renommer/Dupliquer/Supprimer) agissent sur l'arbre
        sous le clic, pas sur l'arbre précédemment sélectionné.

        NB : pas de `grab_release()` après `tk_popup()` — Tk gère le
        grab tout seul, l'appel immédiat l'annulait et empêchait le
        menu de se fermer au clic externe (cf. binding `<FocusOut>`
        posé à la construction du menu)."""
        row_id = self.tree_arbres.identify_row(event.y)
        if not row_id:
            return
        self.tree_arbres.selection_set(row_id)
        self.tree_arbres.focus(row_id)
        self._tree_arbres_ctx_menu.tk_popup(event.x_root, event.y_root)

    def _on_select_arbre(
            self, event: Optional["tk.Event[tk.Misc]"] = None) -> None:
        sel = self.tree_arbres.selection()
        if not sel:
            return
        idx = int(sel[0][1:])
        if idx == self.current_idx:
            return
        self.current_idx = idx
        self._load_arbre_to_ui()

    def _next_arbre_numero(self) -> str:
        """Prochain n° d'arbre : max numérique existant + 1, borné au
        moins au nombre d'arbres + 1 (cas de numéros non numériques)."""
        max_num = 0
        for arb in self.chantier.arbres:
            try:
                max_num = max(max_num, int(arb.numero_arbre))
            except (ValueError, TypeError):
                pass
        return str(max(max_num + 1, len(self.chantier.arbres) + 1))

    def action_add_arbre(self) -> None:
        """Ajoute un arbre vierge (tous champs par défaut)."""
        self.push_undo()
        self.chantier.arbres.append(
            Arbre(numero_arbre=self._next_arbre_numero()))
        self.current_idx = len(self.chantier.arbres) - 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _clear_filter_if_set(self) -> None:
        """Vide le filtre de la liste s'il est actif — pour qu'un arbre
        nouvellement créé reste visible même s'il ne concorde pas avec le
        filtre courant. No-op (donc pas de refresh parasite) si vide."""
        if (getattr(self, "var_filter", None) is not None
                and self.var_filter.get()):
            self.var_filter.set("")

    def action_add_arbre_inherit(self) -> None:
        """Ajoute un arbre héritant des champs d'« identité » de l'arbre
        courant (essence, port, longueur de mèche, épaisseur d'écorce,
        hauteur de sondage) mais SANS ses sondages / dégradations /
        contreforts ni sa géométrie mesurée (rayon, diamètre, hauteur de
        l'arbre restent à mesurer). Pensé pour les alignements d'arbres
        identiques (30 platanes de même essence et même port) : on ne
        re-saisit pas le protocole commun à chaque arbre."""
        cur = self._current_arbre()
        if cur is None:
            return self.action_add_arbre()
        self.push_undo()
        new = Arbre(
            numero_arbre=self._next_arbre_numero(),
            essence=cur.essence,
            port_arbre=cur.port_arbre,
            meche_cm=cur.meche_cm,
            hauteur_sondage_cm=cur.hauteur_sondage_cm,
        )
        # Épaisseur d'écorce = géométrie du brin (relais de compat vers
        # brins[0]). On ne reprend PAS le rayon/diamètre mesurés.
        new.epaisseur_ecorce_cm = cur.epaisseur_ecorce_cm
        self.chantier.arbres.append(new)
        self.current_idx = len(self.chantier.arbres) - 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def _select_arbre_relative(self, delta: int) -> None:
        """Navigation clavier entre arbres (Ctrl+PgDown / Ctrl+PgUp) :
        passe à l'arbre suivant/précédent **parmi les arbres visibles**
        (le filtre est respecté), sans boucler."""
        visible = [i for i, a in enumerate(self.chantier.arbres)
                   if self._arbre_matches_filter(a)]
        if len(visible) <= 1:
            return
        if self.current_idx in visible:
            pos = visible.index(self.current_idx)
            new_idx = visible[min(len(visible) - 1, max(0, pos + delta))]
        else:
            # Arbre courant masqué par le filtre : on entre dans la liste
            # visible par son 1er (avance) ou son dernier (recul) élément.
            new_idx = visible[0] if delta > 0 else visible[-1]
        if new_idx == self.current_idx:
            return
        # Donne le focus clavier à la liste AVANT de changer d'arbre :
        # déclenche le <FocusOut> d'une éventuelle case de grille en cours
        # d'édition (commit undo + normalisation) sur l'arbre encore
        # courant, avant de basculer.
        self.tree_arbres.focus_set()
        self.current_idx = new_idx
        target = f"a{new_idx}"
        if target in self.tree_arbres.get_children():
            self.tree_arbres.selection_set(target)
            self.tree_arbres.focus(target)
            self.tree_arbres.see(target)
        self._load_arbre_to_ui()

    def action_next_arbre(self) -> None:
        self._select_arbre_relative(1)

    def action_prev_arbre(self) -> None:
        self._select_arbre_relative(-1)

    def action_dup_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        self.push_undo()
        new = copy.deepcopy(a)
        # Nouveau numéro = numéro existant + suffixe 'bis', 'ter', etc.
        suffixes = ["", " bis", " ter", " quater"]
        base = a.numero_arbre
        for suf in suffixes[1:]:
            candidate = base + suf
            if not any(x.numero_arbre == candidate
                       for x in self.chantier.arbres):
                new.numero_arbre = candidate
                break
        else:
            new.numero_arbre = base + " (copie)"
        self.chantier.arbres.insert(self.current_idx + 1, new)
        self.current_idx += 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_del_arbre(self) -> None:
        if len(self.chantier.arbres) <= 1:
            messagebox.showinfo("Information",
                                "La mission doit contenir au moins un arbre.")
            return
        a = self._current_arbre()
        if a is None:
            return
        if not messagebox.askyesno(
                "Supprimer",
                f"Supprimer définitivement « {a.display_name} » ?"):
            return
        self.push_undo()
        del self.chantier.arbres[self.current_idx]
        self.current_idx = max(0, self.current_idx - 1)
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_rename_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        # Boucle de retry : si la saisie ne contient pas de chiffre,
        # on ré-ouvre le dialogue pré-rempli avec la valeur invalide
        # plutôt que de refermer et perdre la saisie de l'utilisateur.
        # Règle alignée sur `_revert_num_if_invalid` du pane Identification :
        # au moins un chiffre, lettres autorisées (« 12 bis », « 3 ter »).
        proposed = a.numero_arbre
        while True:
            new = ask_string(
                self, "Renuméroter l'arbre",
                "Nouveau n° d'arbre :",
                initial=proposed,
                info="Doit contenir au moins un chiffre "
                     "(ex. « 1 », « 42 », « 12 bis »).")
            if new is None:
                return
            new = new.strip()
            if not new or new == a.numero_arbre:
                return
            if not any(c.isdigit() for c in new):
                messagebox.showwarning(
                    "Numéro invalide",
                    "Le numéro d'arbre doit contenir au moins un "
                    "chiffre.\n\nExemples valides : « 1 », « 42 », "
                    "« 12 bis ».",
                    parent=self)
                proposed = new
                continue
            break
        # Avertissement non bloquant si le numéro est déjà utilisé par
        # un autre arbre de la mission. L'utilisateur peut quand même
        # confirmer (cas d'un renommage en chaîne, ou d'un doublon
        # volontaire pour un arbre jumeau identifié sur le terrain).
        already_used = any(x is not a and x.numero_arbre == new
                           for x in self.chantier.arbres)
        if already_used:
            confirmer = messagebox.askyesno(
                "Numéro déjà utilisé",
                f"Un autre arbre porte déjà le n° « {new} ».\n\n"
                "Continuer quand même ?")
            if not confirmer:
                return
        self.push_undo()
        a.numero_arbre = new
        self.pane_id.load_from_arbre()
        self._refresh_tree_arbres()
