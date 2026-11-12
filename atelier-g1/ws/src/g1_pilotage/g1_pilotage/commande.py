"""
Commande g1-pilotage : l'onglet Pilotage de l'Atelier en ligne de commande (section 11.5 du plan).

  g1-pilotage noeud [--port 8010] [--hote 127.0.0.1]     lance le nœud pilotage (ros2 run)
  g1-pilotage etat                                       état du pilotage
  g1-pilotage prendre [--forcer] | rendre                prendre ou rendre la main
  g1-pilotage posture N [--portique]                     500, 706, 702, 3 ; 1 et 0 au portique
  g1-pilotage geste N | tache N | dire TEXTE | volume N | led R G B
  g1-pilotage danses [--lire] | danse N --zone-libre
  g1-pilotage verifier FICHIER | jouer FICHIER --zone-libre
  g1-pilotage arret                                      ARRÊT (toujours permis)

Le nœud est joint à $G1_PILOTAGE_URL (défaut http://127.0.0.1:8010), avec le jeton
$G1_PILOTAGE_JETON. Codes de sortie : 0 fait, 1 refusé ou échec (message en français), 2 commande
mal tapée. Python du système, sans ROS (sauf « noeud »).
"""
import argparse
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request

URL_DEFAUT = 'http://127.0.0.1:8010'
TRADUCTIONS = [('usage:', 'usage :'), ('the following arguments are required:', 'il manque :'),
               ('invalid choice:', 'choix inconnu :'), ('choose from', 'possibles :'),
               ('unrecognized arguments:', 'arguments inconnus :'),
               ('invalid int value:', 'nombre entier attendu :'), ('error:', 'erreur :'),
               ('positional arguments', 'arguments'), ('options:', 'options :'),
               ('show this help message and exit', 'affiche cette aide')]


class Analyseur(argparse.ArgumentParser):
    """ArgumentParser qui parle français."""

    def format_help(self):
        texte = super().format_help()
        for anglais, francais in TRADUCTIONS:
            texte = texte.replace(anglais, francais)
        return texte

    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f'g1-pilotage : {message}\n')


def url():
    return (os.environ.get('G1_PILOTAGE_URL') or URL_DEFAUT).rstrip('/')


def appeler(chemin, corps=None, delai=10.0):
    """(statut, corps JSON) du nœud ; (0, {detail}) s'il ne répond pas."""
    entetes = {'Content-Type': 'application/json'}
    jeton = os.environ.get('G1_PILOTAGE_JETON', '')
    if jeton:
        entetes['X-Jeton'] = jeton
    donnees = None if corps is None else json.dumps(corps).encode()
    requete = urllib.request.Request(url() + chemin, data=donnees, headers=entetes,
                                     method='GET' if corps is None else 'POST')
    try:
        with urllib.request.urlopen(requete, timeout=delai) as r:
            return r.status, json.loads(r.read() or b'{}')
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b'{}')
        except ValueError:
            return e.code, {'detail': f'erreur HTTP {e.code}'}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return 0, {'detail': f'le nœud pilotage ne répond pas à {url()} ({e}) : lancez-le '
                             '(g1-pilotage noeud) ou vérifiez G1_PILOTAGE_URL'}


def afficher(statut, corps, montrer_etat=False):
    detail = corps.get('detail', '')
    if 200 <= statut < 300:
        print(detail or 'fait')
        if montrer_etat and 'etat' in corps:
            print(json.dumps(corps['etat'], ensure_ascii=False, indent=2))
        return 0
    print(f'refusé ({statut}) : {detail}', file=sys.stderr)
    for e in corps.get('erreurs') or []:
        print(f'  - {e}', file=sys.stderr)
    return 1


def lire_choregraphie(fichier):
    try:
        import yaml
    except ImportError:
        print('g1-pilotage : PyYAML manque (python3-yaml)', file=sys.stderr)
        sys.exit(1)
    chemin = Path(fichier).expanduser()
    if not chemin.is_file():
        racine = Path(__file__).resolve().parents[4] / 'choregraphies'
        chemin = racine / f'{fichier}.choregraphie.yaml'
    if not chemin.is_file():
        print(f'g1-pilotage : chorégraphie introuvable : {fichier}', file=sys.stderr)
        sys.exit(1)
    return yaml.safe_load(chemin.read_text(encoding='utf-8'))


