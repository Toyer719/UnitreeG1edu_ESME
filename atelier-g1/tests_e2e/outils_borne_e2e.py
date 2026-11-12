#!/usr/bin/env python3
"""Outils du critère 39, la borne visiteur (section 13.9 du plan) : agent Borne et orchestrateur.

  outils_borne_e2e.py preparer --lieu ID
      sur la COPIE du demo : la salle vie_scolaire cachée de la borne (étiquette hors_borne), demo.yaml avec un
      code opérateur (4826), les personnalités d'exemple ;
  outils_borne_e2e.py critere-39 --api URL --lieu ID [--captures DOSSIER]
      le vrai nœud accueil (g1-accueil), lancé par l'outil, et un faux guide (FauxGuide : /guide/etat, TF map →
      base_link, trajets joués vite) dans le domaine du test ; Firefox sans fenêtre, la borne dans un cadre de
      390 × 844 puis 1024 × 768 :
        1. la page ne défile pas, chaque carte fait 64 px au moins et s'amène entière à l'écran, les salles du demo
           sauf l'accueil et la salle cachée, aucun jargon, window.erreursBorne vide ;
        2. une salle touchée → confirmation → /accueil/choix {salle, source: borne} ; cinq appuis rapides → un
           seul choix ; puis suivez_moi avec la distance, arrivee, retour, salles d'après /accueil/etat ; occupe et
           pause : cartes inactives et le message ;
        3. un /voix/son → [data-role=borne-son] charge GET /api/voix/son/<id> ;
        4. le code opérateur : faux → refusé ; bon → seulement pause, reprendre et ramener, qui envoient
           /accueil/commande (source operateur) ; cinq faux → 429 ;
        5. la garde : depuis l'adresse réseau du PC (l'Atelier écoute 0.0.0.0), /borne et /api/borne/etat
           répondent, /, /api/lieux, /api/arret/debloquer, /api/guide/aller (403 en français) et /ws/etat (fermé)
           sont refusés ; sans adresse réseau, la même chose par TestClient(client=…) ;
        6. l'Atelier, Équipe › Démo › Borne, montre [data-role=adresse-borne] ;
        7. /accueil/etat et /accueil/evenement conformes tout du long, jamais d'erreur 500, le nœud s'arrête
           (événement arretee).
Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi), 77 en attente (Firefox ou g1_accueil absent).
"""
import argparse
import json
import math
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import wave

ICI = Path(__file__).resolve().parent
RACINE = ICI.parent
sys.path.insert(0, str(RACINE))

EN_ATTENTE = 77
PREFIXE = 'borne'
TAILLES = {'telephone': (390, 844), 'tablette': (1024, 768)}
CODE = '4826'
CACHEE = 'vie_scolaire'
CODES_HTTP = []


class Echec(Exception):
    pass


class EnAttente(Exception):
    pass


def dire(texte):
    print(f'[{PREFIXE}] {texte}', flush=True)


def ok(texte):
    print(f'[{PREFIXE}] ok : {texte}', flush=True)


def verifier(condition, message):
    if not condition:
        raise Echec(message)


def appel(api, methode, chemin, corps=None, entetes=None, source=None, delai=20):
    """(code HTTP, JSON) d'un appel à l'API ; source : adresse locale d'où partir (ex. 127.0.0.2)."""
    donnees = None if corps is None else json.dumps(corps).encode()
    r = urllib.request.Request(api + chemin, data=donnees, method=methode,
                               headers=dict({'Content-Type': 'application/json'}, **(entetes or {})))
    ouvreur = urllib.request.build_opener(_SourceHandler(source)) if source else urllib.request.build_opener()
    try:
        with ouvreur.open(r, timeout=delai) as reponse:
            code, texte = reponse.status, reponse.read()
    except urllib.error.HTTPError as e:
        code, texte = e.code, e.read()
    CODES_HTTP.append((methode, chemin, code))
    try:
        return code, json.loads(texte or b'null')
    except ValueError:
        return code, {'detail': texte.decode('utf-8', 'replace')}


class _SourceHandler(urllib.request.HTTPHandler):
    """Les demandes partent d'une adresse locale choisie (un autre client pour le serveur)."""

    def __init__(self, source):
        super().__init__()
        self.source = source

    def http_open(self, req):
        import http.client
        source = self.source
        return self.do_open(lambda hote, **kw: http.client.HTTPConnection(hote, source_address=(source, 0), **kw),
                            req)


