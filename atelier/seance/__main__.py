"""g1-seance : la boîte noire des séances avec le robot (vague 6, section 13.3 du plan).

  g1-seance demarrer [--mode reel|repetition] [--lieu L] [--etage E] [--api URL]   ouvre la séance de l'Atelier
  g1-seance arreter [--api URL]           « Terminer la séance » : l'enregistrement s'arrête, le rapport s'écrit
  g1-seance etat [--json] [--api URL]     la séance ouverte et la dernière
  g1-seance enregistrer --dossier D [--atelier PID]   l'enregistreur seul, jusqu'à Ctrl+C (lancé par l'Atelier)
  g1-seance rapport DOSSIER               rapport.html, rapport.md, rapport.json et trajets.png
  g1-seance exporter DOSSIER [--sortie F.zip] [--sans-bag]   un .zip de toute la séance (à donner à Claude)
  g1-seance liste [--json]                les séances, la plus récente d'abord

DOSSIER : l'identifiant d'une séance (2026-11-12_14h03, voir « liste »), « derniere », ou son dossier.
--api : l'Atelier qui tourne (défaut http://127.0.0.1:$ATELIER_PORT, sinon 8000). Codes de sortie : 0 réussi,
1 échoué (le message dit pourquoi), 2 mauvaise utilisation.
"""
import argparse
import json
import os
import sys
import urllib.error
import urllib.request

from atelier.lieu.seance import dossier_seances
from . import manifeste as M

MESSAGE_SANS_ATELIER = ("L'Atelier ne répond pas à {api} : lancez g1-atelier (la séance s'ouvre alors seule en "
                        "Réel), ou, sans Atelier, g1-seance enregistrer --dossier DOSSIER.")


def api_par_defaut():
    port = os.environ.get("ATELIER_PORT") or "8000"
    return f"http://127.0.0.1:{port}"


