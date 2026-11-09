"""La logique du nœud voix, sans ROS (vague 6, section 13.6 du plan) : file d'attente, priorités, trois sorties.

LogiqueVoix reçoit les messages du nœud (dire : /robot/dire, commande : /voix/commande, personnalite :
/personnalite/active, reponse : /api/voice/response), le son des phrases calculé par le fil de synthèse
(prochaine_synthese, puis son_pret ou synthese_echouee) et l'heure (pas, 20 fois par seconde). Chaque appel rend
ce qu'il faut publier : des Requete (service voice du robot, /api/voice/request) et des Annonce (/voix/son,
sortie borne). etat() est le message de /voix/etat. Horloge injectable (tests à fausse horloge).

Les règles (contrat de 13.6) :
  - une phrase à la fois ; « normale » attend son tour ; « haute » coupe la phrase en cours (1004, puis elle),
    sauf une phrase de sécurité ; « securite » coupe la phrase en cours et vide la file ; « taire » : 1004 et file
    vide ; jamais deux flux en même temps : après un 1004, PAUSE_APRES_ARRET_S avant la phrase suivante ; une
    phrase finie (durée du PCM + MARGE_FIN_S) laisse la place à la suivante ;
  - sortie robot : le PCM 16 kHz en morceaux de 96 000 octets au plus (3 s), tous avec le stream_id de la
    phrase (son id), dans l'ordre, au moins ECART_MORCEAUX_S entre deux morceaux (comme les exemples du SDK
    d'Unitree, qui attendent 1 s entre deux PlayStream) ; la fin est estimée par la durée du PCM (le SDK n'a
    pas de « fin de lecture ») ; un code d'erreur rendu par le robot pour un morceau arrête l'envoi des
    suivants (comme play_pcm_stream du SDK) ; le code de 1004 est ignoré (PlayStop du SDK aussi) ;
  - sortie borne : rien n'est envoyé au robot ; le WAV de la phrase (écrit par le fil de synthèse) est annoncé
    sur /voix/son quand vient son tour ;
  - sortie robot_tts : 1001 {index, speaker_id, text} (synthèse d'Unitree ; langues à vérifier sur le robot) ;
    durée estimée d'après la longueur du texte ;
  - volume : 1006 au démarrage (si un volume est réglé), à chaque commande « volume » et au retour du robot,
    puis 1005 pour le relire ; seulement pour les sorties robot et robot_tts ;
  - le robot muet (personne n'écoute /api/voice/request, ou plus de réponse en DELAI_REPONSE_S) : robot.abonne
    ou robot.repond faux, erreurs comptées une fois par phrase, jamais d'exception ; une phrase qui attend
    l'abonné plus de DELAI_ABONNE_S est abandonnée ; une phrase normale qui a attendu plus de PEREMPTION_S est
    oubliée (« Suivez-moi ! » dit une minute plus tard n'a plus de sens).

Les réglages d'une phrase : voix et vitesse du message (champ voix de /robot/dire), sinon ceux de la
personnalité active, sinon ceux du nœud (demo.yaml, g1-voix --voix, commande « voix ») ; le volume d'une
personnalité (0 à 100) est un gain appliqué au son de ses phrases (« Discret » à 50 parle plus bas), le volume du
nœud est celui du haut-parleur du robot (1006) ; pour la sortie borne, il s'applique aussi au WAV.
"""
import json
import re
import time
from collections import OrderedDict, deque, namedtuple
from datetime import datetime

from atelier.lieu import voix as V
from atelier.lieu.pilotage import parametre_tts, parametre_volume
from atelier.lieu.validation import valider_donnees

from .synthese import choisir_voix, gain_valable, vitesse_valable

Requete = namedtuple("Requete", "api_id parametre binaire identifiant raison phrase")
Annonce = namedtuple("Annonce", "message")

