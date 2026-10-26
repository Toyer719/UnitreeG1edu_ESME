#!/usr/bin/env python3
"""Outils du critère 19, le niveau 2 complet en répétition, depuis l'Atelier (section 7 du plan,
critère 19 ; section 10).

  critere_19_outils.py niveau2 --api URL --lieu ID [--conteneur]
      1. POST /api/simulation/demarrer {lieu, etage, mode: repetition} : Gazebo --jumeau (faux G1),
         faux slam_operate, navigation (relais, pont, Nav2, guide) ; attente du relais ;
      2. « Y aller » avant le repérage : 409, message en français ; « Repérer le robot » (marque) ;
         puis attente de Nav2 (bt_navigator actif : il attend map → base_link) ;
      3. aucun lien direct entre /cmd_vel et Gazebo (seul pont_g1 écoute /cmd_vel, seul g1_jumeau
         publie /g1_jumeau/cmd_vel) ;
      4. POST /api/guide/aller b204 : arrive en moins de 180 s, à moins de 0,3 m de b204 (vérité
         terrain /g1_jumeau/odom) ; toutes les requêtes de /api/sport/request sont des 7105,
         comptées, et ont leur réponse ;
      5. une boîte dans le couloir nord, en (12 ; 13), comme au critère 5, puis POST /api/guide/aller
         accueil : bloque → detour → arrive, à moins de 0,3 m de l'accueil ;
      6. /pont/etat et /reperage/etat conformes à leur schéma tout du long.
      --conteneur : la navigation tourne dans le conteneur (E2E_CONTENEUR=1) ; le relais met alors
      plus longtemps à répondre.

La vérité terrain est /g1_jumeau/odom (repère du monde Gazebo = map), jamais /odom (odométrie du
relais). Code de sortie : 0 réussi, 1 échoué (le message dit pourquoi).
"""
import argparse
import json
import math
import subprocess
import sys
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
sys.path.insert(0, str(ICI))

from critere_18_outils import (Echec, Ecoute, appel, attendre_relais, demarrer, francais,  # noqa: E402
                               reperer, verifier)
from outils_pont_e2e import Temoin, format_requetes, Bilan, _nulle  # noqa: E402

DELAI_B204_S = 180.0
DELAI_DETOUR_S = 480.0
TOLERANCE_ARRIVEE_M = 0.3
# La boîte du critère 5 : elle bouche le couloir nord entre amphi et couloir_nord_1
BOITE = ('<sdf version="1.9"><model name="boite_e2e"><static>true</static><link name="l">'
         '<collision name="c"><geometry><box><size>0.5 2.9 1.2</size></box></geometry></collision>'
         '<visual name="v"><geometry><box><size>0.5 2.9 1.2</size></box></geometry></visual>'
         '</link></model></sdf>')


def dire(texte):
    print(f"[critère 19] {texte}", flush=True)


class Observateur(Temoin):
    """Le témoin du pont (requêtes, réponses, vérité, /pont/etat validé), plus /guide/etat."""

    def __init__(self):
        super().__init__('e2e_critere_19')
        from std_msgs.msg import String
        self.guide = []
        self.noeud.create_subscription(String, '/guide/etat', self._guide, 50)

    def _guide(self, m):
        try:
            etat = json.loads(m.data)
        except ValueError:
            return
        with self.verrou:
            self.guide.append((time.monotonic(), etat))

    def guide_depuis(self, t0):
        with self.verrou:
            return [e for t, e in self.guide if t >= t0]

    def nav2_actif(self):
        """bt_navigator actif (Nav2 prêt) ?"""
        from lifecycle_msgs.srv import GetState
        if not hasattr(self, '_client_nav2'):
            self._client_nav2 = self.noeud.create_client(GetState, '/bt_navigator/get_state')
        if not self._client_nav2.wait_for_service(timeout_sec=0.5):
            return False
        futur = self._client_nav2.call_async(GetState.Request())
        fin = time.monotonic() + 3.0
        while not futur.done() and time.monotonic() < fin:
            time.sleep(0.05)
        return bool(futur.done() and futur.result() and futur.result().current_state.label == 'active')

    def liens(self):
        """(abonnés de /cmd_vel, éditeurs de /g1_jumeau/cmd_vel), noms des nœuds."""
        abonnes = sorted({i.node_name for i in self.noeud.get_subscriptions_info_by_topic('/cmd_vel')})
        editeurs = sorted({i.node_name for i in self.noeud.get_publishers_info_by_topic('/g1_jumeau/cmd_vel')})
        return abonnes, editeurs


