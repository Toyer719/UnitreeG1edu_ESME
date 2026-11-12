#!/usr/bin/env python3
"""Outils ROS 2 du critère 16 (le conteneur g1-jetson), lancés sur l'hôte, hors du conteneur.

  service-sport --journal FICHIER
      faux service « sport » minimal : répond à chaque /api/sport/request (code 0, identité
      recopiée) et note chaque requête (une ligne JSON) ; jusqu'à SIGINT ou SIGTERM.
      Sans lui, le pont passerait à robot_muet faute de réponse.
  observer --noeuds pont_g1,guide,... [--delai 90]
      attend, depuis l'hôte, les nœuds du conteneur et un message conforme sur /g1_jetson/etat,
      /pont/etat (attente_reperage), /reperage/etat (non_repere) et /guide/etat ; bilan JSON
  verrouiller [--delai 3]
      publie /pont/arret true (fiable, transient_local) et mesure le temps jusqu'à
      /pont/etat arret_verrouille ; puis false, et attend la sortie du verrou
  dernier-ordre --journal FICHIER --apres T
      code 0 si le service a reçu, après l'instant T (secondes, horloge murale), un 7105
      d'arrêt (velocity [0, 0, 0]) : le pont l'envoie en quittant
  reperer [--delai 60]
      « Repérer le robot » sans l'Atelier : /reperage/demander {id}, puis attend /reperage/etat
      repere (code 0) ou echec (code 1) pour cette demande
  verite --x X --y Y [--max 0.3]
      code 0 si la vérité terrain du faux G1 (/g1_jumeau/odom) est à moins de --max m de (X, Y)

Domaine : ROS_DOMAIN_ID de l'environnement (celui du conteneur lancé par g1-jetson demarrer --local).
"""
import argparse
import json
import math
import signal
import sys
import threading
import time

ETATS_ATTENDUS = {'/pont/etat': 'attente_reperage', '/reperage/etat': 'non_repere'}
SCHEMAS = {'/pont/etat': 'etat_pont', '/reperage/etat': 'etat_reperage'}


def _noeud(nom):
    import rclpy
    from rclpy.executors import SingleThreadedExecutor
    rclpy.init()
    noeud = rclpy.create_node(nom)
    executeur = SingleThreadedExecutor()
    executeur.add_node(noeud)
    fil = threading.Thread(target=lambda: _tourner(executeur), daemon=True)
    fil.start()
    return noeud, executeur, fil


def _tourner(executeur):
    try:
        executeur.spin()
    except Exception:
        pass


def _fermer(noeud, executeur, fil):
    import rclpy
    executeur.shutdown(timeout_sec=2.0)
    fil.join(timeout=2.0)
    noeud.destroy_node()
    rclpy.try_shutdown()


def service_sport(args):
    from rclpy.qos import QoSProfile, ReliabilityPolicy
    from unitree_api.msg import Request, Response

    noeud, executeur, fil = _noeud('faux_sport_critere_16')
    fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
    pub = noeud.create_publisher(Response, '/api/sport/response', fiable)
    journal = open(args.journal, 'a', encoding='utf-8')
    verrou = threading.Lock()

    def sur_requete(req):
        rep = Response()
        rep.header.identity.id = req.header.identity.id
        rep.header.identity.api_id = req.header.identity.api_id
        rep.header.status.code = 0
        pub.publish(rep)
        with verrou:
            journal.write(json.dumps({'t': time.time(), 'id': req.header.identity.id,
                                      'api_id': req.header.identity.api_id,
                                      'parameter': req.parameter}) + '\n')
            journal.flush()

    noeud.create_subscription(Request, '/api/sport/request', sur_requete, fiable)
    fin = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: fin.set())
    signal.signal(signal.SIGINT, lambda *_: fin.set())
    print('faux service sport prêt sur /api/sport/request', flush=True)
    while not fin.wait(0.5):
        pass
    _fermer(noeud, executeur, fil)
    journal.close()
    return 0


