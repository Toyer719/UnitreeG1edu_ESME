"""Outils des critères des passants (6, 23, 24 et 25 ; section 11.3 du plan), agent Passants.

  outils_passants_e2e.py verifier CSV... [--essais N] [--arrivees-min N] [--duree-max S]
        [--detours-max N] [--detours-min N] [--contacts-max N] [--contacts-robot-max N]
        [--bord-min-par-essai M] [--longueur-max M] [--attentes-min N] [--attente-min-s S]
        [--colonnes]
      lit un ou plusieurs CSV de g1-banc (leurs lignes s'ajoutent), affiche un bilan en français
      et rend 0 si chaque seuil donné est tenu, 1 sinon ;
  outils_passants_e2e.py ecouter --sortie FICHIER [--duree S]
      écrit en JSON, une ligne par message, /guide/etat et /guide/evenement (avec l'heure murale et
      le temps simulé), jusqu'à SIGINT ou SIGTERM ;
  outils_passants_e2e.py journal FICHIER [--evenement CODE] [--compter] [--itineraire-par NOEUD]
      lit ce que « ecouter » a écrit : rend 0 si l'événement a été vu (--compter : affiche combien),
      et si un itinéraire de détour passe par NOEUD ;
  outils_passants_e2e.py guide-connait ETAT
      rend 0 si le guide (g1_nav/guide.py) connaît cet état (ex. attente_passage), 77 sinon.
"""
import argparse
import csv
import json
import math
import signal
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
GUIDE = RACINE / 'ws' / 'src' / 'g1_nav' / 'g1_nav' / 'guide.py'


def lire(chemins):
    lignes = []
    for chemin in chemins:
        with open(chemin, newline='', encoding='utf-8') as f:
            lignes += list(csv.DictReader(f))
    return lignes


def nombre(texte, defaut=None):
    try:
        return float(texte)
    except (TypeError, ValueError):
        return defaut