def pose_des_salles(lieu):
    from atelier import chemin_lieu
    from atelier.lieu import charger_salles
    from atelier.lieu.principal import point_principal
    dossier = chemin_lieu(lieu)
    salles = {s.id: s for s in charger_salles(dossier)}
    p = point_principal(dossier)
    return salles, p


# ---------------------------------------------------------------- préparation de la copie

def preparer(args):
    from atelier import chemin_lieu
    from atelier.lieu import accueil as A
    from atelier.lieu import charger_salles, enregistrer_salles
    from atelier.lieu import equipe as E
    dossier = chemin_lieu(args.lieu)
    verifier(dossier.resolve() != (RACINE / 'lieux' / 'demo').resolve(), 'jamais dans lieux/demo : une copie')
    salles = charger_salles(dossier)
    for s in salles:
        if s.id == CACHEE:
            s.etiquettes = list(s.etiquettes or []) + [A.ETIQUETTE_HORS_BORNE]
    enregistrer_salles(dossier, salles)
    A.enregistrer_demo(dossier, {'version': 1, 'borne': {'code_operateur': CODE}, 'voix': {'sortie': 'borne'}})
    E.enregistrer_equipe(dossier, 'personnalites', E.exemple_equipe('personnalites'))
    dire(f'copie préparée : {CACHEE} cachée, code opérateur, personnalités d\'exemple')
    return 0


# ---------------------------------------------------------------- le faux guide et l'observateur