def observer(args):
    from std_msgs.msg import String
    from atelier.lieu import valider_message

    noeuds_voulus = [n for n in args.noeuds.split(',') if n]
    sujets = ['/g1_jetson/etat', '/pont/etat', '/reperage/etat', '/guide/etat']
    noeud, executeur, fil = _noeud('observateur_critere_16')
    recus = {s: [] for s in sujets}
    verrou = threading.Lock()

    def abonner(sujet):
        def rappel(msg):
            with verrou:
                recus[sujet].append((time.time(), msg.data))
        noeud.create_subscription(String, sujet, rappel, 10)

    for sujet in sujets:
        abonner(sujet)
    debut = time.time()
    fin = time.monotonic() + args.delai
    vus = {}
    bilan = {}
    while time.monotonic() < fin:
        for nom in noeud.get_node_names():
            vus.setdefault(nom, round(time.time() - debut, 1))
        bilan = _bilan(recus, verrou, noeuds_voulus, vus, valider_message)
        if bilan['complet']:
            break
        time.sleep(0.5)
    bilan['duree_s'] = round(time.time() - debut, 1)
    _fermer(noeud, executeur, fil)
    print(json.dumps(bilan, ensure_ascii=False))
    return 0 if bilan['complet'] and not bilan['non_conformes'] else 1


def _bilan(recus, verrou, noeuds_voulus, vus, valider_message):
    with verrou:
        copie = {s: list(v) for s, v in recus.items()}
    manquants = [n for n in noeuds_voulus if n not in vus]
    sujets = {}
    non_conformes = []
    for sujet, messages in copie.items():
        etats = []
        for _t, texte in messages:
            try:
                donnees = json.loads(texte)
            except ValueError:
                non_conformes.append(f'{sujet} : pas du JSON ({texte[:60]})')
                continue
            if sujet in SCHEMAS:
                erreurs = valider_message(SCHEMAS[sujet], donnees)
                if erreurs:
                    non_conformes.append(f'{sujet} : {erreurs[:2]}')
            etats.append(donnees.get('etat'))
        sujets[sujet] = {'messages': len(messages), 'etats': sorted(set(e for e in etats if e)),
                         'dernier': json.loads(messages[-1][1]) if messages else None}
    sujets_ok = all(sujets[s]['messages'] > 0 for s in sujets)
    etats_ok = all(ETATS_ATTENDUS[s] in sujets[s]['etats'] for s in ETATS_ATTENDUS)
    return {'complet': not manquants and sujets_ok and etats_ok, 'noeuds_manquants': manquants,
            'noeuds_vus': {n: vus[n] for n in noeuds_voulus if n in vus}, 'sujets': sujets,
            'non_conformes': non_conformes[:10]}


def verrouiller(args):
    from rclpy.qos import DurabilityPolicy, QoSProfile, ReliabilityPolicy
    from std_msgs.msg import Bool, String

    noeud, executeur, fil = _noeud('verrou_critere_16')
    qos_verrou = QoSProfile(depth=1, reliability=ReliabilityPolicy.RELIABLE,
                            durability=DurabilityPolicy.TRANSIENT_LOCAL)
    pub = noeud.create_publisher(Bool, '/pont/arret', qos_verrou)
    etats = []

    def sur_etat(msg):
        try:
            etats.append((time.time(), json.loads(msg.data).get('etat')))
        except (ValueError, AttributeError):
            etats.append((time.time(), None))

    noeud.create_subscription(String, '/pont/etat', sur_etat, 10)
    time.sleep(1.0)                              # découverte du pont
    t0 = time.time()
    pub.publish(Bool(data=True))
    verrouille = _attendre(etats, t0, lambda e: e == 'arret_verrouille', args.delai)
    t1 = time.time()
    pub.publish(Bool(data=False))
    libere = _attendre(etats, t1, lambda e: e != 'arret_verrouille', args.delai)
    time.sleep(0.3)
    _fermer(noeud, executeur, fil)
    bilan = {'verrouille_s': None if verrouille is None else round(verrouille - t0, 2),
             'libere_s': None if libere is None else round(libere - t1, 2),
             'etats': sorted(set(e for _, e in etats if e))}
    print(json.dumps(bilan, ensure_ascii=False))
    return 0 if verrouille is not None and verrouille - t0 < args.delai else 1


def _attendre(etats, depuis, condition, delai):
    fin = time.monotonic() + delai
    while time.monotonic() < fin:
        for t, etat in list(etats):
            if t >= depuis and condition(etat):
                return t
        time.sleep(0.05)
    return None


