"""La sortie en français de g1-diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic.

Une ligne par vérification, rangées par groupe (Câble et réseau, Robot, Jetson), avec son état, ce qui a été vu et,
si ce n'est pas OK, ce qu'il faut faire ; puis les vérifications sans objet ici et la phrase la plus importante.
Couleurs seulement dans un vrai terminal (et jamais avec NO_COLOR).
"""
import os
import textwrap

from atelier.lieu.diagnostic import GROUPES_DIAGNOSTIC, VERIFICATIONS

LARGEUR = 100
ETIQUETTES = {"ok": "OK", "attention": "ATTENTION", "probleme": "PROBLÈME", "inconnu": "INCONNU"}
COULEURS = {"ok": "32", "attention": "33", "probleme": "31", "inconnu": "37"}
MODES = {"reel": "le vrai robot", "repetition": "la répétition (faux G1)"}


def couleurs_permises(flux):
    """Vrai si le flux est un terminal et que NO_COLOR n'est pas posée."""
    return bool(getattr(flux, "isatty", lambda: False)()) and "NO_COLOR" not in os.environ


def _peindre(texte, etat, couleur):
    return f"\033[1;{COULEURS[etat]}m{texte}\033[0m" if couleur else texte


def _heure(date):
    return date[11:19] if isinstance(date, str) and len(date) >= 19 else "?"


def texte_diagnostic(d, couleur=False, largeur=LARGEUR):
    """Le diagnostic (schéma diagnostic) en texte, pour un terminal."""
    lignes = [f"Vérifier le robot : {MODES.get(d.get('mode'), d.get('mode'))} ({_heure(d.get('date'))}, "
              f"{str(round(d.get('duree_s', 0), 1)).replace('.', ',')} s)"
              + (" ; vérifications système simulées" if d.get("faux") else "")]
    marge = " " * 13
    for groupe, titre in GROUPES_DIAGNOSTIC.items():
        verifs = [v for v in d.get("verifications", []) if v.get("groupe") == groupe]
        if not verifs:
            continue
        lignes.append("")
        lignes.append(titre)
        for v in verifs:
            etiquette = _peindre(f"{ETIQUETTES[v['etat']]:<10}", v["etat"], couleur)
            corps = textwrap.wrap(f"{v['titre']} : {v['detail']}", width=largeur - len(marge) - 2) or [""]
            lignes.append(f"  {etiquette} {corps[0]}")
            lignes.extend(f"{marge}{x}" for x in corps[1:])
            if v.get("conseil") and v["etat"] != "ok":
                for i, x in enumerate(textwrap.wrap(v["conseil"], width=largeur - len(marge) - 4)):
                    lignes.append(f"{marge}{'→ ' if i == 0 else '  '}{x}")
            if v.get("action"):
                # la commande seule sur sa ligne : on peut la copier telle quelle dans un terminal
                lignes.append(f"{marge}  Ici : g1-diagnostic --action {v['action']}")
    ignorees = d.get("ignorees") or []
    if ignorees:
        lignes.append("")
        par_raison = {}
        for x in ignorees:
            titre = VERIFICATIONS.get(x["id"], ("", x["id"]))[1].replace("« ", "«\u00a0").replace(" »", "\u00a0»")
            par_raison.setdefault(x["raison"], []).append(titre)
        for raison, titres in par_raison.items():
            for i, morceau in enumerate(textwrap.wrap(f"Pas vérifiés ({raison}) : {', '.join(titres)}.",
                                                      width=largeur - 2)):
                lignes.append(("  " if i else "") + morceau)
    lignes.append("")
    resume = d.get("resume") or {}
    etats = ("ok", "attention", "probleme", "inconnu")
    compte = ", ".join(f"{resume.get(e, 0)} {ETIQUETTES[e].lower()}" for e in etats if resume.get(e))
    lignes.append(_peindre(f"{ETIQUETTES[d['etat']]} : ", d["etat"], couleur) + (compte or "aucune vérification"))
    lignes.extend(textwrap.wrap(d.get("message", ""), width=largeur))
    return "\n".join(lignes)


def texte_action(r):
    """Le résultat d'une action, en une ou deux lignes."""
    debut = "Fait" if r.get("ok") else "Pas fait"
    return f"{debut} : {r.get('message', '')}"