class FauxGuide:
    """Un faux guide (comme celui de la vague 4) et la position du robot, plus l'écoute de la démo."""

    VITESSE = 3.0           # m/s : les trajets sont joués vite

    def __init__(self, salles, principal):
        import rclpy
        from rclpy.executors import SingleThreadedExecutor
        from rclpy.qos import QoSProfile, ReliabilityPolicy
        from std_msgs.msg import Empty, String
        import tf2_ros
        from atelier.lieu import valider_message
        self.rclpy, self.String, self.valider = rclpy, String, valider_message
        self.salles, self.principal = salles, principal
        self.contexte = rclpy.Context()
        rclpy.init(context=self.contexte)
        self.noeud = rclpy.create_node('e2e_faux_guide_borne', context=self.contexte)
        self.verrou = threading.RLock()
        self.recus = []
        self.non_conformes = []
        p = principal.pose
        self.pose = [p.x, p.y, p.theta]
        self.guide = {'version': 1, 'etat': 'attente', 'cible': None, 'reste_m': None, 'itineraire': [],
                      'mission': None, 'actif': False}
        self.trajet = None            # (but (x, y), cible, mission, retour, fin du séjour)
        n = self.noeud
        self.pub_etat = n.create_publisher(String, '/guide/etat', 10)
        self.pub_evenement = n.create_publisher(String, '/guide/evenement', 10)
        self.pub_commande = n.create_publisher(String, '/accueil/commande', 10)
        self.pub_son = n.create_publisher(String, '/voix/son', 10)
        self.tf = tf2_ros.TransformBroadcaster(n)
        fiable = QoSProfile(depth=50, reliability=ReliabilityPolicy.RELIABLE)
        for sujet in ('/accueil/etat', '/accueil/evenement', '/accueil/choix', '/accueil/commande', '/robot/dire'):
            n.create_subscription(String, sujet, self._recepteur(sujet), fiable)
        n.create_subscription(String, '/guide/aller', self._aller, fiable)
        n.create_subscription(Empty, '/guide/stop', self._stop, fiable)
        n.create_timer(0.1, self._pas)
        self.executeur = SingleThreadedExecutor(context=self.contexte)
        self.executeur.add_node(n)
        self._fin = threading.Event()
        self._fil = threading.Thread(target=self._tourner, daemon=True)
        self._fil.start()

    def _tourner(self):
        while not self._fin.is_set() and self.contexte.ok():
            self.executeur.spin_once(timeout_sec=0.05)

    SCHEMAS = {'/accueil/etat': 'etat_demo', '/accueil/evenement': 'evenement_demo', '/accueil/choix': 'choix_accueil',
               '/accueil/commande': 'commande_accueil', '/robot/dire': 'robot_dire', '/guide/aller': 'demande_guide'}

    def _recepteur(self, sujet):
        def recevoir(m):
            try:
                d = json.loads(m.data)
            except ValueError:
                self.non_conformes.append((sujet, m.data[:200]))
                return
            erreurs = self.valider(self.SCHEMAS[sujet], d)
            if erreurs:
                self.non_conformes.append((sujet, erreurs[:2]))
            with self.verrou:
                self.recus.append((time.monotonic(), sujet, d))
        return recevoir

    def messages(self, sujet, depuis=0.0):
        with self.verrou:
            return [d for t, s, d in self.recus if s == sujet and t >= depuis]

    def etat_demo(self):
        m = self.messages('/accueil/etat')
        return m[-1] if m else {}

    def attendre(self, condition, delai, message, pas=0.05):
        fin = time.monotonic() + delai
        while time.monotonic() < fin:
            v = condition()
            if v:
                return v
            time.sleep(pas)
        raise Echec(f'{message} (démo : {self.etat_demo().get("etat")}, {self.etat_demo().get("message")})')

    def evenement(self, code, **plus):
        from atelier.lieu.comportement import evenement
        m = evenement(code, salle=plus.pop('salle', None), nom=plus.pop('nom', None), mission=plus.pop('mission', None))
        m.update(plus)
        self.pub_evenement.publish(self.String(data=json.dumps(m, ensure_ascii=False)))

    def changer(self, etat, **champs):
        with self.verrou:
            self.guide = dict(self.guide, etat=etat, **champs)

    # ---- /guide/aller : le trajet joué vite (visite, puis retour automatique si demandé)
    def _aller(self, m):
        from atelier.lieu.comportement import lire_demande_aller
        try:
            d = lire_demande_aller(m.data)
        except ValueError:
            return
        brut = json.loads(m.data) if m.data.startswith('{') else {'cible': m.data}
        if self.valider('demande_guide', brut):
            self.non_conformes.append(('/guide/aller', brut))
        with self.verrou:
            self.recus.append((time.monotonic(), '/guide/aller', brut))
            cible = self.principal.id if d['cible'] == 'principal' else d['cible']
            s = self.salles.get(cible)
            if s is None:
                return
            self.trajet = {'but': (s.pose.x, s.pose.y, s.pose.theta), 'cible': cible, 'mission': 'visite',
                           'retour': d['retour'] is not False and cible != self.principal.id, 'sejour': None}
            self.changer('en_route', cible=cible, mission='visite', actif=True, accompagner=bool(d['accompagner']))
        self.evenement('depart', salle=cible, nom=s.nom, mission='visite')

    def visite_externe(self, cible):
        """Une visite demandée hors de la démo (« Y aller » de l'Atelier) : la démo est occupée."""
        s = self.salles[cible]
        with self.verrou:
            self.trajet = {'but': (s.pose.x, s.pose.y, s.pose.theta), 'cible': cible, 'mission': 'visite',
                           'retour': True, 'sejour': None}
            self.changer('en_route', cible=cible, mission='visite', actif=True)

    def _stop(self, _m):
        with self.verrou:
            actif = self.guide.get('actif')
            self.trajet = None
            self.changer('attente', cible=None, mission=None, actif=False, reste_m=None)
        if actif:
            self.evenement('arret')

    def _pas(self):
        with self.verrou:
            t = self.trajet
            if t is not None:
                bx, by, bth = t['but']
                dx, dy = bx - self.pose[0], by - self.pose[1]
                d = math.hypot(dx, dy)
                if t['sejour'] is None:
                    pas = self.VITESSE * 0.1
                    if d <= pas:
                        self.pose = [bx, by, bth]
                        if t['mission'] == 'retour':
                            self.trajet = None
                            self.changer('attente', cible=None, mission=None, actif=False, reste_m=None)
                            self._evenement_differe('retour_arrive', salle=self.principal.id, nom=self.principal.nom,
                                                    mission='retour')
                        elif t['retour']:
                            t['sejour'] = time.monotonic() + 2.0
                            self.changer('arrive', reste_m=0.0, actif=True)
                            self._evenement_differe('arrivee', salle=t['cible'], mission='visite')
                        else:
                            self.trajet = None
                            self.changer('arrive', reste_m=0.0, actif=False)
                    else:
                        self.pose = [self.pose[0] + dx / d * pas, self.pose[1] + dy / d * pas, math.atan2(dy, dx)]
                        self.changer(self.guide['etat'], reste_m=round(d, 2))
                elif time.monotonic() >= t['sejour']:
                    p = self.principal.pose
                    self.trajet = {'but': (p.x, p.y, p.theta), 'cible': self.principal.id, 'mission': 'retour',
                                   'retour': False, 'sejour': None}
                    self.changer('retour', cible=self.principal.id, mission='retour', actif=True)
                    self._evenement_differe('retour', salle=self.principal.id, mission='retour')
            guide = dict(self.guide)
            x, y, th = self.pose
        self.pub_etat.publish(self.String(data=json.dumps(guide)))
        from geometry_msgs.msg import TransformStamped
        tf = TransformStamped()
        tf.header.stamp = self.noeud.get_clock().now().to_msg()
        tf.header.frame_id, tf.child_frame_id = 'map', 'base_link'
        tf.transform.translation.x, tf.transform.translation.y = float(x), float(y)
        tf.transform.rotation.z, tf.transform.rotation.w = math.sin(th / 2), math.cos(th / 2)
        self.tf.sendTransform(tf)

    def _evenement_differe(self, code, **plus):
        threading.Thread(target=lambda: self.evenement(code, **plus), daemon=True).start()

    def deplacer(self, x, y, theta):
        with self.verrou:
            self.pose = [x, y, theta]

    def commande(self, action, source='test'):
        from atelier.lieu import accueil as A
        ident = f'e2e-{action}-{int(time.monotonic() * 1000)}'
        self.pub_commande.publish(self.String(data=json.dumps(A.message_commande(action, source, ident))))
        return self.attendre(lambda: [e for e in self.messages('/accueil/evenement') if e.get('id') == ident], 3.0,
                             f'pas de réponse à la commande {action}')[0]

    def son(self, ident, texte):
        from atelier.lieu.voix import dossier_sons
        dossier = dossier_sons()
        dossier.mkdir(parents=True, exist_ok=True)
        with wave.open(str(dossier / f'{ident}.wav'), 'wb') as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(16000)
            w.writeframes(b'\x00\x00' * 8000)
        m = {'version': 1, 'id': ident, 'texte': texte, 'duree_s': 0.5, 'url': f'/api/voix/son/{ident}',
             'priorite': 'normale', 'source': 'test', 'frequence_hz': 16000}
        self.pub_son.publish(self.String(data=json.dumps(m, ensure_ascii=False)))

    def fermer(self):
        self._fin.set()
        self._fil.join(timeout=2.0)
        self.executeur.shutdown()
        self.noeud.destroy_node()
        self.rclpy.try_shutdown(context=self.contexte)


