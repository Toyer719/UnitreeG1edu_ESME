#!/usr/bin/env python3
"""Nœud de présence du conteneur g1-jetson, et petits outils DDS du conteneur (section 10.2).

  presence.py
      nœud g1_jetson : publie /g1_jetson/etat (std_msgs/String, JSON) à 1 Hz :
      {version, image, arch, domaine, interfaces, lancement, lieu, etage, depuis_s}
      et recopie le dernier état dans /tmp/g1_jetson_etat.json.
  presence.py --lire [--delai 5]
      attend un /g1_jetson/etat et l'affiche (JSON) ; code 1 si rien n'arrive
      (« g1-jetson etat », par docker exec).
  presence.py --sujets /state_estimator/odom_pelvis /lf/sportmodestate [--delai 20]
      attend que ces sujets existent sur le réseau DDS ; affiche le bilan (JSON) ;
      code 0 s'ils sont tous vus (« g1-jetson verifier », conteneur en veille sur le robot).

Lancé par demarrer.sh, dans l'environnement de env.sh. Toujours en temps mural.
"""
import argparse
import json
import os
import platform
import sys
import time
from pathlib import Path

SUJET_ETAT = '/g1_jetson/etat'
FICHIER_VERSION = Path('/opt/g1/VERSION')
FICHIER_ETAT = Path('/tmp/g1_jetson_etat.json')
PERIODE_S = 1.0


def lire_version(chemin=FICHIER_VERSION):
    """Champs de /opt/g1/VERSION (lignes cle=valeur) ; dict vide si le fichier manque."""
    champs = {}
    try:
        for ligne in Path(chemin).read_text(encoding='utf-8').splitlines():
            if '=' in ligne:
                cle, valeur = ligne.split('=', 1)
                champs[cle.strip()] = valeur.strip()
    except OSError:
        pass
    return champs


def texte_version(champs):
    """« 2026-10-25T23:10:00+01:00 3f2c1ab » : date de construction et commit."""
    return ' '.join(v for v in (champs.get('date'), champs.get('commit')) if v) or 'inconnue'


def etat_presence(environ, champs_version, maintenant, arch=None):
    """Contenu de /g1_jetson/etat (dict), à partir de l'environnement du conteneur."""
    debut = environ.get('G1_DEBUT')
    try:
        depuis = max(0.0, maintenant - float(debut)) if debut else 0.0
    except ValueError:
        depuis = 0.0
    interfaces = environ.get('G1_INTERFACES_CHOISIES', '')
    lancement = environ.get('G1_LANCEMENT', 'navigation')
    navigation = lancement == 'navigation'
    try:
        domaine = int(environ.get('ROS_DOMAIN_ID', '0'))
    except ValueError:
        domaine = None
    return {
        'version': texte_version(champs_version),
        'image': champs_version.get('image', 'g1-jetson'),
        'arch': arch or platform.machine(),
        'domaine': domaine,
        'interfaces': [i for i in interfaces.split(',') if i],
        'lancement': lancement,
        'lieu': (environ.get('G1_LIEU') or None) if navigation else None,
        'etage': (environ.get('G1_ETAGE') or None) if navigation else None,
        'depuis_s': round(depuis, 1),
    }


def _noeud(nom):
    import rclpy
    rclpy.init()
    return rclpy, rclpy.create_node(nom)


def publier():
    """Nœud g1_jetson : /g1_jetson/etat à 1 Hz, jusqu'à SIGINT ou SIGTERM."""
    import signal
    from std_msgs.msg import String

    rclpy, noeud = _noeud('g1_jetson')
    pub = noeud.create_publisher(String, SUJET_ETAT, 10)
    champs = lire_version()

    def envoyer():
        etat = etat_presence(os.environ, champs, time.time())
        texte = json.dumps(etat, ensure_ascii=False)
        pub.publish(String(data=texte))
        try:
            temporaire = FICHIER_ETAT.with_suffix('.tmp')
            temporaire.write_text(texte + '\n', encoding='utf-8')
            temporaire.replace(FICHIER_ETAT)
        except OSError:
            pass

    def sur_sigterm(_numero, _cadre):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, sur_sigterm)
    noeud.create_timer(PERIODE_S, envoyer)
    envoyer()
    try:
        rclpy.spin(noeud)
    except KeyboardInterrupt:
        pass
    except Exception as erreur:          # ExternalShutdownException, contexte fermé
        if type(erreur).__name__ != 'ExternalShutdownException':
            raise
    noeud.destroy_node()
    rclpy.try_shutdown()
    return 0


def lire(delai):
    """Attend un /g1_jetson/etat ; l'affiche et renvoie 0, ou 1 si rien n'arrive à temps."""
    from std_msgs.msg import String

    rclpy, noeud = _noeud('g1_jetson_lecture')
    recu = []
    noeud.create_subscription(String, SUJET_ETAT, lambda m: recu.append(m.data), 10)
    fin = time.monotonic() + delai
    while not recu and time.monotonic() < fin:
        rclpy.spin_once(noeud, timeout_sec=0.2)
    noeud.destroy_node()
    rclpy.try_shutdown()
    if not recu:
        print(f'aucun {SUJET_ETAT} reçu en {delai:.0f} s', file=sys.stderr)
        return 1
    print(recu[0])
    return 0


def attendre_sujets(sujets, delai):
    """Attend que chaque sujet existe sur le réseau ; bilan JSON ; 0 si tous sont vus."""
    rclpy, noeud = _noeud('g1_jetson_verification')
    vus = {}
    fin = time.monotonic() + delai
    while time.monotonic() < fin and len(vus) < len(sujets):
        rclpy.spin_once(noeud, timeout_sec=0.5)
        for nom, types in noeud.get_topic_names_and_types():
            if nom in sujets:
                vus[nom] = types
    tous = sorted(nom for nom, _ in noeud.get_topic_names_and_types())
    noeud.destroy_node()
    rclpy.try_shutdown()
    bilan = {'vus': {s: vus.get(s) for s in sujets}, 'manquants': [s for s in sujets if s not in vus],
             'nombre_de_sujets': len(tous), 'sujets': tous[:200]}
    print(json.dumps(bilan, ensure_ascii=False))
    return 0 if not bilan['manquants'] else 1


def main(argv=None):
    analyseur = argparse.ArgumentParser(description='Présence du conteneur g1-jetson (/g1_jetson/etat)')
    analyseur.add_argument('--lire', action='store_true', help='affiche le prochain /g1_jetson/etat')
    analyseur.add_argument('--sujets', nargs='+', help='attend que ces sujets existent')
    analyseur.add_argument('--delai', type=float, default=None, help='secondes (5 pour --lire, 20 pour --sujets)')
    args = analyseur.parse_args(argv)
    if args.lire:
        return lire(args.delai or 5.0)
    if args.sujets:
        return attendre_sujets(args.sujets, args.delai or 20.0)
    return publier()


if __name__ == '__main__':
    sys.exit(main())