SORTIES_ROBOT = ("robot", "robot_tts")      # les sorties qui parlent au service voice du robot
SORTIES_PIPER = ("robot", "borne")          # les sorties qui ont besoin du son de Piper
DELAI_REPONSE_S = 1.5         # une requête sans réponse au-delà : le robot ne répond pas
DELAI_ABONNE_S = 2.0          # personne n'écoute /api/voice/request : la phrase attend ce temps, puis est abandonnée
PAUSE_APRES_ARRET_S = 0.2     # après un 1004 (STOP_PLAY), avant le premier morceau de la phrase suivante
MARGE_FIN_S = 0.3             # fin d'une phrase : durée du son + cette marge (latence du robot)
FILE_MAX = 10                 # phrases en attente au plus (au-delà, la plus vieille phrase normale est oubliée)
PEREMPTION_S = 30.0           # une phrase normale qui attend depuis plus longtemps est oubliée
AVANCE_SYNTHESE = 3           # phrases de la file synthétisées d'avance au plus
CARACTERES_PAR_S_TTS = 13.0   # durée estimée d'une phrase de la synthèse d'Unitree (robot_tts)
LOCUTEUR_TTS_DEFAUT = V.LOCUTEURS_TTS["en"]   # le français n'est pas dans le SDK : l'anglais lit mieux nos lettres
HISTORIQUE_MAX = 20
LIBELLES_SORTIES = {
    "robot": "Haut-parleur du robot (voix du PC)",
    "borne": "Borne (tablette ou téléphone)",
    "robot_tts": "Synthèse du robot (langues à vérifier)",
}
TEXTES_ERREURS = {
    "abonne": "Le haut-parleur du robot n'écoute pas : « {texte} » n'a pas été dite.",
    "reponse": "Le haut-parleur du robot ne répond plus (phrase « {texte} »).",
    "code": "Le robot a refusé la phrase « {texte} » (code {code}).",
    "synthese": "La voix du PC n'a pas pu dire « {texte} » : {erreur}.",
    "volume": "Le robot a refusé le volume (code {code}).",
    "message": "Message ignoré : {erreur}",
}
MOTIF_NON_ID = re.compile(r"[^a-z0-9-]+")


class Identifiants:
    """identity.id des requêtes : time.monotonic_ns(), strictement croissant (comme le pont et le pilotage)."""

    def __init__(self, horloge_ns=time.monotonic_ns):
        self._horloge_ns = horloge_ns
        self._dernier = 0

    def __call__(self):
        self._dernier = max(int(self._horloge_ns()), self._dernier + 1)
        return self._dernier


def id_de_phrase(demande, numero, instant):
    """L'id d'une phrase (MOTIF_ID_SON) : celui de /robot/dire s'il convient (mis en minuscules, les autres
    signes remplacés par « - »), sinon un id neuf « s-AAAAMMJJ-HHMMSS-NNNN »."""
    if isinstance(demande, str) and demande:
        propre = MOTIF_NON_ID.sub("-", demande.lower()).strip("-")[:64].strip("-")
        if propre and V.MOTIF_ID_SON.match(propre):
            return propre
    return f"s-{instant:%Y%m%d-%H%M%S}-{numero % 10000:04d}"


def duree_tts_s(texte):
    """Durée estimée d'une phrase dite par la synthèse d'Unitree (robot_tts)."""
    return max(1.0, len(texte) / CARACTERES_PAR_S_TTS + 0.5)


