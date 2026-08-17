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
from diagnostic import genet_diagnostic
from dialogs import ask_string
from i18n import _
from model import URGENCE_NIVEAUX, Arbre

# Cf. note dans `app_recovery` : base `tk.Tk` pour mypy (self = widget),
# `object` au runtime.
if TYPE_CHECKING:
    _MixinBase = tk.Tk
else:
    _MixinBase = object

# Tags de classe de risque pour un arbre au diagnostic fiable (≥3
# sondages) : la couleur du `●` plein encode alors la classe globale
# Pénétromètre. Les couleurs hexa associées sont posées dans `App`
# (`tag_configure`, cf. penetrometre.py) — ici on ne nomme que les tags.
_CLASSE_TAG = {
    CLASSE_VERT: "etat_ok_vert",
    CLASSE_ORANGE: "etat_ok_orange",
    CLASSE_ROUGE: "etat_ok_rouge",
}

# Filtre par classe de risque de la liste d'arbres (combobox du panneau
# gauche). « Non fiable » = arbre dont le risque n'est pas publié (colonne
# Risque = « — » : 0-2 sondages ou rayon nul). Cf. `_arbre_matches_filter`.
_RISK_FILTER_ALL = "Tous"
_RISK_FILTER_UNRELIABLE = "Non fiable"
_RISK_FILTER_CHOICES = (_RISK_FILTER_ALL, CLASSE_VERT, CLASSE_ORANGE,
                        CLASSE_ROUGE, _RISK_FILTER_UNRELIABLE)

# Filtre par urgence de préconisation. « Non renseignée » = urgence == "".
_URGENCE_FILTER_ALL = "Toutes"
_URGENCE_FILTER_NONE = "Non renseignée"
_URGENCE_FILTER_CHOICES = (
    (_URGENCE_FILTER_ALL,) + tuple(URGENCE_NIVEAUX) + (_URGENCE_FILTER_NONE,)
)

# Filtre par échéance de préconisation.
_ECHEANCE_FILTER_ALL      = "Toutes échéances"
_ECHEANCE_FILTER_OVERDUE  = "Échéance dépassée"
_ECHEANCE_FILTER_30       = "Dans 30 jours"
_ECHEANCE_FILTER_90       = "Dans 90 jours"
_ECHEANCE_FILTER_NONE     = "Sans échéance"
_ECHEANCE_FILTER_CHOICES  = (
    _ECHEANCE_FILTER_ALL, _ECHEANCE_FILTER_OVERDUE,
    _ECHEANCE_FILTER_30, _ECHEANCE_FILTER_90, _ECHEANCE_FILTER_NONE,
)

