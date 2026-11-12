"""
Commande g1-guide : lancer la navigation, envoyer le robot, l'arrêter.

  g1-guide navigation --lieu L --etage E [--simu] [--moteur nav2|unitree]
                      [--localisation simu|unitree|amcl|externe] [--pont auto|oui|non]
                      [--vitesse-max M_PAR_S] [--sans-personnes]
      Nav2, routeur et guide sur la carte du lieu (ros2 launch g1_nav navigation.launch.py) ;
      --localisation : défaut simu avec --simu, unitree sinon (repérage par 1804, section 10.5) ;
      --pont : /cmd_vel → ordres de marche du robot (défaut auto : avec Nav2, sauf en simu) ;
      --vitesse-max : plafonds du pont et vitesses de Nav2 abaissés (premiers essais, ex. 0.2 ;
      refusée sous 0,2 m/s) ; défaut : la variable G1_VITESSE_MAX, sinon les plafonds du
      contrat ;
      --sans-personnes : sans le détecteur de personnes au LiDAR (ni accompagnement, ni attente
      des passants)
  g1-guide aller ID [--accompagner] [--sans-retour] [--sans-suivre]
      envoie le robot vers la salle ou le nœud ID (« principal » : le point principal), puis
      affiche l'état du guide et ses messages au visiteur jusqu'à l'arrivée (Ctrl+C arrête
      l'affichage, pas le robot) ; --accompagner : il suit le visiteur ; --sans-retour : il ne
      revient pas seul au point principal ensuite
  g1-guide stop
      arrête le robot tout de suite
  g1-guide etat
      affiche une fois l'état du guide

Code de sortie : 0 si tout va bien, 1 en cas d'erreur (guide absent, échec), 2 si la commande
est mal tapée.
"""
import argparse
import json
import os
import sys
import time

# Messages d'argparse les plus courants, en français
TRADUCTIONS = [('the following arguments are required:', 'il manque :'),
               ('invalid choice:', 'choix inconnu :'), ('choose from', 'possibles :'),
               ('unrecognized arguments:', 'arguments inconnus :'),
               ('expected one argument', 'il faut une valeur'),
               ('invalid float value:', 'nombre attendu, pas')]

# Délai pour trouver le guide sur le réseau ROS 2, en secondes
DELAI_DECOUVERTE_S = 5.0
# --pont de g1-guide → argument pont:= du lancement
PONTS = {'auto': 'auto', 'oui': 'true', 'non': 'false'}


class Analyseur(argparse.ArgumentParser):
    """ArgumentParser qui parle français : aide, titres et messages d'erreur."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, add_help=False, **kwargs)
        self._positionals.title = 'arguments'
        self._optionals.title = 'options'
        self.add_argument('-h', '--help', action='help', help='affiche cette aide et quitte')

    def error(self, message):
        for anglais, francais in TRADUCTIONS:
            message = message.replace(anglais, francais)
        self.print_usage(sys.stderr)
        self.exit(2, f'erreur : {message}\nAide : {self.prog} --help\n')


def texte_etat(etat):
    """Une ligne lisible à partir d'un état du guide (dict de /guide/etat)."""
    morceaux = [etat.get('etat', '?')]
    if etat.get('cible'):
        morceaux.append(f'vers {etat["cible"]}')
    if etat.get('reste_m') is not None:
        morceaux.append(f'reste {etat["reste_m"]:.1f} m')
    if etat.get('itineraire'):
        morceaux.append('par ' + ' → '.join(etat['itineraire']))
    texte = ', '.join(morceaux)
    return f'{texte} : {etat["message"]}' if etat.get('message') else texte


def refus_vitesse_max(texte):
    """
    Raison du refus de --vitesse-max (ou de G1_VITESSE_MAX), ou None si elle est permise.

    Vague 5 (section 12.6 du plan) : au plus 0,4 m/s (plafond du pont), au moins 0,2 m/s (le vrai
    robot ne fait aucun pas plus lentement). Le lancement le vérifie aussi (plafonds_pont).
    """
    try:
        from atelier.lieu.robot import LIMITES_PONT, MESSAGE_VITESSE_MAX_BASSE, VITESSE_MAX_MIN
        plafond = LIMITES_PONT['vx']
    except ImportError:        # atelier absent : les valeurs du contrat
        plafond, VITESSE_MAX_MIN = 0.4, 0.2
        MESSAGE_VITESSE_MAX_BASSE = 'le robot ne marche pas sous 0,2 m/s'
    try:
        vitesse = float(str(texte).strip().replace(',', '.'))
    except ValueError:
        vitesse = float('nan')
    if not 0.0 < vitesse <= plafond:            # faux aussi pour NaN
        return (f'--vitesse-max {texte} : il faut une vitesse en m/s, plus grande que 0 et au '
                f'plus {plafond:g} (ex. 0.2)')
    if vitesse < VITESSE_MAX_MIN - 1e-9:
        return (f'--vitesse-max {texte} refusée : {MESSAGE_VITESSE_MAX_BASSE} (le vrai robot ne '
                f'ferait aucun pas) ; mettez au moins {VITESSE_MAX_MIN:g}')
    return None


