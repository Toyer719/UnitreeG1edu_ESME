"""
API HTTP et WebSocket du nœud pilotage (tornado), section 11.5 du plan.

Elle tourne dans le conteneur du Jetson (sur le PC en répétition) ; le serveur de l'Atelier la
joint par G1_PILOTAGE_URL (défaut http://127.0.0.1:8010). Sur le Wi-Fi, le jeton partagé
G1_PILOTAGE_JETON est exigé dans l'en-tête X-Jeton (401 sans lui) ; sans jeton configuré, seules
les connexions de la machine elle-même (127.0.0.1) sont acceptées.

  GET  /etat                        état du pilotage (schéma etat_pilotage)
  GET  /danses[?lire=1]             danses du robot (lire=1 : 7100 au robot ; sinon la dernière)
  GET  /gestes[?lire=1]             gestes d'Unitree (et la liste 7107 du robot avec lire=1)
  POST /maitre    {maitre: pilotage|guide, forcer?, par?}       prendre ou rendre la main
  POST /posture   {fsm, portique?, jeton?}                       7101 (1, 0 : confirmation double)
  POST /tache     {tache}                                        sport 7106 (saluer, serrer main)
  POST /geste     {action}                                       arm 7106
  POST /voix      {texte, voix?}   /volume {volume}   /led {r, g, b}
  POST /danse     {id, zone_libre}                               7101 550000 + id
  POST /choregraphie {choregraphie, zone_libre, vitesse?}        chorégraphie vérifiée, jouée
  POST /requete   {service, api_id, parametre, portique?, jeton?, zone_libre?}   mode avancé
  POST /arret     {par?}                                         ARRÊT, toujours permis
  WS   /joystick  {vx, vy, wz} toutes les 0,1 s ; {lacher: true} ;
                  reçoit {type: etat|refus|bienvenue}

Réponses en JSON, avec un « detail » en français. Codes : 200 fait ; 400 demande mal formée ;
401 jeton ; 403 interdit (rien n'est envoyé au robot) ; 409 verrou, activité en cours ou refus du
robot (code et message traduits) ; 422 chorégraphie fausse ; 428 confirmation demandée ; 504 le
robot ne répond pas.
"""
import hmac
import json
import math

from tornado import ioloop, web, websocket

from .logique import D

CORPS_MAX_OCTETS = 2 * 1024 * 1024
PERIODE_ETAT_WS_S = 0.5
ECART_REFUS_WS_S = 1.0
LOCALES = ('127.0.0.1', '::1', '::ffff:127.0.0.1')


class Refus(Exception):
    """Demande refusée avant d'arriver à la logique (corps illisible, champ manquant)."""

    def __init__(self, statut, detail):
        super().__init__(detail)
        self.statut = statut
        self.detail = detail


def entier(d, cle, quoi=None, defaut=None, obligatoire=True):
    """Champ entier d'un corps JSON ; Refus 400 en français sinon."""
    v = d.get(cle, defaut)
    if v is None and not obligatoire:
        return None
    if isinstance(v, float) and v.is_integer() and math.isfinite(v):
        v = int(v)
    if isinstance(v, bool) or not isinstance(v, int):
        raise Refus(400, f'« {cle} » doit être un nombre entier{f" ({quoi})" if quoi else ""}.')
    return v


def booleen(d, cle):
    v = d.get(cle, False)
    if not isinstance(v, bool):
        raise Refus(400, f'« {cle} » doit valoir true ou false.')
    return v


def refuser_non_fini(constante):
    """NaN, Infinity et -Infinity sont refusés dans les demandes (JSON strict)."""
    raise ValueError(f'nombre non fini : {constante}')


def autorise(requete, jeton):
    """Vrai si la requête porte le bon jeton, ou vient de la machine sans jeton configuré."""
    if jeton:
        recu = requete.headers.get(D.ENTETE_JETON, '')
        return hmac.compare_digest(recu.encode(), jeton.encode())
    return requete.remote_ip in LOCALES


