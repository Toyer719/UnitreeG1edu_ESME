"""Les verdicts du diagnostic (vague 6, section 13.2 du plan) : agent Diagnostic.

Des fonctions pures : les faits recueillis par les sondes (sondes.py) → les vérifications du schéma diagnostic
(atelier.lieu.diagnostic.verification), chacune OK, Attention, Problème ou Inconnu, avec UNE phrase qui dit ce qui a
été vu (detail), UNE phrase qui dit quoi faire (conseil, obligatoire hors OK), l'action possible et le détail
technique (infobulle, rapport). Aucun nom de sujet ROS dans detail et conseil : seulement dans technique.

Les vérifications qui dépendent d'une autre la citent dans leur conseil (« Branchez d'abord le câble du robot. ») ;
celles qui n'ont pas pu être faites ici vont dans « ignorees », avec leur raison (en répétition : le réseau et le
Jetson ; sans câble : l'adresse et les pings ; sans réponse du Jetson ou en vérification rapide : le Jetson).
"""
from atelier.lieu.diagnostic import (ADRESSES_ROBOT, BATTERIE_ATTENTION, BATTERIE_PROBLEME, ECART_HORLOGE_MAX_S,
                                     PLACE_JETSON_MIN_GO, PROFIL_RESEAU, SERVICES_CARTOGRAPHIE, STATUT_ACTIF,
                                     SUJETS_SLAM, VERIFICATIONS, VERIFICATIONS_REPETITION, accord_services,
                                     majuscule, noms_services, services_arretes, verification)
from atelier.lieu.pilotage import DANSE_PREFIXE, MODES_COURSE, MODES_MARCHE, nom_mode

from .sondes import COTES_SUJETS, SUJETS_PAR_MODE

PLACE_JETSON_PROBLEME_GO = 1.0       # sous ce seuil, le conteneur ne démarre plus : Problème (Attention sous 5 Go)
USB3_MBPS = 5000
AGE_CAMERA_MAX_S = 3.0
CABLE = "Branchez d'abord le câble du robot."
ROS_D_ABORD = "Commencez par les réglages ROS, plus haut dans la liste."
RELANCER_REPETITION = "Lancez la répétition (Naviguer › Lancer), puis vérifiez à nouveau."
ESSAIS_DETAIL = "Pas pendant les essais : rien n'est envoyé au robot."
ESSAIS_CONSEIL = "Rien à faire : ce point se vérifie avec le vrai robot."
RELIER = "Vérifiez que le robot est allumé et relié (câble, PC1), puis vérifiez à nouveau."


def typographie(texte):
    """Espaces insécables du français : dans les guillemets, et avant « : », « ; », « ? » et « ! » (un signe ne
    commence jamais une ligne)."""
    if not texte:
        return texte
    texte = str(texte).replace("« ", "«\u00a0").replace(" »", "\u00a0»")
    for signe in (":", ";", "?", "!"):
        texte = texte.replace(" " + signe, "\u00a0" + signe)
    return texte


def nombre(x, chiffres=1):
    """Nombre à la française : 0,6 ; 12 ; 3,5."""
    texte = f"{float(x):.{chiffres}f}".rstrip("0").rstrip(".") if chiffres else f"{round(float(x)):d}"
    return texte.replace(".", ",") or "0"


def liste_noms(noms):
    """« a », « a et b », « a, b et c »."""
    noms = list(noms)
    if len(noms) <= 1:
        return "".join(noms)
    return ", ".join(noms[:-1]) + " et " + noms[-1]


def _duree(fait):
    return (fait or {}).get("duree_s")


def _sans_reponse(fait):
    return not fait or fait.get("delai_depasse") or fait.get("sans_reponse")