def commande_navigation(args):
    """Arguments de ros2 launch pour g1-guide navigation (section 4.5 du plan)."""
    commande = ['ros2', 'launch', 'g1_nav', 'navigation.launch.py', f'lieu:={args.lieu}',
                f'etage:={args.etage}', f'simu:={"true" if args.simu else "false"}',
                f'moteur:={args.moteur}']
    if getattr(args, 'localisation', None):
        commande.append(f'localisation:={args.localisation}')
    pont = getattr(args, 'pont', 'auto') or 'auto'
    if pont != 'auto':
        commande.append(f'pont:={PONTS[pont]}')
    vitesse = getattr(args, 'vitesse_max', None) or os.environ.get('G1_VITESSE_MAX', '').strip()
    if vitesse:
        commande.append(f'vitesse_max:={vitesse}')
    if getattr(args, 'sans_personnes', False):
        commande.append('personnes:=false')
    return commande


def demande_aller(cible, accompagner=False, retour=True):
    """Texte de /guide/aller : l'id seul, ou le JSON de la vague 4 (schéma demande_guide)."""
    if not accompagner and retour:
        return cible
    corps = {'cible': cible, 'accompagner': bool(accompagner), 'source': 'g1-guide'}
    if not retour:
        corps['retour'] = False
    return json.dumps(corps)


class Client:
    """Petit nœud ROS 2 qui publie sur /guide/aller ou /guide/stop et lit /guide/etat."""

    def __init__(self):
        import rclpy
        from std_msgs.msg import Empty, String

        rclpy.init()
        self.rclpy = rclpy
        self.noeud = rclpy.create_node('g1_guide_commande')
        self.String, self.Empty = String, Empty
        self.pub_aller = self.noeud.create_publisher(String, '/guide/aller', 10)
        self.pub_stop = self.noeud.create_publisher(Empty, '/guide/stop', 10)
        self.etat = None
        self.evenements = []
        self.noeud.create_subscription(String, '/guide/etat', self._sur_etat, 10)
        self.noeud.create_subscription(String, '/guide/evenement', self._sur_evenement, 10)

    def _sur_etat(self, msg):
        try:
            self.etat = json.loads(msg.data)
        except ValueError:
            pass

    def _sur_evenement(self, msg):
        try:
            self.evenements.append(json.loads(msg.data))
        except ValueError:
            pass

    def tourner(self, duree_s):
        fin = time.monotonic() + duree_s
        while time.monotonic() < fin:
            self.rclpy.spin_once(self.noeud, timeout_sec=max(0.0, fin - time.monotonic()))

    def attendre_guide(self, publication):
        """Attend que le guide écoute le sujet ; False s'il n'est pas là après le délai."""
        fin = time.monotonic() + DELAI_DECOUVERTE_S
        while publication.get_subscription_count() == 0:
            if time.monotonic() > fin:
                return False
            self.tourner(0.1)
        return True

    def fermer(self):
        self.noeud.destroy_node()
        self.rclpy.try_shutdown()


def guide_absent():
    print('Le guide ne répond pas. Lancez d\'abord la navigation, par exemple :\n'
          '  g1-guide navigation --lieu demo --etage rdc --simu', file=sys.stderr)
    return 1


def aller(client, cible, suivre=True, accompagner=False, retour=True):
    if not client.attendre_guide(client.pub_aller):
        return guide_absent()
    client.tourner(0.3)
    avant = (client.etat or {}).get('cible')
    client.evenements.clear()
    client.pub_aller.publish(client.String(data=demande_aller(cible, accompagner, retour)))
    print(f'Envoyé : aller à « {cible} »' + (' en accompagnant le visiteur' if accompagner else '')
          + ('' if retour else ', sans retour au point principal'))
    if not suivre:
        client.tourner(0.3)      # laisse le temps au message de partir
        return 0
    dernier = None
    try:
        while True:
            client.tourner(0.2)
            etat = client.etat
            while client.evenements:          # les messages au visiteur (vague 4)
                print(f'\n  « {client.evenements.pop(0).get("texte")} »', end='', flush=True)
            # On attend un état qui concerne cette cible (le guide traduit les alias en id)
            if etat is None or not (etat.get('cible') == cible.strip()
                                    or etat.get('cible') not in (avant, None)):
                continue
            texte = texte_etat(etat)
            # Une ligne à chaque changement d'état, et la distance restante au fil de l'eau
            if dernier is None or etat['etat'] != dernier:
                print(f'\n{texte}', end='', flush=True)
                dernier = etat['etat']
            else:
                print(f'\r{texte}   ', end='', flush=True)
            if etat['etat'] in ('arrive', 'echec'):
                print()
                return 0 if etat['etat'] == 'arrive' else 1
    except KeyboardInterrupt:
        print('\nAffichage arrêté ; le robot continue. Pour l\'arrêter : g1-guide stop')
        return 0


