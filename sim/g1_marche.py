#!/usr/bin/env python3
"""G1 qui marche dans MuJoCo, piloté à la manette ou au clavier.

La marche vient de la politique pré-entraînée d'Unitree (unitree_rl_gym).
Les trois consignes (avancer, glisser, tourner) sont celles que le vrai robot
reçoit avec LocoClient.Move(vx, vy, vyaw).

Manette : stick gauche = avancer / glisser, stick droit = tourner,
          B = stop, A = relever le robot.
Clavier (fenêtre MuJoCo active) : flèches haut/bas = avancer/reculer,
          flèches gauche/droite = tourner, Page préc./suiv. = glisser,
          Fin = stop, Origine = relever le robot.
"""
import argparse
import signal
import sys
import threading
import time
import warnings
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np
import torch
import yaml

RACINE = Path(__file__).resolve().parents[1]
RL_GYM = RACINE / "third_party" / "unitree_rl_gym"
sys.path.insert(0, str(RACINE / "outils"))
from manette import Manette  # noqa: E402

VX_MAX, VY_MAX, WZ_MAX = 0.8, 0.4, 0.8   # m/s, m/s, rad/s
PAS_CLAVIER_V, PAS_CLAVIER_W = 0.1, 0.2
HAUTEUR_CHUTE = 0.45                     # m, hauteur du bassin
PERIODE_PAS = 0.8                        # s, cycle de marche appris par la politique


def charger_config():
    with open(RL_GYM / "deploy/deploy_mujoco/configs/g1.yaml") as f:
        c = yaml.safe_load(f)
    for cle in ("policy_path", "xml_path"):
        c[cle] = c[cle].replace("{LEGGED_GYM_ROOT_DIR}", str(RL_GYM))
    return c


def gravite_projetee(q):
    qw, qx, qy, qz = q
    return np.array([
        2 * (-qz * qx + qw * qy),
        -2 * (qz * qy + qw * qx),
        1 - 2 * (qw * qw + qz * qz),
    ])