class Base(web.RequestHandler):
    """Jeton, corps JSON et erreurs en français pour toutes les routes."""

    def initialize(self, coeur, jeton):
        self.coeur = coeur
        self.jeton = jeton

    def prepare(self):
        if not autorise(self.request, self.jeton):
            detail = ('Jeton du pilotage absent ou faux (en-tête X-Jeton) : donnez '
                      'G1_PILOTAGE_JETON à l\'Atelier.'
                      if self.jeton else 'Sans jeton (G1_PILOTAGE_JETON), le pilotage n\'accepte '
                                         'que la machine '
                      'elle-même (127.0.0.1).')
            self.repondre(401, {'detail': detail})
            self.finish()

    def set_default_headers(self):
        self.set_header('Content-Type', 'application/json; charset=utf-8')
        self.set_header('Cache-Control', 'no-store')

    def corps(self):
        if not self.request.body:
            return {}
        try:
            d = json.loads(self.request.body.decode('utf-8'), parse_constant=refuser_non_fini)
        except (ValueError, UnicodeDecodeError):
            raise Refus(400, 'Le corps de la demande n\'est pas du JSON valable (NaN et Infinity '
                             'sont interdits).') from None
        if not isinstance(d, dict):
            raise Refus(400, 'Le corps de la demande doit être un objet JSON.')
        return d

    def repondre(self, statut, corps):
        self.set_status(statut)
        self.write(json.dumps(corps, ensure_ascii=False, allow_nan=False, default=str))

    def write_error(self, statut, **kwargs):
        detail = {400: 'Demande mal formée.', 404: 'Adresse inconnue du nœud pilotage.',
                  405: 'Méthode non permise '
                       'ici.'}.get(statut, 'Erreur interne du nœud pilotage : voir son journal.')
        self.repondre(statut, {'detail': detail})

    async def executer(self, fonction, *args, **kwargs):
        """Lance une fonction bloquante (attente de la réponse du robot) dans un fil de travail."""
        return await ioloop.IOLoop.current().run_in_executor(None, lambda: fonction(*args,
                                                                                    **kwargs))

    async def faire(self, nom, *args, **kwargs):
        resultat = await self.executer(self.coeur.faire_et_attendre, nom, *args, **kwargs)
        corps = dict(resultat.corps)
        corps.setdefault('detail', 'Fait.')
        corps['etat'] = self.coeur.etat()
        self.repondre(resultat.statut, corps)

    async def post(self, *args):
        try:
            await self.traiter(self.corps())
        except Refus as r:
            self.repondre(r.statut, {'detail': r.detail})

    async def traiter(self, d):
        self.repondre(405, {'detail': f'Méthode POST non permise sur {self.request.path}.'})


class Etat(Base):
    def get(self):
        self.repondre(200, self.coeur.etat())


class Danses(Base):
    async def get(self):
        if self.get_argument('lire', '0') == '1':
            r = await self.executer(self.coeur.faire_et_attendre, 'lister_danses')
            if not r.ok:
                self.repondre(r.statut, dict(r.corps, detail='Liste des danses illisible : '
                                                             f'{r.corps["detail"]}'))
                return
        liste = self.coeur.logique.liste_danses()
        if liste is None:
            self.repondre(409, {'detail': 'La liste des danses n\'a pas encore été lue : « Lire '
                                          'la liste ».',
                                'danses': None})
            return
        self.repondre(200, {'danses': liste, 'interdites': list(D.DANSES_INTERDITES),
                            'detail': f'{len(liste)} danses dans le robot.'})


class Gestes(Base):
    async def get(self):
        robot = None
        if self.get_argument('lire', '0') == '1':
            r = await self.executer(self.coeur.faire_et_attendre, 'lister_gestes')
            robot = r.corps.get('data') if r.ok else None
        gestes = [{'id': n, 'nom': nom} for n, nom in D.GESTES_BRAS.items()]
        self.repondre(200, {'gestes': gestes, 'taches': [{'id': n, 'nom': nom} for n,
                                                         nom in D.TACHES_LOCO.items()],
                            'robot': robot})


