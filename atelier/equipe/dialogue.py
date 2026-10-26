"""Chatbot à règles de dialogues.yaml (vague 4, section 11.6 du plan), sans ROS.

EXEMPLE : un chatbot simple et prévisible, que l'équipe remplacera (ou gardera) par le sien. Il sert
au nœud dialogue (paquet g1_equipe) et à l'essai d'une phrase dans l'onglet Dialogues de l'Atelier.

    from atelier.equipe.dialogue import Chatbot
    bot = Chatbot(dialogues, salles)            # contenu de dialogues.yaml, salles de salles.yaml
    r = bot.repondre("Je cherche la salle B204, s'il vous plaît")
    r["action"], r["reponse"], r["guide"]
    → "guider", "Je vous emmène à Salle B204. Suivez-moi !",
      {"cible": "b204", "accompagner": True, "source": "dialogue"}

Comment une phrase est comparée aux motifs :
  - phrase et motifs sont normalisés (atelier.lieu.equipe.normaliser) : sans majuscules, accents ni
    ponctuation (« Où est l'Accueil ? » → « ou est l accueil ») ;
  - {salle} vaut une salle du lieu : son id, son nom ou un de ses alias (salles.yaml), avec ou sans
    article ou préposition devant (« la salle b204 », « au cdi », « l accueil », « jusqu a la b204 ») ;
    une règle à {salle} ne correspond que si une salle est trouvée ;
  - {*} vaut n'importe quels mots, aucun compris ;
  - passe 1, « phrase entière » : la première règle (dans l'ordre du fichier) dont un motif correspond
    à toute la phrase l'emporte ;
  - passe 2, « dans la phrase » (rien en passe 1) : la première règle dont un motif se trouve dans la
    phrase (« bonjour, je cherche la b204 merci » contient « je cherche {salle} »). Prudence : un motif
    fait seulement de repères ({salle}, {*}) n'est pas cherché dans la phrase, et une règle guider ne
    l'est pas si la phrase a une négation (« ne », « n' », « pas », « jamais ») : « je ne cherche
    pas la b204 » ne fait pas partir le robot ;
  - sinon : le repli.

Le chatbot ne fait rien bouger : il dit quoi répondre et quoi demander. Le nœud dialogue publie la
demande sur /guide/aller ; c'est le guide qui décide et conduit (le verrou du pilotage, la sécurité
et l'arrêt restent au guide et au nœud pilotage). decider() ajoute ce que le nœud sait de l'instant :
robot piloté à la main, visite déjà en cours.
"""
from atelier.lieu.comportement import ETATS_EN_MISSION, texte_evenement
from atelier.lieu.equipe import REPERE_JOKER, REPERE_SALLE, jetons_motif, normaliser

# Mots qui peuvent précéder le nom d'une salle (« je vais à la b204 », « jusqu'au cdi »)
MOTS_LIAISON = frozenset({"a", "au", "aux", "la", "le", "les", "l", "un", "une", "des", "du", "de", "d", "en",
                          "vers", "jusqu", "jusque", "dans", "pour", "chez", "sur", "the", "to"})
# Négations : en passe 2, une règle guider est ignorée si la phrase en contient une
NEGATIONS = frozenset({"ne", "n", "pas", "jamais"})
MOTS_MAX = 60               # au-delà, la phrase est coupée (reconnaissance vocale bavarde)
TEXTE_MAX = 500

PASSE_ENTIERE, PASSE_PARTIELLE = "entiere", "partielle"

MESSAGES = {
    "autre_etage": "{nom_salle} est à un autre étage : je ne peux pas encore vous y emmener.",
    "deja_en_visite": "Je guide déjà quelqu'un vers {nom} : je reviens dès que possible.",
    "personnalite_inconnue": "Je ne connais pas ce mode.",
}


class _Salle:
    __slots__ = ("id", "nom", "etage")

    def __init__(self, ident, nom, etage):
        self.id, self.nom, self.etage = ident, nom, etage


def _salle(s):
    if isinstance(s, dict):
        return _Salle(s["id"], s.get("nom") or s["id"], s.get("etage"))
    return _Salle(s.id, s.nom, s.etage)