# Filtre par complétude des sondages.
_COMPLET_FILTER_ALL        = "Tous"
_COMPLET_FILTER_COMPLETS   = "Complets (≥3 sondages)"
_COMPLET_FILTER_INCOMPLETS = "Incomplets"
_COMPLET_FILTER_CHOICES    = (
    _COMPLET_FILTER_ALL, _COMPLET_FILTER_COMPLETS, _COMPLET_FILTER_INCOMPLETS,
)


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
        var_risk_filter: tk.StringVar
        var_urgence_filter: tk.StringVar
        var_echeance_filter: tk.StringVar
        var_complet_filter: tk.StringVar
        lbl_etat_footer: ttk.Label
        _tree_arbres_ctx_menu: tk.Menu
        _filtre_actif_frame: ttk.Frame
        _lbl_filtre_actif: ttk.Label
        _lst_frame: ttk.Frame
        pane_id: IdentificationPane
        _etat_cache: dict[int, tuple[str, str, str]]

        def push_undo(self) -> None: ...
        def _current_arbre(self) -> Optional[Arbre]: ...
        def _load_arbre_to_ui(self) -> None: ...
        def set_status(self, text: str) -> None: ...
        def _reset_all_filters(self) -> None: ...
        def _refresh_welcome_visibility(self) -> None: ...

    # --- Liste d'arbres ---------------------------------------------

    def _arbre_matches_filter(self, a: Arbre,
                              etat: "tuple[str, str, str] | None" = None
                              ) -> bool:
        """Vrai si l'arbre concorde avec les filtres courants : recherche
        texte (sous-chaîne insensible à la casse sur n°, essence **ou
        commentaire**) **ET** filtre par classe de risque **ET** filtre par
        urgence de préconisation. Filtres vides = tout passe. Tolérant si
        appelé avant la construction.

        `etat` : le triplet `_arbre_etat(a)` s'il a déjà été calculé par
        l'appelant. `_arbre_etat` appelle `genet_diagnostic` (16
        directions × brins) ; sans ce paramètre, `_refresh_tree_arbres`
        le payait **deux fois par arbre** dès qu'un filtre de risque
        était actif — une fois pour la ligne, une fois ici. Sur une
        mission de 300 arbres, ça doublait le coût de chaque frappe dans
        le champ de recherche (~30 ms → ~60 ms).
        """
        q = getattr(self, "var_filter", None)
        if q is not None:
            needle = q.get().strip().lower()
            if needle and not (needle in a.numero_arbre.lower()
                               or needle in a.essence.lower()
                               or needle in a.commentaire.lower()):
                return False
        rf = getattr(self, "var_risk_filter", None)
        if rf is not None:
            choice = rf.get()
            if choice and choice != _RISK_FILTER_ALL:
                if etat is None:
                    # Repli sur le cache alimenté par `_refresh_tree_arbres`
                    # (même source que `_update_etat_footer`) avant de
                    # recalculer — sert la navigation clavier, qui filtre
                    # toute la mission à chaque Ctrl+PgUp/PgDown.
                    etat = getattr(self, "_etat_cache", {}).get(id(a))
                if etat is None:
                    etat = self._arbre_etat(a)
                risque = etat[1]  # « Vert/Orange/Rouge/— »
                if choice == _RISK_FILTER_UNRELIABLE:
                    if risque != "—":
                        return False
                elif risque != choice:
                    return False
        uf = getattr(self, "var_urgence_filter", None)
        if uf is not None:
            choice = uf.get()
            if choice and choice != _URGENCE_FILTER_ALL:
                if choice == _URGENCE_FILTER_NONE:
                    if a.urgence != "":
                        return False
                elif a.urgence != choice:
                    return False
        # Filtre par échéance
        ef = getattr(self, "var_echeance_filter", None)
        if ef is not None:
            choice = ef.get()
            if choice and choice != _ECHEANCE_FILTER_ALL:
                if choice == _ECHEANCE_FILTER_NONE:
                    if a.echeance:
                        return False
                else:
                    if not a.echeance:
                        return False
                    try:
                        from datetime import date as _date

                        from dialogs_shared import normaliser_date
                        norm = normaliser_date(a.echeance)
                        if norm:
                            j, m, y = norm.split("/")
                            d_ech = _date(int(y), int(m), int(j))
                            today = _date.today()
                            if choice == _ECHEANCE_FILTER_OVERDUE:
                                if d_ech >= today:
                                    return False
                            elif choice == _ECHEANCE_FILTER_30:
                                from datetime import timedelta
                                if not (today <= d_ech <= today + timedelta(days=30)):
                                    return False
                            elif choice == _ECHEANCE_FILTER_90:
                                from datetime import timedelta
                                if not (today <= d_ech <= today + timedelta(days=90)):
                                    return False
                        else:
                            return False
                    except Exception:
                        return False
        # Filtre par complétude
        cf = getattr(self, "var_complet_filter", None)
        if cf is not None:
            choice = cf.get()
            if choice and choice != _COMPLET_FILTER_ALL:
                n_sond = sum(len(b.sondages) for b in a.brins)
                complet = (a.rayon_tronc_cm > 0 and n_sond >= 3)
                if choice == _COMPLET_FILTER_COMPLETS and not complet:
                    return False
                if choice == _COMPLET_FILTER_INCOMPLETS and complet:
                    return False
        return True

    def _refresh_tree_arbres(self) -> None:
        self.tree_arbres.delete(*self.tree_arbres.get_children())
        # Vider le cache : les objets Arbre peuvent avoir été remplacés
        # (undo/redo arbre scopé) — on repart propre.
        if hasattr(self, "_etat_cache"):
            self._etat_cache.clear()
        n_rouge = n_orange = n_vert = n_afinir = 0
        for i, a in enumerate(self.chantier.arbres):
            # _arbre_etat appelle genet_diagnostic — on le fait une seule
            # fois par arbre pour alimenter à la fois la ligne du Treeview
            # ET les compteurs du footer (évite un second parcours complet
            # dans _update_etat_footer).
            glyph, risque, tag = self._arbre_etat(a)
            if hasattr(self, "_etat_cache"):
                self._etat_cache[id(a)] = (glyph, risque, tag)
            if risque == CLASSE_ROUGE:
                n_rouge += 1
            elif risque == CLASSE_ORANGE:
                n_orange += 1
            elif risque == CLASSE_VERT:
                n_vert += 1
            else:
                n_afinir += 1
            # L'état vient d'être calculé au-dessus : on le passe au
            # filtre plutôt que de le laisser le recalculer.
            if not self._arbre_matches_filter(a, (glyph, risque, tag)):
                continue
            # Affichage compact : "n°X" (l'essence est dans la 2e colonne)
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            # iid = position réelle dans chantier.arbres (cf.
            # _on_select_arbre) — préservée même quand des lignes sont
            # masquées par le filtre.
            self.tree_arbres.insert("", "end", iid=f"a{i}",
                                    text=label,
                                    values=(a.essence, glyph, risque),
                                    tags=(tag,))
        # Footer = vue macro sur TOUTE la mission (pas la sous-liste filtrée).
        self._set_etat_footer_counts(n_rouge, n_orange, n_vert, n_afinir)
        # Bandeau "filtre actif" : signale le nombre d'arbres masqués et
        # propose un bouton de réinitialisation rapide.
        if hasattr(self, "_filtre_actif_frame"):
            n_masques = len(self.chantier.arbres) - len(
                self.tree_arbres.get_children())
            if n_masques > 0:
                self._lbl_filtre_actif.configure(
                    text=_("{n} arbre(s) masqué(s) par le filtre").format(n=n_masques))
                if not self._filtre_actif_frame.winfo_ismapped():
                    self._filtre_actif_frame.pack(fill="x", pady=(0, 4),
                                                  before=self._lst_frame)
            else:
                self._filtre_actif_frame.pack_forget()
        # Re-sélectionne l'arbre courant s'il est visible dans la liste
        # filtrée (sinon on laisse la sélection vide : le panneau de droite
        # continue d'afficher l'arbre courant).
        target = f"a{self.current_idx}"
        if target in self.tree_arbres.get_children():
            self.tree_arbres.selection_set(target)
            self.tree_arbres.focus(target)
        self._refresh_welcome_visibility()

    def _set_etat_footer_counts(self, n_rouge: int, n_orange: int,
                                   n_vert: int, n_afinir: int) -> None:
        """Affiche les compteurs pré-calculés dans le footer. Séparé de
        _update_etat_footer pour que _refresh_tree_arbres puisse passer
        ses comptes sans second parcours de la liste."""
        if not hasattr(self, "lbl_etat_footer"):
            return
        n_total = len(self.chantier.arbres)
        self.lbl_etat_footer.configure(
            text=(f"{n_rouge} rouge · {n_orange} orange · {n_vert} vert "
                  + _("· {n} à finir   ({t})").format(n=n_afinir, t=n_total)))

    def _update_etat_footer(self) -> None:
        """Footer = **vue de triage macro** de la mission : répartition des
        arbres par classe de risque (fiables) + nombre encore « à finir »
        (rayon/sondages incomplets → diagnostic non fiable). Répond au
        « puis-je quitter le site ? » sans ouvrir l'export de synthèse.
        Recalculé sur toute la mission (jamais la sous-liste filtrée) à
        chaque rafraîchissement de l'état de l'arbre courant."""
        n_rouge = n_orange = n_vert = n_afinir = 0
        cache = getattr(self, "_etat_cache", {})
        for a in self.chantier.arbres:
            key = id(a)
            if key in cache:
                risque = cache[key][1]
            else:
                glyph, risque, tag = self._arbre_etat(a)
                cache[key] = (glyph, risque, tag)
            if risque == CLASSE_ROUGE:
                n_rouge += 1
            elif risque == CLASSE_ORANGE:
                n_orange += 1
            elif risque == CLASSE_VERT:
                n_vert += 1
            else:  # « — » : incomplet (○/◐) → à finir
                n_afinir += 1
        self._set_etat_footer_counts(n_rouge, n_orange, n_vert, n_afinir)

    @staticmethod
    def _arbre_diag_fiable(a: Arbre) -> bool:
        """Diagnostic global publiable : **au moins un brin** avec rayon
        défini ET ≥3 directions sondées (fiabilité par brin — cf. décision
        cépées). Pour un genet mono-caule, c'est le critère historique sur
        le brin unique. Calcul léger (pas de snapshot) pour le footer."""
        return any(b.rayon_tronc_cm > 0 and len(b.sondages) >= 3
                   for b in a.brins)

    @staticmethod
    def _arbre_etat(a: Arbre) -> tuple[str, str, str]:
        """Renvoie `(glyphe, risque, tag)` pour les colonnes État + Risque.

        **Deux canaux distincts** (lève l'ancienne ambiguïté où la couleur
        de ligne signifiait *complétude* pour `○/◐` mais *classe de risque*
        pour `●`) :

        - **Colonne État** = la FORME du glyphe porte la **complétude**,
          lisible même en daltonisme rouge-vert (fréquent en terrain) :
            - `○` (cercle vide)  : pas de rayon OU aucun sondage
            - `◐` (demi-cercle)  : 1-2 sondages (diagnostic non fiable)
            - `●` (cercle plein) : ≥3 sondages (diagnostic fiable)
        - **Colonne Risque** = le **mot** « Vert / Orange / Rouge » dès que
          le diagnostic est fiable, `—` sinon. Lisible sans dépendre de la
          couleur (daltonisme).
        - **Couleur de la ligne** (`tag`) = **uniquement la classe de
          risque** (fiables) ; les arbres incomplets restent **neutres**
          (`etat_vide`/`etat_partiel` → gris) pour que la couleur ne
          signifie plus qu'une seule chose.

        On évite les emojis couleur (🔴🟠🟢) qui s'affichent souvent en
        monochrome dans ttk.Treeview selon la police système.

        NB : l'extrapolation géométrique de la cavité reste active dès 2
        sondages (son minimum mathématique) — découplé du seuil de
        fiabilité à 3.

        **Cépée** : l'état agrège les brins (`genet_diagnostic`) — `●`
        coloré par la **classe globale = pire brin fiable**, `◐` si des
        sondages existent mais aucun brin n'atteint 3 directions, `○` si
        aucun brin n'a de rayon ni de sondage. Mono-caule = inchangé.
        """
        has_data = any(b.rayon_tronc_cm > 0 and b.sondages for b in a.brins)
        if not has_data:
            return "○", "—", "etat_vide"
        gd = genet_diagnostic(a)
        if not gd.fiable:
            return "◐", "—", "etat_partiel"
        if gd.classe_globale is None:
            return "●", "—", "etat_ok"
        return "●", gd.classe_globale, _CLASSE_TAG.get(
            gd.classe_globale, "etat_ok")

    def _refresh_current_arbre_etat(self) -> None:
        """Met à jour la pastille d'état + le footer après une mutation
        sur l'arbre courant. N'agit que sur la ligne sélectionnée pour
        éviter de reconstruire toute la tree (préserve la sélection et
        la position de scroll)."""
        a = self._current_arbre()
        if a is None:
            return
        # Invalide l'entrée de cache de l'arbre courant et recalcule.
        if hasattr(self, "_etat_cache"):
            self._etat_cache.pop(id(a), None)
        sel = self.tree_arbres.selection()
        if sel:
            label = f"n° {a.numero_arbre}" if a.numero_arbre else "(sans n°)"
            glyph, risque, tag = self._arbre_etat(a)
            if hasattr(self, "_etat_cache"):
                self._etat_cache[id(a)] = (glyph, risque, tag)
            self.tree_arbres.item(sel[0], text=label,
                                  values=(a.essence, glyph, risque),
                                  tags=(tag,))
        self._update_etat_footer()

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
        """Vide les filtres de la liste (texte, risque ET urgence) s'ils sont
        actifs — pour qu'un arbre nouvellement créé (toujours « Non
        fiable » au départ) reste visible. No-op si déjà vides (pas de
        refresh parasite)."""
        if (getattr(self, "var_filter", None) is not None
                and self.var_filter.get()):
            self.var_filter.set("")
        if (getattr(self, "var_risk_filter", None) is not None
                and self.var_risk_filter.get() != _RISK_FILTER_ALL):
            self.var_risk_filter.set(_RISK_FILTER_ALL)
        if (getattr(self, "var_urgence_filter", None) is not None
                and self.var_urgence_filter.get() != _URGENCE_FILTER_ALL):
            self.var_urgence_filter.set(_URGENCE_FILTER_ALL)
        if getattr(self, "var_echeance_filter", None) is not None:
            self.var_echeance_filter.set(_ECHEANCE_FILTER_ALL)
        if getattr(self, "var_complet_filter", None) is not None:
            self.var_complet_filter.set(_COMPLET_FILTER_ALL)

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
        # Protocole commun à un alignement : on reprend l'épaisseur
        # d'écorce. La géométrie mesurée (rayon, diamètre, hauteur de
        # l'arbre) reste à défaut — à re-mesurer pour chaque individu —,
        # tout comme les sondages/dégradations/contreforts.
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

    def action_next_a_finir(self) -> None:
        """Saute au prochain arbre « à finir » (diagnostic non fiable :
        rayon manquant ou < 3 sondages), en **bouclant** depuis l'arbre
        courant — outil de triage de fin de mission, pendant du compteur
        « N à finir » du footer. Ignore les filtres (et les **vide** si
        besoin pour rendre la cible visible)."""
        n = len(self.chantier.arbres)
        if n == 0:
            return
        # Parcours cyclique à partir de l'arbre SUIVANT le courant (pour
        # avancer même si le courant est lui-même à finir).
        ordre = ((self.current_idx + 1 + k) % n for k in range(n))
        cible = next((i for i in ordre
                      if not self._arbre_diag_fiable(self.chantier.arbres[i])),
                     None)
        if cible is None:
            self.set_status("Tous les arbres ont un diagnostic fiable.")
            return
        self.current_idx = cible
        self._clear_filter_if_set()      # cible visible quoi qu'il arrive
        self.tree_arbres.focus_set()
        self._refresh_tree_arbres()       # re-sélectionne a{current_idx}
        iid = f"a{cible}"
        if iid in self.tree_arbres.get_children():
            self.tree_arbres.see(iid)
        self._load_arbre_to_ui()
        reste = sum(1 for a in self.chantier.arbres
                    if not self._arbre_diag_fiable(a))
        num = self.chantier.arbres[cible].numero_arbre or "(sans n°)"
        self.set_status(_("Arbre n° {num} — {n} arbre(s) encore à finir.").format(num=num, n=reste))

    def action_dup_arbre(self) -> None:
        a = self._current_arbre()
        if not a:
            return
        self.push_undo()
        new = copy.deepcopy(a)
        new.numero_arbre = self._next_arbre_numero()
        self.chantier.arbres.insert(self.current_idx + 1, new)
        self.current_idx += 1
        self._clear_filter_if_set()
        self._refresh_tree_arbres()
        self._load_arbre_to_ui()

    def action_del_arbre(self) -> None:
        if len(self.chantier.arbres) <= 1:
            messagebox.showinfo(_("Information"),
                                "La mission doit contenir au moins un arbre.")
            return
        a = self._current_arbre()
        if a is None:
            return
        if not messagebox.askyesno(
                _("Supprimer"),
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
                    _("Numéro invalide"),
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
                _("Numéro déjà utilisé"),
                f"Un autre arbre porte déjà le n° « {new} ».\n\n"
                "Continuer quand même ?")
            if not confirmer:
                return
        self.push_undo()
        a.numero_arbre = new
        self.pane_id.load_from_arbre()
        self._refresh_tree_arbres()