# ---------------------------------------------------------------- le nœud accueil, lancé par l'outil

class NoeudAccueil:
    def __init__(self, lieu, journal):
        self.journal = open(journal, 'w', encoding='utf-8')
        arguments = ['g1-accueil', '--lieu', lieu, '--etage', 'rdc', '--', '--ros-args', '-p', 'suivre_pont:=false',
                     '-p', 'delai_entre_visiteurs_s:=1.0', '-p', 'delai_choix_s:=120.0']
        self.p = subprocess.Popen(arguments, stdout=self.journal, stderr=subprocess.STDOUT, start_new_session=True)

    def arreter(self):
        if self.p.poll() is None:
            os.killpg(self.p.pid, signal.SIGINT)
            try:
                self.p.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(self.p.pid, signal.SIGKILL)
                self.p.wait()
        self.journal.close()
        return self.p.returncode


# ---------------------------------------------------------------- Firefox

def texte(nav, role):
    return nav.js("const e = document.querySelector('[data-role=' + arguments[0] + ']'); "
                  "return e ? e.textContent.replace(/\\u00a0/g, ' ').replace(/\\u2011/g, '-') : null", role)


def parcours_borne(nav, api, g, nom, largeur, hauteur, captures, attendues, salle, autre):
    from atelier.tests import test_borne_communs as C
    C.ouvrir_borne_cadre(nav, api, largeur, hauteur)
    C.attendre_ecran(nav, 'salles', 15)
    m = nav.js(C.MESURE_BORNE)
    verifier(m['fautes'] == [] and m['erreurs'] == [], f'{nom} : {m["fautes"]} {m["erreurs"]}')
    verifier(m['taille'] == [largeur, hauteur], f'{nom} : cadre de {m["taille"]}')
    verifier(m['cartes'] == attendues, f'{nom} : salles {m["cartes"]}, attendues {attendues}')
    C.capture_cadre(nav, captures / f'borne_{nom}_1_salles.png')
    ok(f'{nom} {largeur} × {hauteur} : ne défile pas, {len(attendues)} cartes de 64 px au moins entières, ni l\'accueil '
       f'ni « {CACHEE} » (cachée), aucun jargon, aucune erreur')
    # une salle, la confirmation, cinq appuis rapides
    t0 = time.monotonic()
    nav.js("document.querySelector('[data-salle=' + arguments[0] + ']').click()", salle)
    nav.attendre("return !document.querySelector('[data-role=confirmation-borne]').hidden", message='confirmation')
    verifier(texte(nav, 'salle-confirmee').startswith('« '), 'confirmation sans le nom de la salle')
    C.capture_cadre(nav, captures / f'borne_{nom}_2_confirmation.png')
    nav.js("const o = document.querySelector('[data-role=confirmer-salle]'); for (let i = 0; i < 5; i++) o.click();")
    g.attendre(lambda: g.messages('/accueil/choix', t0), 3.0, 'pas de /accueil/choix')
    time.sleep(1.5)
    choix = g.messages('/accueil/choix', t0)
    verifier(len(choix) == 1 and choix[0]['salle'] == salle and choix[0]['source'] == 'borne',
             f'{nom} : cinq appuis rapides → {len(choix)} choix ({choix})')
    aller = g.attendre(lambda: g.messages('/guide/aller', t0), 3.0, 'pas de /guide/aller')
    verifier(aller[0]['cible'] == salle and aller[0].get('source') == 'accueil', f'/guide/aller {aller[0]}')
    ok(f'{nom} : salle touchée → confirmation → un seul /accueil/choix ({salle}, borne) pour cinq appuis rapides')
    # la visite suivie par la borne
    C.attendre_ecran(nav, 'suivez_moi', 10)
    detail = nav.attendre("const d = document.querySelector('[data-role=borne-detail]').textContent; "
                          "return /Encore \\d+ m jusqu/.test(d.replace(/\\u00a0/g, ' ')) ? d : null", delai=10,
                          message='la distance restante')
    C.capture_cadre(nav, captures / f'borne_{nom}_3_suivez_moi.png')
    C.attendre_ecran(nav, 'arrivee', 20)
    C.capture_cadre(nav, captures / f'borne_{nom}_4_arrivee.png')
    C.attendre_ecran(nav, 'retour', 10)
    C.capture_cadre(nav, captures / f'borne_{nom}_5_retour.png')
    C.attendre_ecran(nav, 'salles', 30)
    ok(f'{nom} : suivez_moi (« {detail.strip()} »), arrivee, retour, salles, d\'après /accueil/etat')
    # occupé, puis pause : cartes inactives, le message
    g.visite_externe(autre)
    C.attendre_ecran(nav, 'occupe', 10)
    verifier(nav.js("return Array.from(document.querySelectorAll('[data-salle]')).every((c) => c.disabled)"),
             f'{nom} : cartes actives pendant « occupé »')
    titre_occupe = texte(nav, 'borne-titre')
    C.capture_cadre(nav, captures / f'borne_{nom}_6_occupe.png')
    C.attendre_ecran(nav, 'salles', 40)
    r = g.commande('pause')
    verifier(r['code'] == 'commande_acceptee', f'pause : {r}')
    C.attendre_ecran(nav, 'pause', 10)
    verifier(nav.js("return Array.from(document.querySelectorAll('[data-salle]')).every((c) => c.disabled)"),
             f'{nom} : cartes actives pendant la pause')
    titre_pause = texte(nav, 'borne-titre')
    C.capture_cadre(nav, captures / f'borne_{nom}_7_pause.png')
    r = g.commande('reprendre')
    verifier(r['code'] == 'commande_acceptee', f'reprendre : {r}')
    C.attendre_ecran(nav, 'salles', 10)
    verifier(nav.js('return window.erreursBorne') == [], f'{nom} : erreurs de la page')
    ok(f'{nom} : occupé (« {titre_occupe} ») et pause (« {titre_pause} ») : cartes inactives et le message')