def appeler(api, methode, chemin, corps=None, delai=90):
    """(code HTTP, JSON) d'une demande à l'Atelier ; (None, message) s'il ne répond pas."""
    donnees = None if corps is None else json.dumps(corps).encode("utf-8")
    demande = urllib.request.Request(api.rstrip("/") + chemin, data=donnees, method=methode,
                                     headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(demande, timeout=delai) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        texte = e.read().decode("utf-8", "replace")
        try:
            return e.code, json.loads(texte)
        except ValueError:
            return e.code, {"detail": texte}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return None, {"detail": MESSAGE_SANS_ATELIER.format(api=api), "erreur": str(e)}


def dossier_seance(texte):
    """Le dossier d'une séance : son id, « derniere », ou un chemin."""
    if texte in ("derniere", "dernière"):
        for _, dossier in M.liste_seances():
            return dossier
        raise ValueError(f"aucune séance dans {dossier_seances()}")
    return M.dossier_de(texte)


def decrire(m):
    """Une ligne en français pour une séance (manifeste ou résumé)."""
    r = M.resume(m)
    from .rapport import MODES, duree
    morceaux = [r["id"] or "?", {"ouverte": "ouverte", "fermee": "fermée", "interrompue": "interrompue"}
                .get(r["etat"], r["etat"] or "?"), MODES.get(r["mode"], r["mode"] or "?")]
    if r.get("lieu"):
        morceaux.append(f"lieu {r['lieu']}" + (f" ({r['etage']})" if r.get("etage") else ""))
    morceaux.append(f"durée {duree(r.get('duree_s'))}")
    morceaux.append(f"{r.get('actions', 0)} actions")
    morceaux.append({"pret": "rapport prêt", "en_cours": "rapport en cours", "echec": "rapport en échec"}
                    .get(r.get("rapport"), "pas de rapport"))
    return " · ".join(morceaux)


def commande_demarrer(args):
    corps = {"ouverture": "g1-seance"}
    for cle in ("mode", "lieu", "etage"):
        if getattr(args, cle):
            corps[cle] = getattr(args, cle)
    code, r = appeler(args.api, "POST", "/api/seance/demarrer", corps)
    if code != 200:
        print(f"erreur : {r.get('detail')}", file=sys.stderr)
        return 1
    m = r["seance"]
    print(f"Séance ouverte : {decrire(m)}\n  dossier : {dossier_seances() / m['id']}")
    return 0


def commande_arreter(args):
    code, r = appeler(args.api, "POST", "/api/seance/arreter", {"fermeture": "g1-seance"})
    if code != 200:
        print(f"erreur : {r.get('detail')}", file=sys.stderr)
        return 1
    m = r["seance"]
    print(f"Séance terminée : {decrire(m)}\n  le rapport s'écrit (une minute au plus) : "
          f"g1-seance rapport {m['id']} pour le refaire, g1-seance exporter {m['id']} pour le .zip")
    return 0


def commande_etat(args):
    code, r = appeler(args.api, "GET", "/api/seance")
    if code != 200:
        print(f"erreur : {r.get('detail')}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    print("Séance ouverte : " + (decrire(r["seance"]) if r.get("seance") else "aucune"))
    if r.get("derniere"):
        print("Dernière séance : " + decrire(r["derniere"]))
    return 0


def commande_enregistrer(args):
    from .enregistreur import enregistrer
    reglages = {}
    if args.taille_max_mo:
        reglages["taille_max_mo"] = args.taille_max_mo
    if args.place_min_go is not None:
        reglages["place_libre_min_go"] = args.place_min_go
    return enregistrer(args.dossier, atelier_pid=args.atelier, reglages=reglages or None)


def commande_rapport(args):
    from .rapport import faire_rapport
    dossier = dossier_seance(args.dossier)
    r = faire_rapport(dossier)
    print(f"Rapport : {dossier / 'rapport.html'}\n  {len(r['trajets'])} trajets, {len(r['anomalies'])} anomalies, "
          f"{len(r['erreurs'])} erreurs")
    return 0


def commande_exporter(args):
    from .export import exporter
    dossier = dossier_seance(args.dossier)
    chemin = exporter(dossier, args.sortie, args.sans_bag)
    print(f"Séance exportée : {chemin} ({os.path.getsize(chemin) / 1e6:.1f} Mo"
          + (", sans l'enregistrement" if args.sans_bag else "") + ")")
    return 0


def commande_liste(args):
    seances = [m for m in (M.lire_manifeste(d) for _, d in M.liste_seances()) if m]
    if args.json:
        print(json.dumps([M.resume(m) for m in seances], ensure_ascii=False, indent=1))
        return 0
    if not seances:
        print(f"Aucune séance dans {dossier_seances()}.")
        return 0
    print(f"Séances ({dossier_seances()}) :")
    for m in seances:
        print("  " + decrire(m))
    return 0


def analyseur():
    p = argparse.ArgumentParser(prog="g1-seance", description=__doc__.split("\n")[0],
                                epilog="Exemple : g1-seance rapport derniere ; g1-seance exporter derniere",
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sous = p.add_subparsers(dest="commande", metavar="COMMANDE")
    s = sous.add_parser("demarrer", help="ouvrir la séance de l'Atelier qui tourne")
    s.add_argument("--mode", choices=["reel", "repetition"])
    s.add_argument("--lieu")
    s.add_argument("--etage")
    s.add_argument("--api", default=api_par_defaut())
    s = sous.add_parser("arreter", help="terminer la séance (le rapport s'écrit tout seul)")
    s.add_argument("--api", default=api_par_defaut())
    s = sous.add_parser("etat", help="la séance ouverte et la dernière")
    s.add_argument("--json", action="store_true")
    s.add_argument("--api", default=api_par_defaut())
    s = sous.add_parser("enregistrer", help="l'enregistreur seul, jusqu'à Ctrl+C")
    s.add_argument("--dossier", required=True, help="dossier de la séance (le bag va dans DOSSIER/bag)")
    s.add_argument("--atelier", type=int, help="PID de l'Atelier : l'enregistreur s'arrête s'il disparaît")
    s.add_argument("--taille-max-mo", type=float, help="taille maximale du bag (Mo)")
    s.add_argument("--place-min-go", type=float, help="place libre gardée sur le disque (Go)")
    s = sous.add_parser("rapport", help="écrire le rapport d'une séance")
    s.add_argument("dossier", help="id de la séance, « derniere », ou son dossier")
    s = sous.add_parser("exporter", help="un .zip de toute la séance")
    s.add_argument("dossier", help="id de la séance, « derniere », ou son dossier")
    s.add_argument("--sortie", help="fichier .zip (défaut : seance_<id>.zip dans le dossier courant)")
    s.add_argument("--sans-bag", action="store_true", help="sans l'enregistrement ROS 2 (plus petit)")
    s = sous.add_parser("liste", help="les séances, la plus récente d'abord")
    s.add_argument("--json", action="store_true")
    return p


def main(argv=None):
    p = analyseur()
    args = p.parse_args(argv)
    if not args.commande:
        p.print_help()
        return 2
    commandes = {"demarrer": commande_demarrer, "arreter": commande_arreter, "etat": commande_etat,
                 "enregistrer": commande_enregistrer, "rapport": commande_rapport, "exporter": commande_exporter,
                 "liste": commande_liste}
    try:
        return commandes[args.commande](args)
    except ValueError as e:
        print(f"erreur : {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