def verifier_liens(obs):
    time.sleep(1.0)
    abonnes, editeurs = obs.liens()
    dire(f"abonnés à /cmd_vel : {abonnes} ; éditeurs de /g1_jumeau/cmd_vel : {editeurs}")
    verifier(abonnes == ['pont_g1'], f"/cmd_vel doit être écouté par le pont seul (pont_g1), pas {abonnes} : "
                                     "lien direct vers Gazebo ?")
    verifier(editeurs == ['g1_jumeau'], f"/g1_jumeau/cmd_vel doit être publié par g1_jumeau seul, pas {editeurs}")


def pose_salle(lieu, salle):
    from atelier import chemin_lieu
    from atelier.lieu import charger_salles
    s = [s for s in charger_salles(chemin_lieu(lieu)) if s.id == salle]
    verifier(s, f"salle {salle} absente du lieu {lieu}")
    return s[0].pose.x, s[0].pose.y


def aller(api, obs, lieu, cible, delai, suite=()):
    """POST /api/guide/aller, puis attend arrive ; renvoie (durée, écart, requêtes, états vus)."""
    cx, cy = pose_salle(lieu, cible)
    debut = time.monotonic()
    code, r = appel(api, "POST", "/api/guide/aller", {"cible": cible})
    verifier(code == 200 and r.get("ecoute", 0) > 0, f"POST /api/guide/aller {cible} : {code} {r}")
    vus, lus = [], [0]

    def fini():
        etats = obs.guide_depuis(debut)
        for e in etats[lus[0]:]:
            if e.get("cible") == cible and (not vus or vus[-1] != e.get("etat")):
                vus.append(e.get("etat"))
        lus[0] = len(etats)
        return vus and vus[-1] in ("arrive", "echec")
    while time.monotonic() - debut < delai and not fini():
        time.sleep(0.2)
    duree = time.monotonic() - debut
    dire(f"états du guide vers {cible} : {' → '.join(vus) or 'aucun'} ({duree:.0f} s)")
    if vus and vus[-1] == "echec":
        dernier = obs.guide_depuis(debut)[-1]
        raise Echec(f"le guide a échoué vers {cible} : {dernier.get('message', dernier)}")
    verifier(vus and vus[-1] == "arrive", f"pas arrivé à {cible} en {delai:.0f} s (états {vus})")
    reste = iter(vus)
    verifier(all(any(v == s for v in reste) for s in suite),
             f"suite attendue dans l'ordre : {' → '.join(suite)} ; vue : {' → '.join(vus)}")
    time.sleep(1.5)
    x, y, _ = obs.pose()
    ecart = math.hypot(x - cx, y - cy)
    dire(f"arrivé à {cible} en {duree:.0f} s, à {ecart:.3f} m (vérité terrain)")
    verifier(ecart < TOLERANCE_ARRIVEE_M, f"arrivé à {ecart:.3f} m de {cible} (max {TOLERANCE_ARRIVEE_M} m)")
    return duree, ecart, obs.requetes_entre(debut), vus


def bilan_requetes(obs, requetes, quoi):
    """Toutes des 7105 bien formées, avec leur réponse ; au moins 8 par seconde en marche."""
    bilan = Bilan()
    autres = [r for r in requetes if r[2] != 7105]
    verifier(not autres, f"{quoi} : requêtes autres que 7105 sur /api/sport/request : {autres[:3]}")
    format_requetes(requetes, bilan)
    mouvement = [r for r in requetes if not _nulle(r)]
    verifier(len(mouvement) > 50, f"{quoi} : seulement {len(mouvement)} ordres de mouvement 7105")
    repondues = {i for _, i, c in obs.reponses if c == 0}
    sans = [r[1] for r in requetes if r[1] not in repondues]
    verifier(not sans, f"{quoi} : {len(sans)} requêtes 7105 sans réponse de code 0")
    t0, t1 = mouvement[0][0], mouvement[-1][0]
    frequence = (len([r for r in requetes if t0 <= r[0] <= t1]) - 1) / max(1e-6, t1 - t0)
    verifier(frequence >= 8.0, f"{quoi} : {frequence:.1f} requêtes par seconde en marche (8 au moins)")
    verifier(not bilan.erreurs, f"{quoi} : {bilan.erreurs}")
    dire(f"{quoi} : {len(requetes)} requêtes 7105 ({len(mouvement)} de mouvement), {frequence:.1f} par "
         "seconde en marche, toutes répondues : tout le mouvement passe par le pont et le faux G1")