class Chatbot:
    """Les règles d'un dialogues.yaml (déjà vérifié par atelier.lieu.equipe.valider_equipe) et les
    salles du lieu (Salle de atelier.lieu, ou dicts de salles.yaml). etage : si donné, une salle d'un
    autre étage n'est pas guidée (le guide ne change pas d'étage) : le robot le dit."""

    def __init__(self, dialogues, salles=(), etage=None):
        self.dialogues = dialogues
        self.etage = etage or None
        self.repli = dialogues["repli"]
        self.salles = {}
        self.formes = {}            # (mots…) → _Salle ; la première salle l'emporte
        for brut in salles:
            s = self.salles.setdefault(_salle(brut).id, _salle(brut))
            alias = (brut.get("alias") or []) if isinstance(brut, dict) else list(brut.alias)
            for texte in (s.id, s.nom, *alias):
                mots = tuple(normaliser(texte).split())
                if mots:
                    self.formes.setdefault(mots, s)
        self.regles = [(r, [(m, jetons_motif(m)) for m in r["motifs"]]) for r in dialogues["regles"]]

    # ------------------------------------------------------------ comparaison

    def salle_de(self, mots):
        """La salle désignée par ces mots (tuple ou liste), en retirant au besoin les articles et
        prépositions du début ; None sinon."""
        mots = tuple(mots)
        while mots:
            if mots in self.formes:
                return self.formes[mots]
            if mots[0] not in MOTS_LIAISON:
                return None
            mots = mots[1:]
        return None

    def _essai(self, jetons, mots, i, j, jusqu_au_bout):
        """(vrai, salle) si jetons[i:] correspond à mots[j:] (jusqu'au bout, ou à partir de j seulement)."""
        if i == len(jetons):
            return (j == len(mots) or not jusqu_au_bout), None
        jeton = jetons[i]
        if jeton == REPERE_JOKER:
            for k in range(j, len(mots) + 1):
                ok, salle = self._essai(jetons, mots, i + 1, k, jusqu_au_bout)
                if ok:
                    return True, salle
            return False, None
        if jeton == REPERE_SALLE:
            for k in range(len(mots), j, -1):          # la plus longue salle d'abord (« hall nord » avant « hall »)
                salle = self.salle_de(mots[j:k])
                if salle is not None:
                    ok, suivante = self._essai(jetons, mots, i + 1, k, jusqu_au_bout)
                    if ok:
                        return True, suivante or salle
            return False, None
        if j < len(mots) and mots[j] == jeton:
            return self._essai(jetons, mots, i + 1, j + 1, jusqu_au_bout)
        return False, None

    def _cherche(self, jetons, mots, passe):
        if passe == PASSE_ENTIERE:
            return self._essai(jetons, mots, 0, 0, True)
        for debut in range(len(mots)):
            ok, salle = self._essai(jetons, mots, 0, debut, False)
            if ok:
                return True, salle
        return False, None

    def trouver(self, texte):
        """(règle, motif, passe, salle) de la phrase, ou (None, None, None, None) : le repli."""
        mots = normaliser(str(texte)[:TEXTE_MAX]).split()[:MOTS_MAX]
        if not mots:
            return None, None, None, None
        negation = bool(NEGATIONS.intersection(mots))
        for passe in (PASSE_ENTIERE, PASSE_PARTIELLE):
            for regle, motifs in self.regles:
                if passe == PASSE_PARTIELLE and regle["action"] == "guider" and negation:
                    continue
                for motif, jetons in motifs:
                    if not jetons:
                        continue
                    if passe == PASSE_PARTIELLE and all(j in (REPERE_SALLE, REPERE_JOKER) for j in jetons):
                        continue
                    ok, salle = self._cherche(jetons, mots, passe)
                    if ok and (regle["action"] != "guider" or salle is not None):
                        return regle, motif, passe, salle
        return None, None, None, None

    # ------------------------------------------------------------ réponse

    def repondre(self, texte):
        """Ce que le chatbot répond à une phrase : dict
          texte, regle (id ou None : le repli), action (guider, dire, personnalite, stop, geste, repli),
          reponse (la phrase à dire), motif et passe (entiere, partielle ou None), salle et nom_salle
          (action guider), guide (la demande pour /guide/aller, schéma demande_guide, ou None),
          personnalite (id à activer, action personnalite), geste (numéro du geste des bras, action
          geste), raison (pourquoi une règle guider ne guide pas : autre_etage).
        None pour une phrase vide (rien à répondre)."""
        if not normaliser(str(texte)):
            return None
        regle, motif, passe, salle = self.trouver(texte)
        r = {"texte": str(texte)[:TEXTE_MAX], "regle": None, "action": "repli", "reponse": self.repli,
             "motif": None, "passe": None, "salle": None, "nom_salle": None, "guide": None,
             "personnalite": None, "geste": None, "raison": None}
        if regle is None:
            return r
        r.update(regle=regle["id"], action=regle["action"], motif=motif, passe=passe, reponse=regle["reponse"])
        if regle["action"] == "guider":
            r.update(salle=salle.id, nom_salle=salle.nom,
                     reponse=regle["reponse"].replace("{nom_salle}", salle.nom).replace("{salle}", salle.id))
            if self.etage and salle.etage and salle.etage != self.etage:
                r.update(raison="autre_etage", reponse=MESSAGES["autre_etage"].replace("{nom_salle}", salle.nom))
            else:
                r["guide"] = {"cible": salle.id, "accompagner": regle.get("accompagner", True), "source": "dialogue"}
        elif regle["action"] == "personnalite":
            r["personnalite"] = regle["personnalite"]
        elif regle["action"] == "geste":
            r["geste"] = regle.get("geste")
        return r

    def nom_salle(self, ident):
        s = self.salles.get(ident)
        return s.nom if s else ident