class Phrase:
    """Une phrase à dire : son texte, ses réglages, son son (Piper) et son déroulé."""

    def __init__(self, ident, message, recu, numero):
        self.id = ident
        self.demande = message.get("id")            # id de /robot/dire, tel quel
        self.texte = message["texte"].strip()
        self.priorite = message.get("priorite") or "normale"
        self.source = message.get("source") or "autre"
        self.code = message.get("code")
        self.langue = message.get("langue") or "fr"
        self.voix_message = message.get("voix") if isinstance(message.get("voix"), dict) else None
        self.recu = recu
        self.numero = numero
        self.son = None                 # SonPhrase (synthese.py)
        self.cle_son = None             # (voix, vitesse, gain) du son calculé
        self.en_synthese = None         # clé de la synthèse en cours (fil de synthèse)
        self.echec_synthese = None
        self.sortie = None
        self.debut = None
        self.debut_iso = None
        self.fin_prevue = None
        self.morceaux = []
        self.envoyes = 0
        self.octets_envoyes = 0
        self.prochain_morceau = None
        self.vers_robot = False         # quelque chose a été envoyé au robot pour cette phrase
        self.attente_abonne = None
        self.erreur = False             # une erreur déjà comptée pour cette phrase
        self.interrompue = False

    @property
    def rang(self):
        return V.RANG_PRIORITE.get(self.priorite, 0)

    def resume(self):
        """Le champ en_cours de /voix/etat."""
        d = {"id": self.id, "texte": self.texte[:500], "priorite": self.priorite, "source": self.source}
        if self.debut_iso:
            d["debut"] = self.debut_iso
        duree = self.duree_s()
        if duree is not None:
            d["duree_s"] = round(duree, 2)
        if self.demande and self.demande != self.id:
            d["id_demande"] = self.demande
        if self.sortie:
            d["sortie"] = self.sortie
        if self.sortie == "robot":
            d["morceaux"] = {"envoyes": self.envoyes, "total": len(self.morceaux)}
        return d

    def duree_s(self):
        if self.sortie == "robot_tts":
            return duree_tts_s(self.texte)
        if self.son is not None:
            return self.son.duree_pcm_s if self.sortie == "robot" else self.son.duree_s
        return None