def operateur_navigateur(nav, api, g, captures):
    from atelier.tests import test_borne_communs as C
    C.ouvrir_borne_cadre(nav, api, *TAILLES['tablette'])
    C.attendre_ecran(nav, 'salles', 15)
    nav.attendre("return !document.querySelector('[data-role=borne-operateur]').hidden", message='bouton opérateur')
    nav.js("document.querySelector('[data-role=borne-operateur]').click()")
    nav.attendre("return !document.querySelector('[data-role=operateur-code]').hidden", message='clavier du code')

    def taper(code):
        nav.js("for (const c of arguments[0]) document.querySelector('[data-touche=\"' + c + '\"]').click();"
               "document.querySelector('[data-touche=valider]').click();", code)
    taper('0000')
    nav.attendre("const m = document.querySelector('[data-role=code-message]'); return !m.hidden && m.textContent",
                 message='code faux')
    verifier(texte(nav, 'code-message') == 'Code faux.', f'code faux : {texte(nav, "code-message")}')
    time.sleep(0.7)
    taper(CODE)
    nav.attendre("return !document.querySelector('[data-role=operateur-actions]').hidden", message='mode opérateur')
    actions = nav.js("return Array.from(document.querySelectorAll('[data-role=operateur-actions] [data-action]'))"
                     ".map((b) => b.dataset.action)")
    verifier(actions == ['pause', 'reprendre', 'ramener'], f'actions de l\'opérateur : {actions}')
    C.capture_cadre(nav, captures / 'borne_tablette_8_operateur.png')
    vus = []
    for action, preparer in (('pause', None), ('ramener', 'loin'), ('reprendre', None)):
        if preparer == 'loin':
            s = g.salles['amphi'].pose
            g.deplacer(s.x, s.y, s.theta)           # le robot loin de l'accueil : « Ramener » devient possible
        t0 = time.monotonic()
        nav.attendre("const b = document.querySelector('[data-action=' + arguments[0] + ']'); return b && !b.disabled",
                     action, delai=10, message=f'« {action} » possible')
        nav.js("document.querySelector('[data-action=' + arguments[0] + ']').click()", action)
        c = g.attendre(lambda: [x for x in g.messages('/accueil/commande', t0) if x['action'] == action], 5.0,
                       f'« {action} » de l\'opérateur : pas de /accueil/commande')[0]
        verifier(c['source'] == 'operateur', f'« {action} » : source {c["source"]}')
        vus.append(action)
        if action == 'ramener':
            g.attendre(lambda: g.etat_demo().get('etat') == 'attente', 30, 'ramener : la démo ne revient pas en attente')
            r = g.commande('pause')
            verifier(r['code'] == 'commande_acceptee', f'pause : {r}')
    nav.js("document.querySelector('[data-role=fermer-operateur]').click()")
    g.attendre(lambda: g.etat_demo().get('etat') == 'attente', 10, 'reprendre : pas d\'attente')
    ok(f'mode opérateur : code faux refusé ; bon code → seulement {", ".join(actions)} ; {", ".join(vus)} envoient '
       '/accueil/commande (source operateur)')