class Marcheur:
    def __init__(self, c):
        self.m = mujoco.MjModel.from_xml_path(c["xml_path"])
        self.d = mujoco.MjData(self.m)
        self.dt = c["simulation_dt"]
        self.m.opt.timestep = self.dt
        self.decimation = c["control_decimation"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", FutureWarning)  # torch.jit.load : format du fichier d'Unitree
            self.politique = torch.jit.load(c["policy_path"])
        self.kps = np.array(c["kps"], dtype=np.float32)
        self.kds = np.array(c["kds"], dtype=np.float32)
        self.angles_defaut = np.array(c["default_angles"], dtype=np.float32)
        self.echelles = (c["ang_vel_scale"], c["dof_pos_scale"], c["dof_vel_scale"])
        self.echelle_action = c["action_scale"]
        self.echelle_cmd = np.array(c["cmd_scale"], dtype=np.float32)
        self.n = c["num_actions"]
        self.obs = np.zeros(c["num_obs"], dtype=np.float32)
        self.reinitialiser()

    def reinitialiser(self):
        mujoco.mj_resetData(self.m, self.d)
        self.action = np.zeros(self.n, dtype=np.float32)
        self.cible = self.angles_defaut.copy()
        self.compteur = 0

    def pas(self, cmd):
        """Avance la physique d'un pas ; la politique décide tous les `decimation` pas."""
        self.d.ctrl[:] = (self.cible - self.d.qpos[7:]) * self.kps - self.d.qvel[6:] * self.kds
        mujoco.mj_step(self.m, self.d)
        self.compteur += 1
        if self.compteur % self.decimation:
            return
        e_omega, e_pos, e_vit = self.echelles
        n = self.n
        phase = (self.compteur * self.dt) % PERIODE_PAS / PERIODE_PAS
        o = self.obs
        o[:3] = self.d.qvel[3:6] * e_omega
        o[3:6] = gravite_projetee(self.d.qpos[3:7])
        o[6:9] = cmd * self.echelle_cmd
        o[9:9 + n] = (self.d.qpos[7:] - self.angles_defaut) * e_pos
        o[9 + n:9 + 2 * n] = self.d.qvel[6:] * e_vit
        o[9 + 2 * n:9 + 3 * n] = self.action
        o[9 + 3 * n:9 + 3 * n + 2] = (np.sin(2 * np.pi * phase), np.cos(2 * np.pi * phase))
        with torch.inference_mode():
            self.action = self.politique(torch.from_numpy(o).unsqueeze(0)).numpy().squeeze()
        self.cible = self.action * self.echelle_action + self.angles_defaut

    @property
    def hauteur(self):
        return float(self.d.qpos[2])


class Clavier:
    def __init__(self):
        self.cmd = np.zeros(3, dtype=np.float32)
        self.relever = False

    def touche(self, code):
        g = mujoco.glfw.glfw
        pas = {
            g.KEY_UP: (0, PAS_CLAVIER_V), g.KEY_DOWN: (0, -PAS_CLAVIER_V),
            g.KEY_PAGE_UP: (1, PAS_CLAVIER_V), g.KEY_PAGE_DOWN: (1, -PAS_CLAVIER_V),
            g.KEY_LEFT: (2, PAS_CLAVIER_W), g.KEY_RIGHT: (2, -PAS_CLAVIER_W),
        }
        if code in pas:
            i, v = pas[code]
            self.cmd[i] += v
            self.cmd = np.clip(self.cmd, [-VX_MAX, -VY_MAX, -WZ_MAX], [VX_MAX, VY_MAX, WZ_MAX])
        elif code == g.KEY_END:
            self.cmd[:] = 0
        elif code == g.KEY_HOME:
            self.relever = True


def tester(robot, duree):
    """Marche tout droit à 0,5 m/s sans fenêtre et vérifie que le robot reste debout."""
    cmd = np.array([0.5, 0.0, 0.0], dtype=np.float32)
    hauteur_min = robot.hauteur
    for _ in range(int(duree / robot.dt)):
        robot.pas(cmd)
        hauteur_min = min(hauteur_min, robot.hauteur)
    distance = float(robot.d.qpos[0])
    debout = hauteur_min > HAUTEUR_CHUTE
    print(f"{duree:.0f} s simulées : {distance:.2f} m parcourus, bassin au plus bas à {hauteur_min:.2f} m, "
          f"{'resté debout' if debout else 'TOMBÉ'}")
    return 0 if debout and distance > 0.25 * duree else 1


def main():
    p = argparse.ArgumentParser(description="G1 qui marche dans MuJoCo, piloté à la manette ou au clavier.")
    p.add_argument("--test", type=float, metavar="SECONDES",
                   help="test sans fenêtre : marche tout droit et affiche le bilan")
    args = p.parse_args()

    # Ctrl+C demande l'arrêt : la fenêtre MuJoCo se ferme proprement avant la sortie
    arret = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: arret.set())

    torch.set_num_threads(1)
    robot = Marcheur(charger_config())
    if args.test:
        return tester(robot, args.test)

    manette = Manette()
    clavier = Clavier()
    print(f"Manette : {manette.nom}" if manette.nom else
          "Pas de manette : utilisez le clavier dans la fenêtre MuJoCo.")
    print(__doc__.split("\n\n", 2)[2])

    with mujoco.viewer.launch_passive(robot.m, robot.d, key_callback=clavier.touche) as viewer:
        with viewer.lock():
            viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            viewer.cam.trackbodyid = robot.m.body("pelvis").id
            viewer.cam.distance, viewer.cam.elevation, viewer.cam.azimuth = 3.0, -15.0, 135.0
        cmd = np.zeros(3, dtype=np.float32)
        tombe_signale = False
        prochain_affichage = 0.0
        while viewer.is_running() and not arret.is_set():
            debut = time.perf_counter()
            if robot.compteur % robot.decimation == 0:
                etat = manette.lire()
                if etat is not None and (etat.avant or etat.gauche or etat.rotation or etat.a or etat.b):
                    clavier.cmd[:] = 0
                    cmd = np.array([etat.avant * VX_MAX, etat.gauche * VY_MAX, etat.rotation * WZ_MAX],
                                   dtype=np.float32)
                    if etat.b:
                        cmd[:] = 0
                    if etat.a:
                        clavier.relever = True
                else:
                    cmd = clavier.cmd.copy()
                if clavier.relever:
                    with viewer.lock():
                        robot.reinitialiser()
                    clavier.relever, tombe_signale = False, False

            robot.pas(cmd)

            if robot.compteur % robot.decimation == 0:
                viewer.sync()
                if robot.hauteur < HAUTEUR_CHUTE and not tombe_signale:
                    print("\nLe robot est tombé : A (manette) ou Origine (clavier) pour le relever.")
                    tombe_signale = True
                if debut > prochain_affichage:
                    print(f"\rAvancer {cmd[0]:+.2f} m/s   Glisser {cmd[1]:+.2f} m/s   "
                          f"Tourner {cmd[2]:+.2f} rad/s   ", end="", flush=True)
                    prochain_affichage = debut + 0.2

            reste = robot.dt - (time.perf_counter() - debut)
            if reste > 0:
                time.sleep(reste)
    # La fenêtre MuJoCo se ferme dans un fil d'arrière-plan : sortir avant qu'il ait fini fait planter Python
    for fil in threading.enumerate():
        if fil.daemon and fil is not threading.current_thread():
            fil.join(timeout=3.0)
    print("\nSimulation arrêtée.")
    return 0


if __name__ == "__main__":
    # Message sans conséquence à la fermeture de la fenêtre MuJoCo
    warnings.filterwarnings("ignore", message=".*GLFW library is not initialized")
    sys.exit(main())