class LogiqueVoix:
    """File et priorités du nœud voix ; sorties robot (Piper → 1003), borne (WAV → /voix/son), robot_tts (1001)."""

    def __init__(self, sortie="robot", voix=V.VOIX_DEFAUT, volume=None, vitesse=1.0,
                 locuteur_tts=LOCUTEUR_TTS_DEFAUT, disponibles=None, horloge=time.monotonic, mur=None,
                 identifiants=None):
        if sortie not in V.SORTIES_VOIX:
            raise ValueError(f"sortie « {sortie} » inconnue : {', '.join(V.SORTIES_VOIX)}")
        if volume is not None and (isinstance(volume, bool) or not isinstance(volume, int) or not 0 <= volume <= 100):
            raise ValueError("volume : un nombre entier de 0 à 100")
        self.horloge = horloge
        self.mur = mur or (lambda: datetime.now().astimezone())
        self.identifiants = identifiants or Identifiants()
        self.disponibles = list(V.VOIX_PIPER if disponibles is None else disponibles)
        self.sortie = sortie
        self.voix = choisir_voix(voix, self.disponibles) or voix
        self.vitesse = vitesse_valable(vitesse)
        self.volume = volume
        self.volume_lu = None
        self.locuteur_tts = int(locuteur_tts)
        self.index_tts = 0
        self.personnalite = None
        self.file = deque()
        self.en_cours = None
        self.t_libre = 0.0                  # pas de nouvelle phrase avant cet instant (après un 1004)
        self.numero = 0
        self.dites = self.interrompues = self.erreurs = self.refusees = 0
        self.oubliees = self.abandonnees = 0
        self.derniere_erreur = None
        self.derniere_commande = None
        self.historique = deque(maxlen=HISTORIQUE_MAX)
        self.abonne = False
        self.repond = None
        self.t_reponse = None
        self.attendues = OrderedDict()      # identifiant → (instant, api_id, phrase)
        self.perdues = deque(maxlen=200)    # identifiants dont la réponse n'est pas venue à temps
        self.envoyees = {}                  # api_id → nombre de requêtes envoyées
        self.reglage_robot = sortie in SORTIES_ROBOT     # 1006 puis 1005 à envoyer dès que le robot écoute
        self.syntheses = []                 # secondes de calcul des dernières phrases
        self.change = True

    # ------------------------------------------------------------ outils

    def _t(self, t):
        return float(self.horloge()) if t is None else float(t)

    def _iso(self):
        return self.mur().isoformat(timespec="seconds")

    def _erreur(self, genre, phrase=None, **valeurs):
        if phrase is not None:
            if phrase.erreur:
                return
            phrase.erreur = True
            valeurs.setdefault("texte", phrase.texte[:60])
        self.erreurs += 1
        self.derniere_erreur = TEXTES_ERREURS[genre].format(**valeurs)[:300]
        self.change = True

    def _requete(self, api_id, parametre, binaire=b"", raison="", phrase=None, t=0.0):
        identifiant = self.identifiants()
        self.attendues[identifiant] = (t, api_id, phrase)
        while len(self.attendues) > 500:
            self.attendues.popitem(last=False)
        self.envoyees[api_id] = self.envoyees.get(api_id, 0) + 1
        return Requete(api_id, parametre, bytes(binaire), identifiant, raison, phrase.id if phrase else None)

    def _phrases(self):
        return ([self.en_cours] if self.en_cours is not None else []) + list(self.file)

    def _trouver(self, ident):
        for p in self._phrases():
            if p.id == ident:
                return p
        return None

    def reglages_phrase(self, phrase, sortie=None):
        """(voix, vitesse, gain) du son d'une phrase pour une sortie (la sortie actuelle par défaut)."""
        sortie = sortie or self.sortie
        reglages = phrase.voix_message
        if reglages is None and self.personnalite:
            reglages = self.personnalite.get("voix") if isinstance(self.personnalite.get("voix"), dict) else None
        reglages = reglages or {}
        voix = choisir_voix(reglages.get("nom"), self.disponibles, self.voix) or self.voix
        vitesse = vitesse_valable(reglages.get("vitesse", self.vitesse))
        gain = 1.0
        volume_phrase = reglages.get("volume")
        if isinstance(volume_phrase, (int, float)) and not isinstance(volume_phrase, bool):
            gain = gain_valable(volume_phrase / 100.0)
        if sortie == "borne" and self.volume is not None:
            gain *= self.volume / 100.0
        return voix, round(vitesse, 3), round(gain, 3)

    # ------------------------------------------------------------ entrées

    def dire(self, message, t=None):
        """Une phrase de /robot/dire (dict) : rangée selon sa priorité. Rend ce qu'il faut publier."""
        t = self._t(t)
        if not isinstance(message, dict):
            erreurs = ["/robot/dire : un objet JSON est attendu"]
        else:
            erreurs = valider_donnees("robot_dire", message, "/robot/dire")
            if not erreurs and not message["texte"].strip():
                erreurs = ["/robot/dire : texte vide"]
        if erreurs:
            self.refusees += 1
            self.derniere_erreur = TEXTES_ERREURS["message"].format(erreur=erreurs[0])[:300]
            self.change = True
            return []
        self.numero += 1
        phrase = Phrase(id_de_phrase(message.get("id"), self.numero, self.mur()), message, t, self.numero)
        sorties = []
        if phrase.rang >= 2:
            self.abandonnees += len(self.file)
            self.file.clear()
            sorties += self._interrompre(t)
            self.file.appendleft(phrase)
        elif phrase.rang == 1:
            if self.en_cours is not None and self.en_cours.rang <= 1:
                sorties += self._interrompre(t)
            rang = 0
            while rang < len(self.file) and self.file[rang].rang >= 1:
                rang += 1
            self.file.insert(rang, phrase)
        else:
            if len(self.file) >= FILE_MAX:
                vieilles = [p for p in self.file if p.rang == 0]
                if vieilles:
                    self.file.remove(vieilles[0])
                    self.oubliees += 1
            self.file.append(phrase)
        self.change = True
        return sorties + self.pas(t)

    def commande(self, message, t=None):
        """Une commande de /voix/commande (schéma commande_voix) : taire, volume, sortie, voix."""
        t = self._t(t)
        erreurs = (valider_donnees("commande_voix", message, "/voix/commande") if isinstance(message, dict)
                   else ["/voix/commande : un objet JSON est attendu"])
        if erreurs:
            self.refusees += 1
            self.derniere_erreur = TEXTES_ERREURS["message"].format(erreur=erreurs[0])[:300]
            self.derniere_commande = {"action": None, "ok": False, "message": erreurs[0][:200]}
            self.change = True
            return []
        action = message["action"]
        sorties, ok, texte = [], True, ""
        if action == "taire":
            self.abandonnees += len(self.file)
            self.file.clear()
            sorties = self._interrompre(t)
            if not sorties and self.sortie in SORTIES_ROBOT and self.abonne:
                sorties = [self._requete(V.API_VOIX["stop_play"], V.parametre_arret(), raison="taire", t=t)]
                self.t_libre = max(self.t_libre, t + PAUSE_APRES_ARRET_S)
            texte = "Le robot se tait."
        elif action == "volume":
            self.volume = int(message["volume"])
            if self.sortie in SORTIES_ROBOT:
                if self.abonne:
                    sorties = self._reglages_robot(t)
                else:
                    self.reglage_robot = True      # envoyé dès que le robot écoute
            texte = f"Volume : {self.volume} %."
        elif action == "sortie":
            nouvelle = message["sortie"]
            if nouvelle != self.sortie:
                sorties = self._interrompre(t)
                self.sortie = nouvelle
                self.reglage_robot = nouvelle in SORTIES_ROBOT
            texte = f"Sortie : {LIBELLES_SORTIES[nouvelle]}."
        elif action == "voix":
            nom = message["voix"]
            if nom in self.disponibles:
                self.voix = nom
                texte = f"Voix : {V.VOIX_PIPER.get(nom, nom)}."
            else:
                ok = False
                texte = (f"Voix « {nom} » absente de ce PC (voix présentes : "
                         f"{', '.join(self.disponibles) or 'aucune'}).")
                self.derniere_erreur = texte
        self.derniere_commande = {"action": action, "ok": ok, "message": texte}
        if message.get("id"):
            self.derniere_commande["id"] = message["id"]
        self.change = True
        return sorties + self.pas(t)

    def changer_personnalite(self, message, t=None):
        """/personnalite/active : ses réglages de voix (nom, vitesse, volume) servent aux phrases sans les leurs."""
        if isinstance(message, dict) and isinstance(message.get("id"), str):
            self.personnalite = dict(message)
            self.change = True
        return []

    def changer_abonnes(self, nombre):
        """Nombre de programmes qui écoutent /api/voice/request (le service voice du robot, ou le faux G1)."""
        abonne = nombre > 0
        if abonne and not self.abonne and self.sortie in SORTIES_ROBOT:
            self.reglage_robot = True       # robot revenu (ou trouvé) : le volume lui est renvoyé
        if abonne != self.abonne:
            self.abonne = abonne
            self.change = True

    def reponse(self, identifiant, code, data="", t=None):
        """Une réponse de /api/voice/response ; celles des autres programmes (pilotage) sont ignorées."""
        t = self._t(t)
        attendue = self.attendues.pop(identifiant, None)
        if attendue is None:
            if identifiant in self.perdues:          # arrivée trop tard : le robot répond quand même
                self.repond, self.t_reponse, self.change = True, t, True
            return []
        _, api_id, phrase = attendue
        self.repond, self.t_reponse = True, t
        code = int(code)
        if api_id == V.API_VOIX["get_volume"] and code == 0:
            try:
                lu = json.loads(data or "{}").get("volume")
            except (ValueError, AttributeError):
                lu = None
            if isinstance(lu, int) and not isinstance(lu, bool) and 0 <= lu <= 100:
                self.volume_lu = lu
                if self.volume is None:
                    self.volume = lu
        elif code != 0 and api_id == V.API_VOIX["start_play"] and phrase is not None:
            self._erreur("code", phrase, code=code)
            if phrase is self.en_cours and phrase.envoyes < len(phrase.morceaux):
                phrase.morceaux = phrase.morceaux[:phrase.envoyes]        # comme play_pcm_stream : on s'arrête
                phrase.fin_prevue = phrase.debut + V.duree_pcm_s(phrase.octets_envoyes) + MARGE_FIN_S
        elif code != 0 and api_id == V.API_VOIX["tts"] and phrase is not None:
            self._erreur("code", phrase, code=code)
        elif code != 0 and api_id in (V.API_VOIX["set_volume"], V.API_VOIX["get_volume"]):
            self._erreur("volume", code=code)
        self.change = True
        return []

    # ------------------------------------------------------------ synthèse (fil à part)

    def prochaine_synthese(self):
        """(id, texte, voix, vitesse, gain) de la prochaine phrase à synthétiser, ou None : la file dans l'ordre
        (AVANCE_SYNTHESE phrases au plus), une phrase dont les réglages ont changé est refaite."""
        if self.sortie not in SORTIES_PIPER:
            return None
        for phrase in list(self.file)[:AVANCE_SYNTHESE]:      # la phrase en cours a déjà son son
            if phrase.echec_synthese:
                continue
            cle = self.reglages_phrase(phrase)
            if phrase.cle_son == cle or phrase.en_synthese == cle:
                continue
            phrase.en_synthese = cle
            return (phrase.id, phrase.texte) + cle
        return None

    def son_pret(self, ident, cle, son):
        """Le son d'une phrase est calculé (son : SonPhrase, cle : (voix, vitesse, gain)). Appelé par le fil de
        synthèse, qui ne publie rien : la phrase part au pas suivant (au plus PERIODE_PAS_S plus tard)."""
        phrase = self._trouver(ident)
        if phrase is None:
            return
        phrase.en_synthese = None
        phrase.son, phrase.cle_son = son, tuple(cle)
        self.syntheses.append(son.duree_synthese_s)
        del self.syntheses[:-20]
        self.change = True

    def synthese_echouee(self, ident, erreur):
        """La synthèse d'une phrase a échoué : erreur comptée, la phrase sera retirée de la file."""
        phrase = self._trouver(ident)
        if phrase is None:
            return
        phrase.en_synthese = None
        phrase.echec_synthese = str(erreur)
        self._erreur("synthese", phrase, erreur=str(erreur)[:150])

    # ------------------------------------------------------------ le temps qui passe

    def pas(self, t=None):
        """Morceaux à envoyer, fin de la phrase en cours, phrase suivante. Rend ce qu'il faut publier."""
        t = self._t(t)
        sorties = self._verifier_reponses(t)
        if self.reglage_robot and self.abonne and self.sortie in SORTIES_ROBOT:
            sorties += self._reglages_robot(t)
        phrase = self.en_cours
        if phrase is not None:
            if (phrase.sortie == "robot" and phrase.envoyes < len(phrase.morceaux)
                    and t >= phrase.prochain_morceau):
                sorties.append(self._morceau(phrase, t))
            if t >= phrase.fin_prevue:
                self._finir(phrase, t)
        if self.en_cours is None:
            sorties += self._commencer(t)
        return sorties

    def _verifier_reponses(self, t):
        for identifiant, (instant, api_id, phrase) in list(self.attendues.items()):
            if t - instant < DELAI_REPONSE_S:
                break
            del self.attendues[identifiant]
            self.perdues.append(identifiant)
            if self.repond is not False:
                self.change = True
            self.repond = False
            if api_id == V.API_VOIX["stop_play"]:
                continue                     # PlayStop du SDK ignore aussi sa réponse
            if phrase is not None:
                self._erreur("reponse", phrase)
            elif not self.derniere_erreur or "ne répond" not in self.derniere_erreur:
                self.erreurs += 1
                self.derniere_erreur = "Le haut-parleur du robot ne répond plus."
                self.change = True
        return []

    def _reglages_robot(self, t):
        self.reglage_robot = False
        sorties = []
        if self.volume is not None:
            sorties.append(self._requete(V.API_VOIX["set_volume"], parametre_volume(self.volume), raison="volume",
                                         t=t))
        sorties.append(self._requete(V.API_VOIX["get_volume"], V.parametre_lire_volume(), raison="lire_volume",
                                     t=t))
        return sorties

    def _finir(self, phrase, t):
        self.en_cours = None
        self.dites += 1
        self.t_libre = max(self.t_libre, t)
        self._noter(phrase, "dite", t)
        self.change = True

    def _interrompre(self, t):
        """Coupe la phrase en cours : 1004 si le robot la dit (jamais deux flux en même temps)."""
        phrase = self.en_cours
        if phrase is None:
            return []
        self.en_cours = None
        phrase.interrompue = True
        self.interrompues += 1
        self._noter(phrase, "interrompue", t)
        self.change = True
        if phrase.sortie in SORTIES_ROBOT and phrase.vers_robot:
            self.t_libre = max(self.t_libre, t + PAUSE_APRES_ARRET_S)
            return [self._requete(V.API_VOIX["stop_play"], V.parametre_arret(), raison="interruption", t=t)]
        return []

    def _noter(self, phrase, fin, t):
        self.historique.append({"id": phrase.id, "texte": phrase.texte[:120], "priorite": phrase.priorite,
                                "source": phrase.source, "sortie": phrase.sortie, "fin": fin,
                                "duree_s": None if phrase.duree_s() is None else round(phrase.duree_s(), 2)})

    def _commencer(self, t):
        while self.file:
            phrase = self.file[0]
            if phrase.rang == 0 and t - phrase.recu > PEREMPTION_S:
                self.file.popleft()
                self.oubliees += 1
                self._noter(phrase, "oubliee", t)
                self.change = True
                continue
            if t < self.t_libre:
                return []
            if self.sortie in SORTIES_PIPER:
                if phrase.echec_synthese:
                    self.file.popleft()
                    self._noter(phrase, "echec", t)
                    self.change = True
                    continue
                if phrase.son is None or phrase.cle_son != self.reglages_phrase(phrase):
                    return []                         # le fil de synthèse y travaille
            if self.sortie in SORTIES_ROBOT and not self.abonne:
                if phrase.attente_abonne is None:
                    phrase.attente_abonne = t
                if t - phrase.attente_abonne < DELAI_ABONNE_S:
                    return []
                self.file.popleft()
                self._erreur("abonne", phrase)
                self._noter(phrase, "echec", t)
                continue
            self.file.popleft()
            return self._lancer(phrase, t)
        return []

    def _lancer(self, phrase, t):
        phrase.sortie = self.sortie
        phrase.debut, phrase.debut_iso = t, self._iso()
        self.en_cours = phrase
        self.change = True
        if phrase.sortie == "robot":
            phrase.morceaux = V.morceaux_pcm(phrase.son.pcm16)
            phrase.fin_prevue = t + phrase.son.duree_pcm_s + MARGE_FIN_S
            return [self._morceau(phrase, t)]
        if phrase.sortie == "borne":
            if phrase.son.infos.get("wav") is False:          # la borne n'a pas de fichier à jouer
                self.en_cours = None
                self._erreur("synthese", phrase, erreur="le fichier du son n'a pas pu être écrit")
                self._noter(phrase, "echec", t)
                return []
            phrase.fin_prevue = t + phrase.son.duree_s + MARGE_FIN_S
            return [Annonce(self.message_son(phrase))]
        locuteur = V.LOCUTEURS_TTS.get(phrase.langue, self.locuteur_tts)
        parametre = parametre_tts(phrase.texte, self.index_tts, locuteur)
        self.index_tts += 1
        phrase.fin_prevue = t + duree_tts_s(phrase.texte) + MARGE_FIN_S
        phrase.vers_robot = True
        return [self._requete(V.API_VOIX["tts"], parametre, raison="tts", phrase=phrase, t=t)]

    def _morceau(self, phrase, t):
        morceau = phrase.morceaux[phrase.envoyes]
        phrase.envoyes += 1
        phrase.octets_envoyes += len(morceau)
        phrase.prochain_morceau = t + V.ECART_MORCEAUX_S
        phrase.vers_robot = True
        self.change = True
        return self._requete(V.API_VOIX["start_play"], V.parametre_lecture(phrase.id), morceau,
                             raison=f"morceau {phrase.envoyes}/{len(phrase.morceaux)}", phrase=phrase, t=t)

    def message_son(self, phrase):
        """Message de /voix/son (schéma son_voix) pour la sortie borne."""
        return {"version": 1, "id": phrase.id, "texte": phrase.texte[:500],
                "duree_s": round(max(0.01, phrase.son.duree_s), 3), "url": V.URL_SON + phrase.id, "priorite": phrase.priorite, "source": phrase.source[:40],
                "frequence_hz": int(phrase.son.frequence_hz), "temps": self._iso(),
                "voix": phrase.son.voix, "volume": self.volume}

    # ------------------------------------------------------------ arrêt du nœud

    def arreter(self, t=None):
        """Ctrl+C ou SIGTERM : la file est vidée et, si le robot parle (ou a parlé), 1004."""
        t = self._t(t)
        self.abandonnees += len(self.file)
        self.file.clear()
        sorties = self._interrompre(t)
        if not sorties and self.sortie in SORTIES_ROBOT and self.abonne and (
                self.envoyees.get(V.API_VOIX["start_play"]) or self.envoyees.get(V.API_VOIX["tts"])):
            sorties = [self._requete(V.API_VOIX["stop_play"], V.parametre_arret(), raison="arret_noeud", t=t)]
        return sorties

    # ------------------------------------------------------------ état

    def etat(self, t=None):
        """Le message de /voix/etat (schéma etat_voix)."""
        t = self._t(t)
        moyenne = round(sum(self.syntheses) / len(self.syntheses), 3) if self.syntheses else None
        return {
            "version": 1, "sortie": self.sortie, "libelle_sortie": LIBELLES_SORTIES[self.sortie],
            "voix": self.voix, "vitesse": self.vitesse, "volume": self.volume, "volume_lu": self.volume_lu,
            "en_cours": None if self.en_cours is None else self.en_cours.resume(),
            "file": len(self.file), "dites": self.dites, "interrompues": self.interrompues,
            "erreurs": self.erreurs, "derniere_erreur": self.derniere_erreur, "refusees": self.refusees,
            "oubliees": self.oubliees, "abandonnees": self.abandonnees,
            "robot": {"abonne": self.abonne, "repond": self.repond,
                      "age_reponse_s": None if self.t_reponse is None else round(max(0.0, t - self.t_reponse), 2),
                      "attendues": len(self.attendues)},
            "synthese": {"derniere_s": self.syntheses[-1] if self.syntheses else None, "moyenne_s": moyenne,
                         "nombre": len(self.syntheses)},
            "voix_disponibles": list(self.disponibles), "locuteur_tts": self.locuteur_tts,
            "personnalite": (self.personnalite or {}).get("id"),
            "requetes": {str(k): v for k, v in sorted(self.envoyees.items())},
            "derniere_commande": self.derniere_commande, "historique": list(self.historique)[-5:],
            "temps": self._iso(),
        }


__all__ = ["AVANCE_SYNTHESE", "Annonce", "DELAI_ABONNE_S", "DELAI_REPONSE_S", "FILE_MAX", "Identifiants",
           "LIBELLES_SORTIES", "LOCUTEUR_TTS_DEFAUT", "LogiqueVoix", "MARGE_FIN_S", "PAUSE_APRES_ARRET_S",
           "PEREMPTION_S", "Phrase", "Requete", "SORTIES_PIPER", "SORTIES_ROBOT", "duree_tts_s", "id_de_phrase"]