def adresse_atelier(nav, api, lieu, captures):
    from atelier.tests.test_serveur_navigateur import ouvrir_espace
    from atelier.tests.test_borne_communs import sortir_du_cadre
    try:
        sortir_du_cadre(nav)
    except RuntimeError:
        pass
    nav.taille(1600, 1000)
    ouvrir_espace(nav, api, mode='simu', lieu=lieu)
    nav.commande('demo.borne')
    adresse = nav.attendre("const e = document.querySelector('[data-role=adresse-borne]'); "
                           "return e && /^http:\\/\\/[0-9.]+:[0-9]+\\/borne$/.test(e.textContent) ? e.textContent : null",
                           delai=20, message='[data-role=adresse-borne]')
    nav.capture(str(captures / 'atelier_demo_borne.png'))
    verifier(nav.js('return window.erreursAtelier') == [], 'erreurs dans l\'Atelier')
    return adresse


# ---------------------------------------------------------------- la garde, depuis le réseau

def adresse_reseau_du_pc():
    """Une adresse IPv4 du PC hors de la boucle locale, ou None."""
    from atelier.serveur.routes.borne import _adresses_du_pc
    ips = _adresses_du_pc()
    return ips[0] if ips else None


def garde(api, lieu):
    port = api.rsplit(':', 1)[1]
    ip = adresse_reseau_du_pc()
    refuses = (('GET', '/'), ('GET', '/api/lieux'), ('POST', '/api/arret/debloquer'), ('POST', '/api/guide/aller'))
    if ip is not None:
        base = f'http://{ip}:{port}'
        for chemin in ('/borne', '/api/borne/etat'):
            code, _ = appel(base, 'GET', chemin)
            verifier(code == 200, f'garde : {chemin} depuis {ip} : {code}')
        for methode, chemin in refuses:
            code, r = appel(base, methode, chemin, {} if methode == 'POST' else None)
            verifier(code == 403 and 'seule la borne' in (r or {}).get('detail', ''),
                     f'garde : {methode} {chemin} depuis {ip} : {code} {r}')
        ws = _websocket_ferme(ip, int(port), '/ws/etat')
        verifier(ws, 'garde : /ws/etat ouvert depuis le réseau')
        return f'depuis {ip} (adresse du PC)'
    # sans adresse réseau : la même chose dans le serveur, par TestClient(client=…)
    os.environ['ATELIER_HOTE'] = '0.0.0.0'
    from fastapi.testclient import TestClient
    from atelier.serveur.main import creer_app
    with TestClient(creer_app(ros=False), client=('192.168.1.20', 50000)) as c:
        for chemin in ('/borne', '/api/borne/etat'):
            verifier(c.get(chemin).status_code == 200, f'garde (TestClient) : {chemin}')
        for methode, chemin in refuses:
            r = getattr(c, methode.lower())(chemin)
            verifier(r.status_code == 403 and 'seule la borne' in r.json()['detail'], f'garde (TestClient) : {chemin}')
        from starlette.websockets import WebSocketDisconnect
        try:
            with c.websocket_connect('/ws/etat') as w:
                w.receive_json()
            raise Echec('garde (TestClient) : /ws/etat ouvert')
        except WebSocketDisconnect:
            pass
    return 'par TestClient (le PC n\'a pas d\'adresse réseau)'