class Maitre(Base):
    async def traiter(self, d):
        maitre = d.get('maitre')
        par = str(d.get('par') or 'atelier')[:60]
        if maitre == 'pilotage':
            r = await self.executer(self.coeur.prendre_main, forcer=booleen(d, 'forcer'), par=par)
        elif maitre == 'guide':
            r = await self.executer(self.coeur.faire, 'rendre_main', par=par)
        else:
            raise Refus(400, '« maitre » vaut pilotage (prendre la main) ou guide (la rendre).')
        self.repondre(r.statut, dict(r.corps, etat=self.coeur.etat()))


class Posture(Base):
    async def traiter(self, d):
        await self.faire('posture', entier(d, 'fsm', 'posture'), portique=booleen(d, 'portique'),
                         jeton=str(d.get('jeton') or '') or None)


class Tache(Base):
    async def traiter(self, d):
        await self.faire('tache', entier(d, 'tache', '0 à 3'))


class Geste(Base):
    async def traiter(self, d):
        await self.faire('geste', entier(d, 'action', 'numéro du geste'))


class Voix(Base):
    async def traiter(self, d):
        texte = d.get('texte')
        if not isinstance(texte, str) or not texte.strip():
            raise Refus(400, '« texte » : la phrase à dire.')
        await self.faire('voix', texte.strip(), entier(d, 'voix', 'speaker_id', defaut=0))


class Volume(Base):
    async def traiter(self, d):
        await self.faire('volume', entier(d, 'volume', '0 à 100'))


class Led(Base):
    async def traiter(self, d):
        r, g, b = (entier(d, c, '0 à 255') for c in 'rgb')
        await self.faire('led', r, g, b)


class Danse(Base):
    async def traiter(self, d):
        await self.faire('danser', entier(d, 'id', 'numéro de la '
                                                   'danse'), zone_libre=booleen(d, 'zone_libre'))


class Choregraphie(Base):
    async def traiter(self, d):
        choregraphie = d.get('choregraphie')
        if not isinstance(choregraphie, dict):
            raise Refus(400, '« choregraphie » : le contenu de la chorégraphie (objet JSON).')
        zone_libre = booleen(d, 'zone_libre')
        vitesse = d.get('vitesse', 1.0)
        if isinstance(vitesse, bool) or not isinstance(vitesse, (int, float)):
            raise Refus(400, '« vitesse » : la vitesse de lecture, de 0,25 à 1.')
        r = await self.executer(self.coeur.faire, 'jouer', choregraphie, zone_libre=zone_libre,
                                vitesse=float(vitesse))
        self.repondre(r.statut, dict(r.corps, etat=self.coeur.etat()))


class Requete(Base):
    async def traiter(self, d):
        service = d.get('service')
        if service not in ('sport', 'arm', 'voice'):
            raise Refus(403, f'Service « {service} » interdit : sport, arm ou voice seulement.')
        parametre = d.get('parametre', {})
        if not isinstance(parametre, (dict, str)):
            raise Refus(400, '« parametre » : un objet JSON, ou son texte.')
        await self.faire('requete', service, entier(d, 'api_id', 'numéro de la '
                                                                 'commande'), parametre,
                         portique=booleen(d, 'portique'), jeton=str(d.get('jeton') or '') or None,
                         zone_libre=booleen(d, 'zone_libre'))


class Arret(Base):
    async def traiter(self, d):
        r = await self.executer(self.coeur.faire, 'arret', par=str(d.get('par') or 'atelier')[:60])
        self.repondre(r.statut, dict(r.corps, etat=self.coeur.etat()))