def verifier(args):
    lignes = lire(args.csv)
    fautes = []
    n = len(lignes)
    reussis = [ligne for ligne in lignes if ligne['reussite'] == 'oui']
    somme = {c: sum(int(nombre(ligne.get(c), 0)) for ligne in lignes)
             for c in ('contacts', 'contacts_robot', 'contacts_pieton', 'contacts_aucun', 'detours', 'attentes_passage')}
    bords = [nombre(ligne.get('distance_min_bord_m')) for ligne in lignes]
    bords_connus = [b for b in bords if b is not None]
    print(f'{n} trajets ; {len(reussis)} arrivés à moins de 0,3 m ; durées : '
          + ', '.join(f'{nombre(ligne["duree_s"], 0):.0f} s' for ligne in lignes))
    print(f'contacts : {somme["contacts"]} (causés par le robot : {somme["contacts_robot"]}, par le piéton : '
          f'{somme["contacts_pieton"]}, sans cause : {somme["contacts_aucun"]}) ; détours : {somme["detours"]} ; '
          f'attentes de passage : {somme["attentes_passage"]}')
    if bords_connus:
        print('distance bord à bord minimale par trajet : ' + ', '.join(f'{b:.2f} m' for b in bords_connus))
    longueurs = [nombre(ligne.get('longueur_m'), 0.0) for ligne in lignes]
    print('longueur parcourue : ' + ', '.join(f'{v:.1f} m' for v in longueurs)
          + ' (itinéraire direct : ' + ', '.join(str(ligne.get('longueur_directe_m', '')) for ligne in lignes) + ')')
    if args.essais is not None and n != args.essais:
        fautes.append(f'{n} trajets dans le CSV, {args.essais} attendus')
    if args.arrivees_min is not None:
        dans_le_temps = [ligne for ligne in reussis
                         if args.duree_max is None or nombre(ligne['duree_s'], 1e9) <= args.duree_max]
        if len(dans_le_temps) < args.arrivees_min:
            fautes.append(f'{len(dans_le_temps)} arrivée(s) à moins de 0,3 m'
                          + (f' en moins de {args.duree_max:.0f} s' if args.duree_max else '')
                          + f', il en faut {args.arrivees_min}')
    elif args.duree_max is not None:
        longs = [ligne for ligne in lignes if nombre(ligne['duree_s'], 1e9) > args.duree_max]
        if longs:
            fautes.append(f'{len(longs)} trajet(s) de plus de {args.duree_max:.0f} s')
    if args.detours_max is not None:
        trop = [ligne for ligne in lignes if int(nombre(ligne['detours'], 0)) > args.detours_max]
        if trop:
            fautes.append(f'{len(trop)} trajet(s) avec plus de {args.detours_max} détour(s)')
    if args.detours_min is not None:
        peu = [ligne for ligne in lignes if int(nombre(ligne['detours'], 0)) < args.detours_min]
        if peu:
            fautes.append(f'{len(peu)} trajet(s) avec moins de {args.detours_min} détour(s)')
    if args.contacts_max is not None and somme['contacts'] > args.contacts_max:
        fautes.append(f'{somme["contacts"]} contact(s), au plus {args.contacts_max}')
    if args.contacts_robot_max is not None and somme['contacts_robot'] > args.contacts_robot_max:
        fautes.append(f'{somme["contacts_robot"]} contact(s) causé(s) par le robot, au plus {args.contacts_robot_max}')
    if args.bord_min_par_essai is not None:
        faibles = [b for b in bords if b is None or b < args.bord_min_par_essai]
        if faibles:
            fautes.append(f'{len(faibles)} trajet(s) sous {args.bord_min_par_essai:.2f} m bord à bord (ou sans mesure)')
    if args.longueur_max is not None:
        trop = [v for v in longueurs if v > args.longueur_max]
        if trop:
            fautes.append(f'{len(trop)} trajet(s) de plus de {args.longueur_max:.0f} m ({max(trop):.1f} m)')
    if args.attentes_min is not None:
        peu = [ligne for ligne in lignes if int(nombre(ligne.get('attentes_passage'), 0)) < args.attentes_min]
        if peu:
            fautes.append(f'{len(peu)} trajet(s) sans attente de passage (attente_passage)')
    if args.attente_min_s is not None:
        courtes = [ligne for ligne in lignes if nombre(ligne.get('duree_attente_passage_s'), 0.0) < args.attente_min_s]
        if courtes:
            fautes.append(f'{len(courtes)} trajet(s) où le guide a attendu moins de {args.attente_min_s:.0f} s '
                          'avant le détour')
    if args.colonnes:
        sys.path.insert(0, str(RACINE))
        from atelier.lieu.passants import COLONNES_BANC_V4
        with open(args.csv[0], newline='', encoding='utf-8') as f:
            entete = next(csv.reader(f))
        attendues = ['numero', 'depart', 'arrivee', 'reussite', 'duree_s', 'arrets', 'distance_min_pietons_m',
                     'detours', 'erreur_m', 'etat_final'] + list(COLONNES_BANC_V4)
        if entete != attendues:
            fautes.append(f'colonnes du CSV : {entete}, attendues : {attendues}')
        else:
            print('colonnes du CSV : celles de la vague 1, puis ' + ', '.join(COLONNES_BANC_V4))
    for faute in fautes:
        print(f'NON : {faute}')
    if not fautes:
        print('seuils tenus')
    return 0 if not fautes else 1