def poser_boite():
    sortie = subprocess.run(['ros2', 'run', 'ros_gz_sim', 'create', '-string', BOITE, '-name', 'boite_e2e',
                             '-x', '12', '-y', '13', '-z', '0.6'], capture_output=True, text=True, timeout=60)
    verifier(sortie.returncode == 0, f"impossible de poser la boîte dans Gazebo : {sortie.stderr[-300:]}")
    dire("boîte posée dans le couloir nord, en (12 ; 13)")


def niveau2(args):
    ecoute = Ecoute()
    obs = Observateur()
    try:
        debut = time.monotonic()
        demarrer(args.api, args.lieu)
        attendre_relais(args.api, ecoute, args.lieu, delai=240 if args.conteneur else 120)
        verifier(obs.attendre_pret(30), "pas de vérité terrain ou de /pont/etat")
        dire(f"répétition prête en {time.monotonic() - debut:.0f} s (relais, pont, faux G1)")
        # 2. « Y aller » avant le repérage, puis « Repérer le robot »
        code, r = appel(args.api, "POST", "/api/guide/aller", {"cible": "b204"})
        verifier(code == 409 and francais(r), f"« Y aller » avant le repérage : {code} {r} (409 attendu)")
        dire(f"« Y aller » avant le repérage : 409 « {r['detail'][:70]}… »")
        code, r, duree = reperer(args.api, {"lieu": args.lieu, "etage": "rdc"})
        verifier(code == 200 and r.get("repere"), f"POST /api/robot/reperer : {code} {r}")
        dire(f"repéré en {duree:.1f} s : {r.get('message')}")
        t_nav2 = time.monotonic()
        while not obs.nav2_actif():
            verifier(time.monotonic() - t_nav2 < 120, "Nav2 (bt_navigator) n'est pas actif 120 s après le repérage")
            time.sleep(0.5)
        dire(f"Nav2 actif {time.monotonic() - t_nav2:.1f} s après le repérage")
        # 3. aucun lien direct /cmd_vel → Gazebo
        verifier_liens(obs)
        # 4. accueil → b204
        _, _, requetes, _ = aller(args.api, obs, args.lieu, "b204", DELAI_B204_S)
        bilan_requetes(obs, requetes, "accueil → b204")
        # 5. couloir nord bouché, retour à l'accueil par le couloir sud
        poser_boite()
        time.sleep(2.0)
        _, _, requetes, _ = aller(args.api, obs, args.lieu, "accueil", DELAI_DETOUR_S,
                                  suite=("bloque", "detour", "arrive"))
        bilan_requetes(obs, requetes, "b204 → accueil avec détour")
        verifier_liens(obs)
        # 6. conformité des messages
        verifier(not obs.non_conformes, f"/pont/etat non conforme : {obs.non_conformes[:2]}")
        verifier(not ecoute.non_conformes, f"/reperage/etat non conforme : {ecoute.non_conformes[:3]}")
        dire(f"{len(obs.etats)} messages /pont/etat et {len(ecoute.etats)} /reperage/etat, tous conformes")
        dire(f"niveau 2 complet en {time.monotonic() - debut:.0f} s")
        return 0
    finally:
        obs.fermer()
        ecoute.fermer()


def main(argv=None):
    p = argparse.ArgumentParser(prog="critere_19_outils.py", description=__doc__.split("\n")[0])
    sous = p.add_subparsers(dest="action", required=True)
    s = sous.add_parser("niveau2")
    s.add_argument("--api", required=True)
    s.add_argument("--lieu", required=True)
    s.add_argument("--conteneur", action="store_true")
    args = p.parse_args(argv)
    try:
        return niveau2(args)
    except Echec as e:
        print(f"[critère 19] ÉCHEC : {e}", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