def en_visite(etat_guide):
    """Vrai si le guide mène une visite (et non un retour au point principal, ni le repos)."""
    if not etat_guide:
        return False
    return (etat_guide.get("etat") in ETATS_EN_MISSION and etat_guide.get("etat") != "retour"
            and etat_guide.get("mission") != "retour")


def decider(chatbot, resultat, etat_guide=None, maitre=None, remplacer_visite=False, personnalites=None,
            phrases=None):
    """Ce que le nœud dialogue fait d'une réponse du chatbot, selon l'instant. Renvoie un dict
      dire (phrase à publier sur /robot/dire, ou None), guide (demande pour /guide/aller, ou None),
      stop (publier /guide/stop), personnalite (dict de la personnalité à annoncer sur
      /personnalite/active, ou None), geste (numéro du geste à demander sur /robot/geste, ou None),
      raison (pourquoi une demande n'est pas envoyée, ou None).

    etat_guide : dernier /guide/etat (dict) ; maitre : dernier /mouvement/maitre (dict) ;
    personnalites : contenu de personnalites.yaml ; phrases : celles de la personnalité active
    (pour le texte « pilotage »).
    Règles : robot piloté à la main (maitre pilotage) → pas de /guide/aller, le robot le dit (le guide
    refuserait de toute façon) ; visite déjà en cours → pas de /guide/aller (sauf remplacer_visite),
    un retour au point principal, lui, est interrompu ; stop → toujours envoyé ; geste → seulement robot
    au repos (ni piloté à la main, ni en visite : la réponse est dite, sans le geste), et le nœud
    pilotage vérifie encore."""
    d = {"dire": None, "guide": None, "stop": False, "personnalite": None, "geste": None, "raison": None}
    if resultat is None:
        return d
    d["dire"] = resultat["reponse"]
    action = resultat["action"]
    if action == "guider" and resultat["guide"] is not None:
        if maitre and maitre.get("maitre") == "pilotage":
            d.update(dire=texte_evenement("pilotage", phrases=phrases), raison="pilotage")
        elif en_visite(etat_guide) and not remplacer_visite:
            nom = chatbot.nom_salle(etat_guide.get("cible")) if etat_guide.get("cible") else "une salle"
            d.update(dire=MESSAGES["deja_en_visite"].replace("{nom}", nom), raison="visite_en_cours")
        else:
            d["guide"] = dict(resultat["guide"])
    elif action == "stop":
        d["stop"] = True
    elif action == "personnalite":
        from atelier.lieu.equipe import personnalite_active
        perso = personnalite_active(personnalites, resultat["personnalite"])
        if perso is None:
            d.update(dire=MESSAGES["personnalite_inconnue"], raison="personnalite_inconnue")
        else:
            d["personnalite"] = perso
    elif action == "geste" and resultat.get("geste") is not None:
        if maitre and maitre.get("maitre") == "pilotage":
            d["raison"] = "pilotage"
        elif etat_guide and etat_guide.get("etat") in ETATS_EN_MISSION:
            d["raison"] = "visite_en_cours"
        else:
            d["geste"] = int(resultat["geste"])
    return d


__all__ = ["Chatbot", "MESSAGES", "MOTS_LIAISON", "NEGATIONS", "PASSE_ENTIERE", "PASSE_PARTIELLE", "decider",
           "en_visite"]