def analyseur():
    a = Analyseur(prog='g1-pilotage',
                  description='Pilotage du G1 en ligne de commande (onglet Pilotage de '
                              'l\'Atelier, section 11.5 du plan). Nœud : $G1_PILOTAGE_URL.')
    s = a.add_subparsers(dest='commande', required=True, metavar='commande')
    n = s.add_parser('noeud', help='lance le nœud pilotage (ros2 run g1_pilotage pilote)')
    n.add_argument('--port', type=int, default=None)
    n.add_argument('--hote', default=None)
    n.add_argument('--vitesse-max', default=None)
    s.add_parser('etat', help='état du pilotage')
    p = s.add_parser('prendre', help='prendre la main')
    p.add_argument('--forcer', action='store_true', help='arrête le guide s\'il est en visite')
    s.add_parser('rendre', help='rendre la main au guide')
    p = s.add_parser('posture', help='posture : 500, 706, 702, 3 ; 1 et 0 avec --portique')
    p.add_argument('fsm', type=int)
    p.add_argument('--portique', action='store_true', help='le robot est tenu au portique')
    for nom, aide, cle in (('geste', 'geste d\'Unitree (99 : relâcher)', 'action'),
                           ('tache', 'tâche : 0, 1 saluer ; 2, 3 serrer la main', 'tache'),
                           ('volume', 'volume de 0 à 100', 'volume')):
        p = s.add_parser(nom, help=aide)
        p.add_argument(cle, type=int)
    p = s.add_parser('dire', help='phrase dite par la synthèse du robot (1001)')
    p.add_argument('texte')
    p = s.add_parser('led', help='couleur de la LED (0 à 255)')
    for c in 'rgb':
        p.add_argument(c, type=int)
    p = s.add_parser('danses', help='danses du robot')
    p.add_argument('--lire', action='store_true', help='relit la liste dans le robot (7100)')
    p = s.add_parser('danse', help='joue une danse du robot')
    p.add_argument('id', type=int)
    p.add_argument('--zone-libre', action='store_true', help='2 à 3 m libres autour du robot')
    p = s.add_parser('verifier', help='vérifie une chorégraphie (fichier ou id)')
    p.add_argument('fichier')
    p = s.add_parser('jouer', help='joue une chorégraphie (fichier ou id)')
    p.add_argument('fichier')
    p.add_argument('--zone-libre', action='store_true', help='2 à 3 m libres autour du robot')
    s.add_parser('arret', help='ARRÊT : StopMove, chorégraphie arrêtée, bras relâchés')
    return a


def noeud(args):
    commande = ['ros2', 'run', 'g1_pilotage', 'pilote']
    options = (('--port', args.port), ('--hote', args.hote), ('--vitesse-max', args.vitesse_max))
    for option, valeur in options:
        if valeur is not None:
            commande += [option, str(valeur)]
    os.execvp(commande[0], commande)


def main(argv=None):
    args = analyseur().parse_args(argv)
    c = args.commande
    if c == 'noeud':
        return noeud(args)
    if c == 'etat':
        statut, corps = appeler('/etat')
        if statut == 200:
            print(json.dumps(corps, ensure_ascii=False, indent=2))
            return 0
        return afficher(statut, corps)
    if c == 'prendre':
        return afficher(*appeler('/maitre', {'maitre': 'pilotage', 'forcer': args.forcer,
                                             'par': 'g1-pilotage'}))
    if c == 'rendre':
        return afficher(*appeler('/maitre', {'maitre': 'guide', 'par': 'g1-pilotage'}))
    if c == 'posture':
        corps = {'fsm': args.fsm, 'portique': args.portique}
        statut, reponse = appeler('/posture', corps)
        if statut == 428 and reponse.get('jeton') and args.portique:
            question = f'{reponse["detail"]} Tapez « oui » : '
            confirmation = input(question) if sys.stdin.isatty() else ''
            if confirmation.strip().lower() != 'oui':
                print('annulé : rien n\'a été envoyé au robot', file=sys.stderr)
                return 1
            statut, reponse = appeler('/posture', dict(corps, jeton=reponse['jeton']))
        return afficher(statut, reponse)
    if c == 'geste':
        return afficher(*appeler('/geste', {'action': args.action}))
    if c == 'tache':
        return afficher(*appeler('/tache', {'tache': args.tache}))
    if c == 'volume':
        return afficher(*appeler('/volume', {'volume': args.volume}))
    if c == 'dire':
        return afficher(*appeler('/voix', {'texte': args.texte}))
    if c == 'led':
        return afficher(*appeler('/led', {'r': args.r, 'g': args.g, 'b': args.b}))
    if c == 'danses':
        statut, corps = appeler('/danses?lire=1' if args.lire else '/danses')
        if statut != 200:
            return afficher(statut, corps)
        for d in corps['danses']:
            marque = 'INTERDITE' if d['interdite'] else ''
            print(f'{d["id"]:>4}  {d["nom"]:<20} {d["duree_s"] or "?":>6} s  {marque:<10} '
                  f'{d["remarque"]}')
        return 0
    if c == 'danse':
        return afficher(*appeler('/danse', {'id': args.id, 'zone_libre': args.zone_libre}))
    if c == 'verifier':
        sys.path.insert(0, str(Path(__file__).resolve().parents[4]))
        from atelier.lieu.pilotage import verifier_choregraphie
        erreurs = verifier_choregraphie(lire_choregraphie(args.fichier))
        for e in erreurs:
            print(f'  - {e}', file=sys.stderr)
        print('chorégraphie sûre' if not erreurs else f'{len(erreurs)} erreur(s)')
        return 0 if not erreurs else 1
    if c == 'jouer':
        corps = {'choregraphie': lire_choregraphie(args.fichier), 'zone_libre': args.zone_libre}
        return afficher(*appeler('/choregraphie', corps))
    if c == 'arret':
        return afficher(*appeler('/arret', {'par': 'g1-pilotage'}, delai=3.0))
    return 2


if __name__ == '__main__':
    sys.exit(main())