def _websocket_ferme(hote, port, chemin):
    """Vrai si le serveur refuse le WebSocket (fermeture 4403, ou pas de 101)."""
    import base64
    cle = base64.b64encode(os.urandom(16)).decode()
    with socket.create_connection((hote, port), timeout=5) as s:
        s.sendall((f'GET {chemin} HTTP/1.1\r\nHost: {hote}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n'
                   f'Sec-WebSocket-Key: {cle}\r\nSec-WebSocket-Version: 13\r\n\r\n').encode())
        reponse = s.recv(4096)
        if not reponse.startswith(b'HTTP/1.1 101'):
            return True
        s.settimeout(5)
        trame = s.recv(4096)
        return len(trame) >= 4 and trame[0] & 0x0F == 0x8 and int.from_bytes(trame[2:4], 'big') == 4403


# ---------------------------------------------------------------- le critère

def critere_39(args):
    try:
        import pytest  # noqa: F401  (demarrer_navigateur signale un Firefox absent par pytest.skip)
        from atelier.tests.test_borne_communs import preparer_firefox
        from atelier.tests.test_serveur_navigateur import arreter_navigateur, demarrer_navigateur
    except ImportError as e:
        raise EnAttente(f'outils du navigateur introuvables : {e}') from None
    from atelier import chemin_lieu
    from atelier.lieu import accueil as A
    from atelier.lieu import charger_salles
    captures = Path(args.captures)
    captures.mkdir(parents=True, exist_ok=True)
    salles, principal = pose_des_salles(args.lieu)
    attendues = [s['id'] for s in A.salles_de_la_borne(charger_salles(chemin_lieu(args.lieu)), principal.id, 'rdc')]
    g = FauxGuide(salles, principal)
    noeud = NoeudAccueil(str(chemin_lieu(args.lieu)), Path(args.journaux) / 'accueil.log')
    preparer_firefox()
    gecko = nav = None
    try:
        g.attendre(lambda: g.etat_demo().get('etat') == 'attente', 30, 'le nœud accueil n\'est pas en attente')
        ok(f'nœud accueil lancé, démo en attente ({len(attendues)} salles à la borne)')
        try:
            gecko, nav = demarrer_navigateur()
        except BaseException as e:      # noqa: BLE001 : pytest.skip (Firefox absent)
            raise EnAttente(f'Firefox sans fenêtre ne démarre pas : {e}') from None
        for (nom, (l, h)), salle, autre in zip(TAILLES.items(), ('b204', 'cdi'), ('cdi', 'amphi')):
            parcours_borne(nav, args.api, g, nom, l, h, captures, attendues, salle, autre)
        # le son de la sortie borne
        from atelier.tests import test_borne_communs as C
        C.ouvrir_borne_cadre(nav, args.api, *TAILLES['telephone'])
        C.attendre_ecran(nav, 'salles', 15)
        time.sleep(0.5)
        ident = f's-e2e-{int(time.time())}'
        g.son(ident, 'Bonjour !')
        src = nav.attendre("const a = document.querySelector('[data-role=borne-son]'); const s = a && "
                           "a.getAttribute('src'); return s && s.indexOf(arguments[0]) >= 0 ? s : null", ident,
                           delai=10, message='le son de la borne')
        verifier(src == f'/api/voix/son/{ident}', f'son : {src}')
        code, _ = appel(args.api, 'GET', f'/api/voix/son/{ident}')
        ok(f'/voix/son → [data-role=borne-son] charge {src} (GET : {code}'
           + (', route de la voix pas encore faite' if code == 501 else '') + ')')
        operateur_navigateur(nav, args.api, g, captures)
        # cinq codes faux → 429 (le bon code ensuite d'un autre client)
        codes = [appel(args.api, 'POST', '/api/borne/operateur', {'code': '1111'})[0] for _ in range(5)]
        verifier(codes == [403, 403, 403, 403, 429], f'cinq codes faux : {codes}')
        code, r = appel(args.api, 'POST', '/api/borne/operateur', {'code': CODE}, source='127.0.0.2')
        verifier(code == 200 and r.get('jeton'), f'bon code depuis un autre client : {code} {r}')
        code, _ = appel(args.api, 'POST', '/api/borne/operateur/debloquer', {}, {A.ENTETE_JETON_BORNE: r['jeton']},
                        source='127.0.0.2')
        verifier(code == 404, f'« debloquer » avec le jeton : {code} (404 attendu)')
        ok('cinq codes faux : 403, 403, 403, 403, 429 ; une autre action que pause, reprendre, ramener : 404')
        ok('garde de la borne : /borne et /api/borne/etat permis, /, /api/lieux, /api/arret/debloquer, '
           f'/api/guide/aller (403 en français) et /ws/etat refusés, {garde(args.api, args.lieu)}')
        adresse = adresse_atelier(nav, args.api, args.lieu, captures)
        ok(f'Équipe › Démo › Borne : [data-role=adresse-borne] = {adresse}')
        verifier(not g.non_conformes, f'messages non conformes : {g.non_conformes[:3]}')
        etats = g.messages('/accueil/etat')
        ok(f'{len(etats)} /accueil/etat et {len(g.messages("/accueil/evenement"))} /accueil/evenement, tous conformes')
    finally:
        if nav is not None:
            arreter_navigateur(gecko, nav)
        t_arret = time.monotonic()
        code_noeud = noeud.arreter()
        time.sleep(0.5)
        arretee = [e for e in g.messages('/accueil/evenement', t_arret - 0.5) if e['code'] == 'arretee']
        g.fermer()
    verifier(code_noeud == 0 and arretee, f'arrêt du nœud accueil : code {code_noeud}, arretee {bool(arretee)}')
    cinq_cents = [x for x in CODES_HTTP if x[2] >= 500 and x[2] != 501]
    verifier(not cinq_cents, f'erreurs 500 : {cinq_cents}')
    ok('nœud accueil arrêté (événement arretee), jamais d\'erreur 500')
    return 0


def main(argv=None):
    p = argparse.ArgumentParser(prog='outils_borne_e2e.py', description=__doc__.split('\n')[0])
    sous = p.add_subparsers(dest='commande', required=True)
    s = sous.add_parser('preparer')
    s.add_argument('--lieu', required=True)
    s = sous.add_parser('critere-39')
    s.add_argument('--api', required=True)
    s.add_argument('--lieu', required=True)
    s.add_argument('--captures', required=True)
    s.add_argument('--journaux', default='.')
    args = p.parse_args(argv)
    try:
        return {'preparer': preparer, 'critere-39': critere_39}[args.commande](args)
    except EnAttente as e:
        dire(f'EN ATTENTE : {e}')
        return EN_ATTENTE
    except Echec as e:
        dire(f'ÉCHEC : {e}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