def stop(client):
    if not client.attendre_guide(client.pub_stop):
        return guide_absent()
    client.pub_stop.publish(client.Empty())
    client.tourner(0.3)      # laisse le temps au message de partir
    print('Arrêt envoyé.')
    return 0


def afficher_etat(client):
    fin = time.monotonic() + DELAI_DECOUVERTE_S
    while client.etat is None and time.monotonic() < fin:
        client.tourner(0.2)
    if client.etat is None:
        return guide_absent()
    print(texte_etat(client.etat))
    return 0


def main(argv=None):
    p = Analyseur(prog='g1-guide', description='Navigation du guide de l\'Atelier G1.')
    sous = p.add_subparsers(dest='action', required=True, metavar='navigation|aller|stop|etat',
                            parser_class=Analyseur)
    nav = sous.add_parser('navigation', help='lance Nav2, le routeur et le guide')
    nav.add_argument('--lieu', required=True, help='dossier du lieu, ou id seul (ex. demo)')
    nav.add_argument('--etage', required=True, help='id de l\'étage (ex. rdc)')
    nav.add_argument('--simu', action='store_true', help='simulation Gazebo (temps simulé)')
    nav.add_argument('--moteur', default='nav2', choices=['nav2', 'unitree'],
                     help='nav2 (défaut) ou unitree (commande 1102 du robot)')
    nav.add_argument('--localisation', choices=['simu', 'unitree', 'amcl', 'externe'],
                     help='simu (défaut avec --simu), unitree (défaut sinon : repérage par la '
                          'relocalisation d\'Unitree), amcl (secours : carte et LiDAR), externe')
    nav.add_argument('--pont', default='auto', choices=['auto', 'oui', 'non'],
                     help='pont /cmd_vel → ordres de marche du robot (auto : avec Nav2, sauf en '
                          'simulation)')
    nav.add_argument('--vitesse-max', metavar='M_PAR_S',
                     help='premiers essais : vitesse maximale en m/s (ex. 0.2, au moins 0,2), '
                          'les plafonds du pont et Nav2 baissent dans la même proportion '
                          '(défaut : $G1_VITESSE_MAX, sinon 0,4 / 0,25 / 0,6)')
    nav.add_argument('--sans-personnes', action='store_true',
                     help='sans détecteur de personnes au LiDAR : le guide n\'accompagne pas le '
                          'visiteur et n\'attend pas les passants')
    va = sous.add_parser('aller', help='envoie le robot vers une salle ou un nœud')
    va.add_argument('cible', help='id de la salle ou du nœud (ex. b204, accueil)')
    va.add_argument('--sans-suivre', action='store_true',
                    help='rend la main tout de suite, sans afficher le trajet')
    va.add_argument('--accompagner', action='store_true',
                    help='le robot suit le visiteur : il ralentit ou l\'attend s\'il traîne')
    va.add_argument('--sans-retour', action='store_true',
                    help='le robot reste à destination (pas de retour seul au point principal)')
    sous.add_parser('stop', help='arrête le robot tout de suite')
    sous.add_parser('etat', help='affiche l\'état du guide')
    args = p.parse_args(argv)

    if args.action == 'navigation':
        vitesse = getattr(args, 'vitesse_max', None) \
            or os.environ.get('G1_VITESSE_MAX', '').strip()
        refus = refus_vitesse_max(vitesse) if vitesse else None
        if refus:
            print(f'g1-guide : {refus}', file=sys.stderr)
            return 2
        commande = commande_navigation(args)
        print(' '.join(commande))
        os.execvp(commande[0], commande)     # remplace ce processus : ne revient pas
        return 0

    client = Client()
    try:
        if args.action == 'aller':
            return aller(client, args.cible, not args.sans_suivre, args.accompagner,
                         not args.sans_retour)
        if args.action == 'stop':
            return stop(client)
        return afficher_etat(client)
    finally:
        client.fermer()


if __name__ == '__main__':
    sys.exit(main())