class Juge:
    """Les verdicts d'un diagnostic : les faits, le mode, la source, et les vérifications déjà jugées."""

    def __init__(self, faits, mode, source="atelier", rapide=False):
        self.faits = faits
        self.mode = mode
        self.source = source
        self.rapide = rapide
        self.verifications = []
        self.ignorees = []
        self.interface = faits.get("_interface") or "eno2"
        self.terminal = source == "g1-diagnostic"

    # ------------------------------------------------------------ outils

    def fait(self, nom):
        return self.faits.get(nom) or {}

    def ajouter(self, ident, etat, detail, conseil=None, action=None, technique=None, fait=None, donnees=None,
                titre=None):
        titre = typographie(titre or VERIFICATIONS.get(ident, ("robot", ident))[1])
        v = verification(ident, etat, typographie(detail), conseil=typographie(conseil), action=action,
                         technique=technique, duree_s=_duree(fait), donnees=donnees, titre=titre)
        self.verifications.append(v)
        return v

    def ignorer(self, ident, raison):
        self.ignorees.append({"id": ident, "raison": raison})

    def trouve(self, ident):
        return next((v for v in self.verifications if v["id"] == ident), None)

    def cable_absent(self):
        """Vrai si, en Réel, le câble n'est sûrement pas branché."""
        if self.mode != "reel":
            return False
        return self.fait("cable").get("carrier") != "1"

    def conseil_robot_muet(self):
        """Quoi faire quand le robot (ou le faux G1) ne répond pas."""
        if self.mode == "repetition":
            return RELANCER_REPETITION
        if self.cable_absent():
            return CABLE
        ros = self.trouve("ros")
        if ros is not None and ros["etat"] != "ok":
            return ROS_D_ABORD
        return RELIER

    def sans_ros(self, ident, fait):
        """Vérification impossible sans ROS 2 (le réglage ros le dit déjà)."""
        quoi = "ce terminal" if self.terminal else "l'Atelier"
        self.ajouter(ident, "inconnu", f"Impossible à vérifier : {quoi} ne voit pas ROS 2.", conseil=ROS_D_ABORD,
                     fait=fait)

    # ------------------------------------------------------------ câble et réseau (Réel)

    def cable(self):
        f = self.fait("cable")
        technique = f"interface {self.interface}, porteuse {f.get('carrier')}, état {f.get('operstate')}"
        if f.get("delai_depasse") or f.get("exception"):
            self.ajouter("cable", "inconnu", "Le câble n'a pas pu être vérifié.",
                         conseil="Vérifiez à nouveau dans quelques secondes.", technique=f.get("erreur"), fait=f)
        elif f.get("carrier") == "1":
            self.ajouter("cable", "ok", "Le câble du robot est branché.", technique=technique, fait=f)
        elif f.get("carrier") == "0":
            self.ajouter("cable", "probleme", "Aucun câble détecté sur le port du robot.",
                         conseil="Branchez le câble Ethernet entre le PC et le robot, puis vérifiez à nouveau.",
                         technique=technique, fait=f)
        elif f.get("operstate") is not None:
            self.ajouter("cable", "attention", "Le port du câble est éteint sur le PC.",
                         conseil="Cliquez sur « Rétablir la connexion du câble », puis vérifiez à nouveau.",
                         action="retablir-cable", technique=technique, fait=f)
        else:
            self.ajouter("cable", "probleme", f"Le PC n'a pas de port réseau « {self.interface} ».",
                         conseil=("Branchez le câble sur le port Ethernet du PC ; s'il porte un autre nom, lancez "
                                  "l'Atelier avec ATELIER_INTERFACE_ROBOT=<son nom>."),
                         technique=technique, fait=f)

    def adresse(self):
        f = self.fait("adresse")
        attendue = ADRESSES_ROBOT["pc"]
        if self.cable_absent():
            self.ignorer("adresse", "le câble n'est pas branché")
            return
        adresse = f.get("adresse")
        technique = f"interface {self.interface} : {adresse or 'aucune adresse IPv4'}"
        if adresse == attendue:
            self.ajouter("adresse", "ok", f"Le PC a l'adresse {attendue} sur le câble.", technique=technique, fait=f)
        elif adresse:
            self.ajouter("adresse", "attention", f"Le PC a l'adresse {adresse} sur le câble, au lieu de {attendue}.",
                         conseil="Cliquez sur « Rétablir la connexion du câble » : elle remet la bonne adresse.",
                         action="retablir-cable", technique=technique, fait=f)
        else:
            profil = self.fait("profil")
            existe = profil.get("code_profil") == 0
            self.ajouter("adresse", "probleme", "Le PC n'a pas encore d'adresse sur le câble du robot.",
                         conseil=("Cliquez sur « Rétablir la connexion du câble »." if existe or not profil else
                                  "Lancez une fois « source ~/robot-g1/setup/robot.sh » dans un terminal."),
                         action="retablir-cable" if existe or not profil else None, technique=technique, fait=f)

    def profil(self):
        f = self.fait("profil")
        technique = (f"nmcli : actives {[a.get('nom') for a in f.get('actives') or []]}, "
                     f"autoconnect {f.get('autoconnect')}")
        if f.get("delai_depasse") or f.get("exception"):
            self.ajouter("profil", "inconnu", "NetworkManager n'a pas répondu à temps.",
                         conseil="Vérifiez à nouveau dans quelques secondes.", technique=f.get("erreur"), fait=f)
            return
        if f.get("code_actives") == 127 and f.get("code_profil") == 127:
            self.ajouter("profil", "inconnu", "NetworkManager (nmcli) est introuvable sur ce PC.",
                         conseil="Reliez le PC au robot avec « source ~/robot-g1/setup/robot.sh ».",
                         technique=technique, fait=f)
            return
        actives = f.get("actives") or []
        active = next((a for a in actives if a.get("nom") == PROFIL_RESEAU), None)
        auto = f.get("autoconnect")
        existe = f.get("code_profil") == 0 or active is not None
        if not existe:
            self.ajouter("profil", "probleme", f"La connexion « {PROFIL_RESEAU} » n'existe pas encore sur ce PC.",
                         conseil=("Dans un terminal, lancez une fois « source ~/robot-g1/setup/robot.sh » : il la "
                                  "crée."),
                         technique=technique + f" ; {f.get('erreur_profil') or ''}".rstrip(" ;"), fait=f)
            return
        if active is not None and active.get("interface") not in (self.interface, ""):
            self.ajouter("profil", "attention",
                         f"La connexion « {PROFIL_RESEAU} » est active sur {active.get('interface')}, pas sur "
                         f"{self.interface}.",
                         conseil=(f"Branchez le câble du robot sur le port {self.interface}, ou lancez l'Atelier "
                                  f"avec ATELIER_INTERFACE_ROBOT={active.get('interface')}."),
                         technique=technique, fait=f)
        elif active is not None and auto == "no":
            self.ajouter("profil", "attention",
                         f"La connexion « {PROFIL_RESEAU} » est active, mais ne se rallume pas seule au branchement.",
                         conseil=("Cliquez sur « La rétablir seule à chaque branchement » pour ne plus avoir à "
                                  "lancer robot.sh."),
                         action="cable-automatique", technique=technique, fait=f)
        elif active is not None:
            self.ajouter("profil", "ok", f"La connexion « {PROFIL_RESEAU} » est active et se rallume seule.",
                         technique=technique, fait=f)
        elif not self.cable_absent():
            self.ajouter("profil", "probleme", f"La connexion « {PROFIL_RESEAU} » du câble est éteinte.",
                         conseil="Cliquez sur « Rétablir la connexion du câble ».", action="retablir-cable",
                         technique=technique, fait=f)
        elif auto == "no":
            self.ajouter("profil", "attention",
                         f"La connexion « {PROFIL_RESEAU} » est éteinte et ne se rallume pas seule.",
                         conseil=("Cliquez sur « La rétablir seule à chaque branchement », puis branchez le câble "
                                  "du robot."),
                         action="cable-automatique", technique=technique, fait=f)
        else:
            self.ajouter("profil", "ok",
                         f"La connexion « {PROFIL_RESEAU} » se rallumera seule au branchement du câble.",
                         technique=technique, fait=f)

    def ros(self):
        f = self.fait("ros")
        quoi = "Ce terminal" if self.terminal else "L'Atelier"
        titre = "Réglages ROS de ce terminal" if self.terminal else None
        relancer = ("Ouvrez un nouveau terminal, faites « source ~/robot-g1/setup/robot.sh », puis relancez "
                    "g1-diagnostic." if self.terminal else
                    "Fermez l'Atelier (Ctrl+C), puis dans le même terminal : « source ~/robot-g1/setup/robot.sh » "
                    "et g1-atelier.")
        domaine = f.get("domaine")
        technique = f"domaine {domaine}, interface de CycloneDDS {f.get('interface_dds') or 'aucune'}"
        if not f.get("pont_actif"):
            self.ajouter("ros", "probleme", f"{quoi} ne voit pas ROS 2.",
                         conseil=("Ouvrez un nouveau terminal (il charge ROS 2), puis relancez g1-diagnostic."
                                  if self.terminal else
                                  "Fermez l'Atelier (Ctrl+C) et relancez-le avec g1-atelier : il charge ROS 2."),
                         technique=f"{technique} ; {f.get('erreur_pont') or 'pont ROS 2 inactif'}", fait=f,
                         titre=titre)
        elif self.mode == "repetition":
            self.ajouter("ros", "ok", f"{quoi} voit ROS 2.", technique=technique, fait=f, titre=titre)
        elif domaine != "0":
            self.ajouter("ros", "probleme", f"{quoi} n'a pas été lancé avec robot.sh (domaine ROS {domaine}).",
                         conseil=relancer, technique=technique, fait=f, titre=titre)
        elif f.get("interface_dds") != self.interface:
            self.ajouter("ros", "attention", "ROS 2 n'est pas attaché au câble du robot.",
                         conseil=relancer, technique=technique, fait=f, titre=titre)
        else:
            self.ajouter("ros", "ok", f"{quoi} est réglé pour le robot.", technique=technique, fait=f, titre=titre)

    def pings(self):
        noms = {"pc1": ("Le PC1", "Vérifiez que le robot est allumé et a fini de démarrer "
                        "(environ une minute), puis vérifiez à nouveau."),
                "jetson": ("Le Jetson", "Attendez la fin du démarrage du robot ; s'il ne répond toujours pas, "
                           "redémarrez le robot."),
                "lidar": ("Le LiDAR", "Attendez la fin du démarrage du robot : sans LiDAR, ni scan ni repérage.")}
        for ident, (qui, conseil) in noms.items():
            f = self.fait(ident)
            technique = f"ping {f.get('adresse')}"
            if f.get("saute") == "cable":
                self.ignorer(ident, "le câble n'est pas branché")
            elif f.get("essais"):
                self.ajouter(ident, "inconnu", ESSAIS_DETAIL, conseil=ESSAIS_CONSEIL, technique=technique, fait=f)
            elif f.get("commande_absente"):
                self.ajouter(ident, "inconnu", "Impossible d'essayer : la commande ping manque sur ce PC.",
                             conseil="Installez-la : « sudo apt install iputils-ping ».", technique=technique,
                             fait=f)
            elif f.get("repond"):
                self.ajouter(ident, "ok", f"{qui} répond en {nombre(f.get('ms') or 0)} ms.",
                             technique=f"{technique} : {f.get('ms')} ms", fait=f)
            elif f.get("delai_depasse") or f.get("exception"):
                self.ajouter(ident, "inconnu", f"{qui} n'a pas pu être essayé à temps.",
                             conseil="Vérifiez à nouveau dans quelques secondes.", technique=f.get("erreur"), fait=f)
            else:
                self.ajouter(ident, "probleme", f"{qui} ne répond pas.", conseil=conseil,
                             technique=f"{technique} : pas de réponse en 1 s", fait=f)

    # ------------------------------------------------------------ le robot (Réel et répétition)

    def sujets(self):
        f = self.fait("sujets")
        if f.get("sans_ros"):
            self.sans_ros("sujets", f)
            return
        if f.get("delai_depasse") or f.get("exception"):
            self.ajouter("sujets", "inconnu", "Le graphe ROS 2 n'a pas pu être lu à temps.",
                         conseil="Vérifiez à nouveau dans quelques secondes.", technique=f.get("erreur"), fait=f)
            return
        vus = f.get("vus") or {}
        robot = SUJETS_PAR_MODE[self.mode]
        slam = list(SUJETS_SLAM)

        def present(sujet):
            return bool((vus.get(sujet) or {}).get(COTES_SUJETS.get(sujet, "publieurs")))

        presents = [s for s in robot if present(s)]
        manquants = [s for s in robot if not present(s)] + [s for s in slam if not present(s)]
        technique = (f"vus : {', '.join(s for s in vus if present(s)) or 'aucun'}"
                     + (f" ; manquants : {', '.join(manquants)}" if manquants else ""))
        qui = "le faux G1" if self.mode == "repetition" else "le robot"
        if not presents:
            detail = "Le PC ne voit pas le faux G1." if self.mode == "repetition" else "Le PC ne reçoit rien du robot."
            self.ajouter("sujets", "probleme", detail, conseil=self.conseil_robot_muet(), technique=technique,
                         fait=f)
        elif len(presents) < len(robot):
            self.ajouter("sujets", "attention",
                         f"Le PC voit {qui}, mais pas tout ({len(presents)} sur {len(robot)}).",
                         conseil=("Attendez quelques secondes que le robot finisse de démarrer, puis vérifiez "
                                  "à nouveau."),
                         technique=technique, fait=f)
        elif any(not present(s) for s in slam):
            if self.mode == "repetition":
                self.ajouter("sujets", "attention",
                             "Le faux G1 répond, mais le faux service de cartographie ne tourne pas.",
                             conseil="Lancez la navigation de la répétition (Naviguer › Lancer) pour pouvoir repérer.",
                             technique=technique, fait=f)
            else:
                services = self.fait("services").get("services")
                actifs = services is not None and not services_arretes(services)
                self.ajouter("sujets", "attention", "Le PC reçoit le robot, mais pas son service de cartographie.",
                             conseil=("Attendez quelques secondes après le démarrage des services, puis vérifiez à "
                                      "nouveau." if actifs else
                                      "Cliquez sur « Démarrer les services de cartographie »."),
                             action=None if actifs else "demarrer-services", technique=technique, fait=f)
        else:
            detail = ("Le PC voit le faux G1 et le faux service de cartographie." if self.mode == "repetition"
                      else "Le PC reçoit le robot et son service de cartographie.")
            self.ajouter("sujets", "ok", detail, technique=technique, fait=f)

    def services(self):
        f = self.fait("services")
        if f.get("sans_ros"):
            self.sans_ros("services", f)
            return
        qui = "Le faux G1" if self.mode == "repetition" else "Le robot"
        if _sans_reponse(f) or (f.get("erreur") and "code" not in f):
            self.ajouter("services", "inconnu", f"{qui} ne répond pas quand on lui demande ses services.",
                         conseil=self.conseil_robot_muet(), technique=f.get("erreur"), fait=f)
            return
        unitree = ("Regardez dans l'appli Unitree Explore (Services) si le LiDAR et la cartographie (lidar_driver, "
                   "unitree_slam) sont actifs.")
        if f.get("code") != 0:
            self.ajouter("services", "inconnu",
                         f"{qui} refuse de donner la liste de ses services (code {f.get('code')}).",
                         conseil=unitree, technique=f"robot_state 1003 : code {f.get('code')}", fait=f)
            return
        if f.get("illisible") or f.get("services") is None:
            self.ajouter("services", "inconnu", f"{qui} a répondu, mais sa liste de services est illisible.",
                         conseil=unitree, technique=f"robot_state 1003 : {f.get('illisible')} ; {f.get('data')}",
                         fait=f)
            return
        services = f["services"]
        statuts = {s["name"]: s["status"] for s in services}
        technique = ("robot_state 1003 : " + ", ".join(f"{n} {statuts.get(n, 'absent')}" for n in SERVICES_CARTOGRAPHIE)
                     + f" (statut {STATUT_ACTIF} = actif)")
        donnees = {"services": services}
        absents = [n for n in SERVICES_CARTOGRAPHIE if n not in statuts]
        arretes = [n for n in services_arretes(services) if n in statuts]
        if not absents and not arretes:
            self.ajouter("services", "ok", f"{majuscule(noms_services(SERVICES_CARTOGRAPHIE, technique=True))} sont "
                                           "actifs.", technique=technique, fait=f, donnees=donnees)
            return
        morceaux = []
        if arretes:     # le nom en français, puis celui de l'appli Unitree (une seule fois, ici)
            morceaux.append(f"{majuscule(noms_services(arretes, technique=True))} "
                            f"{'sont' if len(arretes) > 1 else 'est'} "
                            f"{accord_services(arretes, 'arrêté', 'arrêtée', 'arrêtés')}")
        if absents:
            sujet = qui if not morceaux else qui[0].lower() + qui[1:]
            morceaux.append(f"{sujet} n'a pas de service {liste_noms(f'« {n} »' for n in absents)}")
        detail = " ; ".join(morceaux) + "."
        if arretes:
            conseil = "Cliquez sur « Démarrer les services de cartographie » : sans eux, ni scan ni repérage."
        else:
            conseil = "Regardez le nom du service dans l'appli Unitree Explore (Services) et notez-le pour l'équipe."
        self.ajouter("services", "probleme", detail, conseil=conseil,
                     action="demarrer-services" if arretes else None, technique=technique, fait=f, donnees=donnees)

    def mode_robot(self):
        f = self.fait("mode")
        if f.get("sans_ros"):
            self.sans_ros("mode", f)
            return
        qui = "Le faux G1" if self.mode == "repetition" else "Le robot"
        fsm = f.get("fsm")
        technique = (f"mode {fsm} ({nom_mode(fsm)}), lu {'par le pont' if f.get('source') == 'pont' else 'par 7001'}"
                     if fsm is not None else f"7001 : {f.get('erreur') or f.get('code')}")
        if fsm is None:
            if f.get("code") not in (None, 0):
                self.ajouter("mode", "inconnu", f"{qui} refuse de dire son mode (code {f.get('code')}).",
                             conseil="Vérifiez à nouveau dans quelques secondes.", technique=technique, fait=f)
            else:
                self.ajouter("mode", "inconnu", f"{qui} ne dit pas dans quel mode il est.",
                             conseil=self.conseil_robot_muet(), technique=technique, fait=f)
            return
        donnees = {"fsm": fsm, "nom": nom_mode(fsm)}
        ensuite = "avant de naviguer."
        if fsm in MODES_MARCHE:
            detail = {500: f"{qui} démarre la marche."}.get(fsm, f"{qui} est en mode marche, prêt à se déplacer.")
            self.ajouter("mode", "ok", detail, technique=technique, fait=f, donnees=donnees)
        elif fsm in MODES_COURSE:
            self.ajouter("mode", "attention", f"{qui} est en mode course.",
                         conseil="Passez en marche normale à la télécommande : la navigation ne marche pas en course.",
                         technique=technique, fait=f, donnees=donnees)
        elif DANSE_PREFIXE < fsm < DANSE_PREFIXE + 1000:
            self.ajouter("mode", "attention", f"{qui} est en train de danser.",
                         conseil="Attendez la fin de la danse, puis vérifiez à nouveau.", technique=technique, fait=f,
                         donnees=donnees)
        elif fsm in (0, 1):
            self.ajouter("mode", "attention", f"{qui} n'est pas démarré ({nom_mode(fsm)}).",
                         conseil=f"Démarrez-le avec la télécommande (ou « Démarrer » dans Piloter) {ensuite}",
                         technique=technique, fait=f, donnees=donnees)
        elif fsm == 3:
            self.ajouter("mode", "attention", f"{qui} est assis.",
                         conseil=f"Mettez-le debout puis en marche avec la télécommande {ensuite}",
                         technique=technique, fait=f, donnees=donnees)
        else:
            self.ajouter("mode", "attention", f"{qui} n'est pas en mode marche ({nom_mode(fsm)}).",
                         conseil=f"Mettez-le en marche avec la télécommande (ou « Démarrer » dans Piloter) {ensuite}",
                         technique=technique, fait=f, donnees=donnees)

    def batterie(self):
        f = self.fait("batterie")
        if f.get("sans_ros"):
            self.sans_ros("batterie", f)
            return
        soc = f.get("soc")
        if f.get("type_absent"):
            self.ajouter("batterie", "inconnu", "Ce PC ne sait pas lire la batterie du robot.",
                         conseil="Relancez l'Atelier avec g1-atelier : il charge les messages du robot.",
                         technique=f.get("erreur"), fait=f)
        elif soc is None:
            conseil = ("Attendez quelques secondes, puis « Vérifier à nouveau »." if not self.cable_absent()
                       else CABLE)
            if self.mode == "repetition":
                conseil = RELANCER_REPETITION
            self.ajouter("batterie", "inconnu", "Pas encore de nouvelles de la batterie.", conseil=conseil,
                         technique=f.get("erreur") or "aucun message de batterie reçu", fait=f)
        elif soc < BATTERIE_PROBLEME:
            self.ajouter("batterie", "probleme", f"Batterie à {soc} % : presque vide.",
                         conseil="Rechargez la batterie du robot avant de continuer.", technique=f"soc {soc} %",
                         fait=f, donnees={"soc": soc})
        elif soc < BATTERIE_ATTENTION:
            self.ajouter("batterie", "attention", f"Batterie à {soc} %.",
                         conseil=f"Prévoyez de la recharger bientôt (moins de {BATTERIE_ATTENTION} %).",
                         technique=f"soc {soc} %", fait=f, donnees={"soc": soc})
        else:
            self.ajouter("batterie", "ok", f"Batterie à {soc} %.", technique=f"soc {soc} %", fait=f,
                         donnees={"soc": soc})

    # ------------------------------------------------------------ le Jetson (Réel, un seul ssh)

    def jetson(self):
        f = self.fait("ssh")
        ids = ("jetson_ssh", "jetson_docker", "jetson_image", "jetson_place", "jetson_horloge")
        raisons = {"rapide": "vérification rapide, sans le Jetson", "cable": "le câble n'est pas branché",
                   "jetson": "le Jetson ne répond pas"}
        if f.get("saute") in raisons:
            for ident in ids:
                self.ignorer(ident, raisons[f["saute"]])
            return False
        if f.get("essais"):
            for ident in ids:
                self.ajouter(ident, "inconnu", ESSAIS_DETAIL, conseil=ESSAIS_CONSEIL, technique=f.get("erreur"),
                             fait=f)
            return False
        if f.get("delai_depasse") or f.get("exception") or "code" not in f:
            self.ajouter("jetson_ssh", "inconnu", "Le Jetson n'a pas répondu à temps par SSH.",
                         conseil="Vérifiez à nouveau dans quelques secondes ; si cela dure, redémarrez le robot.",
                         technique=f.get("erreur"), fait=f)
            for ident in ids[1:]:
                self.ignorer(ident, "pas de réponse du Jetson par SSH")
            return False
        erreur = f.get("erreur") or ""
        hote = "unitree@" + ADRESSES_ROBOT["jetson"]
        if f["code"] != 0 and not f.get("complet"):
            copier = f"Dans un terminal : « ssh-copy-id {hote} » (mot de passe 123), une seule fois."
            if "IDENTIFICATION HAS CHANGED" in erreur.upper():
                self.ajouter("jetson_ssh", "probleme", "Le Jetson a changé de clé SSH (réinstallé ?).",
                             conseil=(f"Dans un terminal : « ssh-keygen -R {ADRESSES_ROBOT['jetson']} », puis "
                                      f"« ssh-copy-id {hote} » (mot de passe 123)."),
                             technique=erreur[-300:], fait=f)
            elif "Permission denied" in erreur or "Host key verification failed" in erreur:
                self.ajouter("jetson_ssh", "probleme", "Le Jetson demande un mot de passe : le PC n'a pas sa clé.",
                             conseil=copier, technique=erreur[-300:], fait=f)
            else:
                self.ajouter("jetson_ssh", "inconnu", "Le Jetson ne répond pas par SSH.",
                             conseil="Vérifiez à nouveau dans quelques secondes ; si cela dure, redémarrez le robot.",
                             technique=(erreur or f"code {f['code']}")[-300:], fait=f)
            for ident in ids[1:]:
                self.ignorer(ident, "pas d'accès SSH au Jetson")
            return False
        champs = f.get("champs") or {}
        duree = (f.get("t1") or 0) - (f.get("t0") or 0)
        self.ajouter("jetson_ssh", "ok", "Le PC entre sur le Jetson sans mot de passe.",
                     technique=f"ssh {hote} : {nombre(duree, 2)} s", fait=f)
        # Docker
        if champs.get("docker_ok") == "oui":
            self.ajouter("jetson_docker", "ok", "Docker marche sur le Jetson.", fait=f)
        else:
            self.ajouter("jetson_docker", "probleme", "Docker ne marche pas sur le Jetson sans sudo.",
                         conseil=("Sur le Jetson : « sudo usermod -aG docker unitree », puis reconnectez-vous "
                                  "(docs/jetson.md)."),
                         technique=f"docker_ok={champs.get('docker_ok')}", fait=f)
        self.image(champs, f)
        self.place(champs, f)
        self.horloge(champs, f)
        return True

    def image(self, champs, f):
        if champs.get("docker_ok") != "oui":
            self.ignorer("jetson_image", "Docker ne marche pas sur le Jetson")
            return
        sur_jetson = champs.get("image") or None
        pc = self.fait("image_pc")
        sur_pc = pc.get("empreinte")
        technique = f"empreinte sur le Jetson : {sur_jetson or 'aucune'} ; sur le PC : {sur_pc or 'aucune'}"
        if not sur_jetson:
            conseil = ("Faites « g1-jetson envoyer » (2 à 5 min)." if sur_pc else
                       "Faites « g1-jetson construire », puis « g1-jetson envoyer ».")
            self.ajouter("jetson_image", "probleme", "L'image du conteneur n'est pas sur le Jetson.", conseil=conseil,
                         technique=technique, fait=f)
        elif not sur_pc:
            self.ajouter("jetson_image", "inconnu", "Le PC n'a pas d'image du conteneur pour comparer.",
                         conseil="Faites « g1-jetson construire » sur le PC pour pouvoir comparer.",
                         technique=technique + (f" ; {pc.get('erreur')}" if pc.get("erreur") else ""), fait=f)
        elif sur_jetson == sur_pc:
            self.ajouter("jetson_image", "ok", "Le Jetson a la même image du conteneur que le PC.",
                         technique=technique, fait=f)
        else:
            self.ajouter("jetson_image", "attention", "L'image du conteneur sur le Jetson n'est pas celle du PC.",
                         conseil="Faites « g1-jetson envoyer » pour la mettre à jour (2 à 5 min).",
                         technique=technique, fait=f)

    def place(self, champs, f):
        texte = champs.get("place_docker_ko") or champs.get("place_ko") or ""
        try:
            go = int(texte) * 1024 / 1e9
        except ValueError:
            self.ajouter("jetson_place", "inconnu", "La place libre du Jetson est inconnue.",
                         conseil="Vérifiez à nouveau ; sinon, « g1-jetson verifier » la donne.",
                         technique=f"df : {texte!r}", fait=f)
            return
        technique = f"{nombre(go)} Go libres (Docker : {champs.get('place_docker_ko')} ko, dossier personnel : " \
                    f"{champs.get('place_ko')} ko)"
        if go < PLACE_JETSON_PROBLEME_GO:
            self.ajouter("jetson_place", "probleme", f"Il ne reste que {nombre(go)} Go sur le Jetson.",
                         conseil="Faites de la place sur le Jetson (anciennes images : « docker image prune »).",
                         technique=technique, fait=f, donnees={"go": round(go, 1)})
        elif go < PLACE_JETSON_MIN_GO:
            self.ajouter("jetson_place", "attention", f"Il ne reste que {nombre(go)} Go sur le Jetson.",
                         conseil=(f"Faites de la place (moins de {nombre(PLACE_JETSON_MIN_GO, 0)} Go) : anciennes "
                                  "images, « docker image prune »."),
                         technique=technique, fait=f, donnees={"go": round(go, 1)})
        else:
            self.ajouter("jetson_place", "ok", f"{nombre(go)} Go libres sur le Jetson.", technique=technique, fait=f,
                         donnees={"go": round(go, 1)})

    def horloge(self, champs, f):
        try:
            heure = float(champs.get("heure", ""))
            milieu = ((f.get("t0") or 0) + (f.get("t1") or 0)) / 2.0
            marge = abs((f.get("t1") or 0) - (f.get("t0") or 0)) / 2.0
        except ValueError:
            self.ajouter("jetson_horloge", "inconnu", "L'heure du Jetson est inconnue.",
                         conseil="Vérifiez à nouveau dans quelques secondes.",
                         technique=f"date : {champs.get('heure')!r}", fait=f)
            return
        ecart = heure - milieu
        technique = f"écart {ecart:+.2f} s (± {marge:.2f} s, durée du ssh)"
        if abs(ecart) <= ECART_HORLOGE_MAX_S + marge:
            self.ajouter("jetson_horloge", "ok", "L'heure du Jetson est la même que celle du PC.",
                         technique=technique, fait=f, donnees={"ecart_s": round(ecart, 2)})
        else:
            self.ajouter("jetson_horloge", "attention",
                         f"L'heure du Jetson a {nombre(abs(ecart))} s d'écart avec celle du PC.",
                         conseil=(f"Remettez-le à l'heure : ssh -t unitree@{ADRESSES_ROBOT['jetson']} "
                                  "\"sudo date -s @$(date +%s)\" (mot de passe 123)."),
                         technique=technique, fait=f, donnees={"ecart_s": round(ecart, 2)})

    def camera(self, ssh_fait):
        f = self.fait("camera")
        etat = f.get("etat")
        if isinstance(etat, dict) and (etat.get("age_recu_s") or 0) <= AGE_CAMERA_MAX_S:
            technique = (f"/camera_poitrine/etat : {etat.get('largeur')}×{etat.get('hauteur')}, "
                         f"{etat.get('ips_mesuree')} images/s, {etat.get('peripherique')}")
            if etat.get("ouverte"):
                self.ajouter("camera", "ok", "La caméra de poitrine envoie ses images.", technique=technique, fait=f)
            else:
                self.ajouter("camera", "attention", "La caméra de poitrine ne donne pas d'image.",
                             conseil="Vérifiez son câble USB (port bleu du Jetson), puis relancez la navigation.",
                             technique=f"{technique} ; {etat.get('erreur')}", fait=f)
            return
        s = self.fait("ssh")
        if not ssh_fait:
            if s.get("essais"):
                self.ajouter("camera", "inconnu", ESSAIS_DETAIL, conseil=ESSAIS_CONSEIL, technique=s.get("erreur"),
                             fait=f)
            else:
                raison = {"rapide": "vérification rapide, sans le Jetson", "cable": "le câble n'est pas branché"}
                self.ignorer("camera", raison.get(s.get("saute"), "le Jetson n'a pas pu être vérifié"))
            return
        cameras = s.get("cameras") or []
        if not cameras:
            self.ajouter("camera", "attention", "La caméra See3CAM n'est pas branchée sur le Jetson.",
                         conseil="Branchez-la sur un port USB 3 (bleu) du Jetson pour voir les visiteurs.",
                         technique="aucun /dev/v4l/by-id/*See3CAM* sur le Jetson", fait=s)
            return
        c = cameras[0]
        technique = f"{c.get('by_id')} → {c.get('chemin')}, USB {c.get('usb_mbps')} Mbit/s"
        if c.get("usb_mbps") is not None and c["usb_mbps"] < USB3_MBPS:
            self.ajouter("camera", "attention", "La caméra See3CAM est branchée en USB 2 : l'image sera saccadée.",
                         conseil="Branchez-la sur un port USB 3 (bleu) du Jetson.", technique=technique, fait=s)
        else:
            self.ajouter("camera", "ok", "La caméra See3CAM est branchée sur le Jetson.", technique=technique, fait=s)

    # ------------------------------------------------------------ tout

    def juger(self):
        """(verifications dans l'ordre de VERIFICATIONS, ignorees)."""
        if self.mode == "reel":
            self.cable()
            self.adresse()
            self.profil()
        self.ros()
        if self.mode == "reel":
            self.pings()
        self.services()          # avant sujets : le conseil des sujets regarde les services
        self.sujets()
        self.mode_robot()
        self.batterie()
        if self.mode == "reel":
            ssh_fait = self.jetson()
            self.camera(ssh_fait)
        else:
            for ident in VERIFICATIONS:
                if ident not in VERIFICATIONS_REPETITION:
                    self.ignorer(ident, "sans objet en répétition")
        ordre = list(VERIFICATIONS)
        self.verifications.sort(key=lambda v: ordre.index(v["id"]) if v["id"] in ordre else len(ordre))
        self.ignorees.sort(key=lambda v: ordre.index(v["id"]) if v["id"] in ordre else len(ordre))
        return self.verifications, self.ignorees


def juger(faits, mode, source="atelier", rapide=False):
    """(verifications, ignorees) d'après les faits des sondes (fonction pure)."""
    return Juge(faits, mode, source=source, rapide=rapide).juger()