class Joystick(websocket.WebSocketHandler):
    """Joystick avec homme mort : un 7105 de 0,5 s par ordre ; StopMove à la fermeture."""

    ouverts = set()

    def initialize(self, coeur, jeton):
        self.coeur = coeur
        self.jeton = jeton
        self.t_refus = None
        self.minuteur = None

    def check_origin(self, origine):
        # le jeton (ou 127.0.0.1) protège ; le client est le serveur de l'Atelier
        return True

    def prepare(self):
        if not autorise(self.request, self.jeton):
            self.set_status(401)
            self.finish(json.dumps({'detail': 'Jeton du pilotage absent ou faux (en-tête '
                                              'X-Jeton).'},
                                   ensure_ascii=False))

    def open(self):
        if Joystick.ouverts:
            self.envoyer({'type': 'refus', 'detail': 'Un autre joystick est déjà ouvert : '
                                                     'fermez-le d\'abord.'})
            self.close(4009, 'joystick deja ouvert')
            return
        Joystick.ouverts.add(self)
        self.envoyer({'type': 'bienvenue', 'detail': 'Joystick relié au nœud '
                                                     'pilotage.', 'etat': self.coeur.etat()})
        self.minuteur = ioloop.PeriodicCallback(self.etat, PERIODE_ETAT_WS_S * 1000)
        self.minuteur.start()

    def etat(self):
        self.envoyer({'type': 'etat', 'etat': self.coeur.etat()})

    def envoyer(self, message):
        try:
            self.write_message(json.dumps(message, ensure_ascii=False, default=str))
        except websocket.WebSocketClosedError:
            pass

    def on_message(self, texte):
        if self not in Joystick.ouverts:
            return
        try:
            d = json.loads(texte, parse_constant=refuser_non_fini)
            if not isinstance(d, dict):
                raise ValueError
        except ValueError:
            self.coeur.faire('lacher_joystick', 'message illisible')
            self.refuser('Ordre du joystick illisible : robot arrêté.')
            return
        if d.get('lacher'):
            self.coeur.faire('lacher_joystick', 'manche lâché')
            return
        vx, vy, wz = (d.get(c, 0.0) for c in ('vx', 'vy', 'wz'))
        resultat = self.coeur.faire('ordre_joystick', vx, vy, wz)
        if not resultat.ok:
            self.refuser(resultat.corps.get('detail', 'Ordre refusé.'))

    def refuser(self, detail):
        t = self.coeur.horloge()
        if self.t_refus is None or t - self.t_refus >= ECART_REFUS_WS_S:
            self.t_refus = t
            self.envoyer({'type': 'refus', 'detail': detail})

    def on_close(self):
        if self.minuteur is not None:
            self.minuteur.stop()
        if self in Joystick.ouverts:
            Joystick.ouverts.discard(self)
            self.coeur.faire('lacher_joystick', 'WebSocket fermé')


class Inconnue(Base):
    def get(self, *args):
        self.repondre(404, {'detail': f'Adresse inconnue du nœud pilotage : {self.request.path}'})

    async def traiter(self, d):
        self.repondre(404, {'detail': f'Adresse inconnue du nœud pilotage : {self.request.path}'})


def creer_application(coeur, jeton=''):
    """L'application tornado du nœud pilotage."""
    options = dict(coeur=coeur, jeton=jeton or '')
    routes = [(r'/etat', Etat), (r'/danses', Danses), (r'/gestes', Gestes), (r'/maitre', Maitre),
              (r'/posture', Posture), (r'/tache', Tache), (r'/geste', Geste), (r'/voix', Voix),
              (r'/volume', Volume), (r'/led', Led), (r'/danse', Danse), (r'/choregraphie',
                                                                         Choregraphie),
              (r'/requete', Requete), (r'/arret', Arret), (r'/joystick', Joystick), (r'/(.*)',
                                                                                     Inconnue)]
    return web.Application([(chemin, classe, options) for chemin, classe in routes],
                           websocket_ping_interval=1.0, websocket_ping_timeout=3.0,
                           compress_response=False)


def ecouter(application, port, hote='0.0.0.0'):
    """Démarre l'écoute HTTP ; renvoie le serveur tornado."""
    return application.listen(int(port), address=hote, max_body_size=CORPS_MAX_OCTETS,
                              xheaders=False)