def ecouter(args):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    from rosgraph_msgs.msg import Clock
    from std_msgs.msg import String

    rclpy.init()
    noeud = rclpy.create_node('ecoute_passants_e2e')
    sortie = open(args.sortie, 'a', encoding='utf-8')
    horloge = {'t': None}

    def ecrire(sujet, msg):
        try:
            donnees = json.loads(msg.data)
        except ValueError:
            donnees = {'texte': msg.data}
        sortie.write(json.dumps({'sujet': sujet, 'mur': round(time.time(), 3), 'sim': horloge['t'],
                                 'message': donnees}, ensure_ascii=False) + '\n')
        sortie.flush()

    noeud.create_subscription(String, '/guide/etat', lambda m: ecrire('/guide/etat', m), 50)
    noeud.create_subscription(String, '/guide/evenement', lambda m: ecrire('/guide/evenement', m), 50)
    noeud.create_subscription(Clock, '/clock', lambda m: horloge.update(t=m.clock.sec + m.clock.nanosec * 1e-9), 10)
    fin = {'drapeau': False}
    signal.signal(signal.SIGINT, lambda *_: fin.update(drapeau=True))
    signal.signal(signal.SIGTERM, lambda *_: fin.update(drapeau=True))
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    limite = time.monotonic() + args.duree if args.duree else math.inf
    while not fin['drapeau'] and time.monotonic() < limite:
        executeur.spin_once(timeout_sec=0.2)
    sortie.close()
    noeud.destroy_node()
    rclpy.try_shutdown()
    return 0


def journal(args):
    messages = []
    with open(args.fichier, encoding='utf-8') as f:
        for ligne in f:
            try:
                messages.append(json.loads(ligne))
            except ValueError:
                continue
    code = 0
    if args.evenement:
        vus = [m for m in messages if m['sujet'] == '/guide/evenement' and m['message'].get('code') == args.evenement]
        print(f'événement « {args.evenement} » : {len(vus)} fois'
              + (f' (« {vus[0]["message"].get("texte", "")} »)' if vus else ''))
        if args.compter is not None and len(vus) < args.compter:
            code = 1
        elif not vus:
            code = 1
    if args.itineraire_par:
        detours = [m['message'] for m in messages
                   if m['sujet'] == '/guide/etat' and m['message'].get('etat') == 'detour']
        par = [d for d in detours if args.itineraire_par in (d.get('itineraire') or [])]
        print(f'itinéraires de détour : {len(detours)} messages, {len(par)} par « {args.itineraire_par} »'
              + (f' ({" → ".join(par[0]["itineraire"])})' if par else ''))
        if not par:
            code = 1
    return code


def guide_connait(args):
    if not GUIDE.is_file() or f"'{args.etat}'" not in GUIDE.read_text(encoding='utf-8') \
            and f'"{args.etat}"' not in GUIDE.read_text(encoding='utf-8'):
        print(f'le guide ({GUIDE}) ne connaît pas encore l\'état « {args.etat} »')
        return 77
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(description='Outils des critères des passants')
    sous = p.add_subparsers(dest='commande', required=True)
    v = sous.add_parser('verifier')
    v.add_argument('csv', nargs='+')
    for option, type_ in (('--essais', int), ('--arrivees-min', int), ('--duree-max', float),
                          ('--detours-max', int), ('--detours-min', int), ('--contacts-max', int),
                          ('--contacts-robot-max', int), ('--bord-min-par-essai', float),
                          ('--longueur-max', float), ('--attentes-min', int), ('--attente-min-s', float)):
        v.add_argument(option, type=type_, default=None)
    v.add_argument('--colonnes', action='store_true')
    e = sous.add_parser('ecouter')
    e.add_argument('--sortie', required=True)
    e.add_argument('--duree', type=float, default=None)
    j = sous.add_parser('journal')
    j.add_argument('fichier')
    j.add_argument('--evenement', default=None)
    j.add_argument('--compter', type=int, default=None)
    j.add_argument('--itineraire-par', default=None)
    g = sous.add_parser('guide-connait')
    g.add_argument('etat')
    args = p.parse_args(argv)
    return {'verifier': verifier, 'ecouter': ecouter, 'journal': journal, 'guide-connait': guide_connait}[args.commande](args)


if __name__ == '__main__':
    sys.exit(main())