def dernier_ordre(args):
    """Un 7105 d'arrêt reçu après --apres ? Affiche les ordres reçus après cet instant."""
    ordres = []
    with open(args.journal, encoding='utf-8') as f:
        for ligne in f:
            try:
                ordre = json.loads(ligne)
            except ValueError:
                continue
            if ordre['t'] >= args.apres:
                ordres.append(ordre)
    arrets = []
    for ordre in ordres:
        try:
            vitesse = json.loads(ordre['parameter']).get('velocity')
        except (ValueError, AttributeError):
            continue
        if ordre['api_id'] == 7105 and vitesse and all(math.isfinite(v) and abs(v) < 1e-9 for v in vitesse):
            arrets.append(ordre)
    print(json.dumps({'ordres_apres': len(ordres), 'arrets': len(arrets),
                      'dernier': ordres[-1] if ordres else None}, ensure_ascii=False))
    return 0 if arrets else 1


def reperer(args):
    from std_msgs.msg import String
    from atelier.lieu import valider_message

    noeud, executeur, fil = _noeud('reperage_critere_16')
    etats = []

    def sur_etat(msg):
        try:
            etats.append(json.loads(msg.data))
        except ValueError:
            pass

    noeud.create_subscription(String, '/reperage/etat', sur_etat, 10)
    pub = noeud.create_publisher(String, '/reperage/demander', 10)
    time.sleep(2.0)                              # découverte du relais
    ident = f'critere-16-{int(time.time())}'
    t0 = time.time()
    pub.publish(String(data=json.dumps({'id': ident})))
    fin = time.monotonic() + args.delai
    dernier = None
    while time.monotonic() < fin:
        miens = [e for e in list(etats) if e.get('demande') == ident and e.get('etat') in ('repere', 'echec')]
        if miens:
            dernier = miens[-1]
            break
        time.sleep(0.2)
    non_conformes = [e for e in list(etats) if valider_message('etat_reperage', e)]
    _fermer(noeud, executeur, fil)
    print(json.dumps({'duree_s': round(time.time() - t0, 1), 'etat': dernier,
                      'non_conformes': len(non_conformes)}, ensure_ascii=False))
    return 0 if dernier and dernier['etat'] == 'repere' and not non_conformes else 1


def verite(args):
    from nav_msgs.msg import Odometry

    noeud, executeur, fil = _noeud('verite_critere_16')
    poses = []
    noeud.create_subscription(Odometry, '/g1_jumeau/odom', lambda m: poses.append(m.pose.pose.position), 10)
    fin = time.monotonic() + 10.0
    while not poses and time.monotonic() < fin:
        time.sleep(0.1)
    _fermer(noeud, executeur, fil)
    if not poses:
        print('aucun /g1_jumeau/odom en 10 s')
        return 1
    p = poses[-1]
    ecart = math.hypot(p.x - args.x, p.y - args.y)
    print(f'vérité ({p.x:.2f} ; {p.y:.2f}), cible ({args.x:.2f} ; {args.y:.2f}) : {ecart:.2f} m')
    return 0 if ecart <= args.max else 1


def main():
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sous = analyseur.add_subparsers(dest='action', required=True)
    p = sous.add_parser('service-sport')
    p.add_argument('--journal', required=True)
    p = sous.add_parser('observer')
    p.add_argument('--noeuds', required=True)
    p.add_argument('--delai', type=float, default=90.0)
    p = sous.add_parser('verrouiller')
    p.add_argument('--delai', type=float, default=3.0)
    p = sous.add_parser('dernier-ordre')
    p.add_argument('--journal', required=True)
    p.add_argument('--apres', type=float, required=True)
    p = sous.add_parser('reperer')
    p.add_argument('--delai', type=float, default=60.0)
    p = sous.add_parser('verite')
    p.add_argument('--x', type=float, required=True)
    p.add_argument('--y', type=float, required=True)
    p.add_argument('--max', type=float, default=0.3)
    args = analyseur.parse_args()
    actions = {'service-sport': service_sport, 'observer': observer, 'verrouiller': verrouiller,
               'dernier-ordre': dernier_ordre, 'reperer': reperer, 'verite': verite}
    return actions[args.action](args)


if __name__ == '__main__':
    sys.exit(main())
