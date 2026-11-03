#!/usr/bin/env python3
"""Télécommande virtuelle Unitree pour la simulation MuJoCo — LE PROJET (G1 EDU).

Ergonomie inspirée du "Virtual Gamepad" d'EngineAI
(engineai_robotics_native_sdk/tools/virtual_gamepad) : interrupteur d'envoi
(F5) avec voyant, groupes Gauche / Centre / Droite, raccourcis clavier,
macros. Code écrit indépendamment, avec tkinter (aucune dépendance en plus).

Envoie un WirelessController_ (format télécommande Unitree) en DDS sur le topic
"rt/virtual_remote", 50 fois par seconde tant que l'envoi est activé. Le
simulateur Python (unitree_mujoco/simulate_python) le recopie dans
lowstate.wireless_remote : deploy_real.py et les exemples SDK le lisent comme
une vraie télécommande. Envoi coupé -> le simulateur remet tout à zéro (0.3 s).

SÉCURITÉ : prévu pour la simulation (interface "lo" par défaut). Le topic
"rt/virtual_remote" n'est pas lu par le vrai robot.

Usage :  python3 virtual_remote.py [--iface lo] [--domain 0]
"""
import argparse
import time
import tkinter as tk
from tkinter import ttk

# ---------------------------------------------------------------------------
# Format télécommande Unitree (bits du champ "keys", cf. KeyMap de deploy_real)
# ---------------------------------------------------------------------------
KEY_BITS = {
    "R1": 0, "L1": 1, "start": 2, "select": 3, "R2": 4, "L2": 5, "F1": 6, "F2": 7,
    "A": 8, "B": 9, "X": 10, "Y": 11, "up": 12, "right": 13, "down": 14, "left": 15,
}
TOPIC = "rt/virtual_remote"
SEND_PERIOD_MS = 20          # 50 Hz
MACRO_HOLD_MS = 400          # durée d'appui d'une macro


class RemoteState:
    """État de la télécommande, indépendant de l'interface graphique."""

    def __init__(self):
        self.buttons = {name: False for name in KEY_BITS}
        self.lx = self.ly = self.rx = self.ry = 0.0

    def keys(self):
        value = 0
        for name, pressed in self.buttons.items():
            if pressed:
                value |= 1 << KEY_BITS[name]
        return value

    def set_stick(self, side, x, y):
        x = max(-1.0, min(1.0, x))
        y = max(-1.0, min(1.0, y))
        if side == "L":
            self.lx, self.ly = x, y
        else:
            self.rx, self.ry = x, y

    def center_sticks(self):
        self.lx = self.ly = self.rx = self.ry = 0.0


class DdsLink:
    """Publication DDS (unitree_sdk2py)."""

    def __init__(self):
        self.publisher = None
        self.msg = None

    def connect(self, domain, iface):
        from unitree_sdk2py.core.channel import ChannelFactoryInitialize, ChannelPublisher
        from unitree_sdk2py.idl.unitree_go.msg.dds_ import WirelessController_
        from unitree_sdk2py.idl.default import unitree_go_msg_dds__WirelessController_
        ChannelFactoryInitialize(domain, iface)
        self.publisher = ChannelPublisher(TOPIC, WirelessController_)
        self.publisher.Init()
        self.msg = unitree_go_msg_dds__WirelessController_()

    def send(self, state: RemoteState):
        self.msg.keys = state.keys()
        self.msg.lx, self.msg.ly = float(state.lx), float(state.ly)
        self.msg.rx, self.msg.ry = float(state.rx), float(state.ry)
        self.publisher.Write(self.msg)


# ---------------------------------------------------------------------------
# Widgets
# ---------------------------------------------------------------------------
class StatusLight(tk.Canvas):
    """Voyant : gris = arrêt, vert clignotant = envoi en cours."""

    def __init__(self, parent):
        super().__init__(parent, width=18, height=18, highlightthickness=0)
        self.dot = self.create_oval(2, 2, 16, 16, fill="grey", outline="")
        self.active = False
        self.blink = False
        self._tick()

    def _tick(self):
        self.blink = not self.blink
        color = ("#2ecc40" if self.blink else "#1e7a2a") if self.active else "grey"
        self.itemconfigure(self.dot, fill=color)
        self.after(300, self._tick)


class StickPad(tk.Canvas):
    """Joystick 2D : se manipule à la souris (glisser), revient au centre au relâchement."""

    SIZE = 130

    def __init__(self, parent, on_change):
        super().__init__(parent, width=self.SIZE, height=self.SIZE, bg="#f4f4f4",
                         highlightthickness=1, highlightbackground="#999")
        s, r = self.SIZE, self.SIZE / 2
        self.create_oval(4, 4, s - 4, s - 4, outline="#bbb")
        self.create_line(r, 4, r, s - 4, fill="#ddd")
        self.create_line(4, r, s - 4, r, fill="#ddd")
        self.knob = self.create_oval(r - 12, r - 12, r + 12, r + 12, fill="#e8603c", outline="")
        self.on_change = on_change
        self.bind("<B1-Motion>", self._drag)
        self.bind("<Button-1>", self._drag)
        self.bind("<ButtonRelease-1>", lambda e: self.on_change(0.0, 0.0))

    def _drag(self, event):
        r = self.SIZE / 2
        x, y = (event.x - r) / (r - 10), -(event.y - r) / (r - 10)
        self.on_change(max(-1, min(1, x)), max(-1, min(1, y)))

    def show(self, x, y):
        r = self.SIZE / 2
        cx, cy = r + x * (r - 14), r - y * (r - 14)
        self.coords(self.knob, cx - 12, cy - 12, cx + 12, cy + 12)


class VirtualRemoteApp:

    # bouton -> touche clavier (clavier AZERTY ; même logique que l'outil EngineAI :
    # A/B/X/Y sur J/K/U/I, gâchettes autour de la croix, SELECT/START sur F1/F2)
    BUTTON_KEYS = {
        "A": "j", "B": "k", "X": "u", "Y": "i",
        "L1": "a", "R1": "e", "L2": "w", "R2": "c",
        "up": "z", "down": "s", "left": "q", "right": "d",
        "select": "F1", "start": "F2",
    }
    # macros pour deploy_real.py (Unitree)
    MACROS = [
        ("1. Posture de départ  [Start]", ("start",)),
        ("2. Marcher  [A]", ("A",)),
        ("Arrêt / amorti  [Select]", ("select",)),
        ("L1 + A", ("L1", "A")),
    ]

    def __init__(self, root, iface, domain):
        self.root = root
        self.state = RemoteState()
        self.link = DdsLink()
        self.connected = False
        self.sending = tk.BooleanVar(value=False)
        self.speed = tk.DoubleVar(value=0.6)
        self.held_keys = set()
        self._release_jobs = {}
        self.button_widgets = {}

        root.title("Télécommande virtuelle G1")
        root.resizable(False, False)
        self._build(iface, domain)
        self._bind_keyboard()
        self._loop()

    # ---------------------------------------------------------------- UI
    def _build(self, iface, domain):
        pad = dict(padx=6, pady=4)

        top = ttk.Frame(self.root)
        top.pack(fill="x", **pad)
        ttk.Label(top, text="Interface :").pack(side="left")
        self.iface_var = tk.StringVar(value=iface)
        self.iface_entry = ttk.Entry(top, textvariable=self.iface_var, width=10)
        self.iface_entry.pack(side="left", padx=4)
        ttk.Label(top, text="Domaine :").pack(side="left")
        self.domain_var = tk.IntVar(value=domain)
        self.domain_entry = ttk.Spinbox(top, from_=0, to=232, textvariable=self.domain_var, width=4)
        self.domain_entry.pack(side="left", padx=4)
        self.connect_btn = ttk.Button(top, text="Connecter", command=self._connect)
        self.connect_btn.pack(side="left", padx=6)
        self.conn_label = ttk.Label(top, text="Déconnecté", foreground="#b00")
        self.conn_label.pack(side="left")

        send = ttk.LabelFrame(self.root, text="Envoi vers le simulateur")
        send.pack(fill="x", **pad)
        self.send_check = ttk.Checkbutton(send, text="Activé (F5)", variable=self.sending,
                                          command=self._on_toggle_send)
        self.send_check.pack(side="left", padx=6, pady=4)
        ttk.Label(send, text="Statut :").pack(side="left", padx=(30, 4))
        self.light = StatusLight(send)
        self.light.pack(side="left")
        ttk.Label(send, text="Vitesse clavier :").pack(side="left", padx=(30, 4))
        ttk.Scale(send, from_=0.1, to=1.0, variable=self.speed, length=110).pack(side="left")
        self.speed_label = ttk.Label(send, width=4)
        self.speed_label.pack(side="left", padx=4)

        body = ttk.Frame(self.root)
        body.pack(fill="x", **pad)

        # --- gauche
        left = ttk.LabelFrame(body, text="Gauche")
        left.pack(side="left", fill="y", padx=4)
        self._button(left, "L2", "L2 (w)").pack(fill="x", padx=6, pady=2)
        self._button(left, "L1", "L1 (a)").pack(fill="x", padx=6, pady=2)
        dpad = ttk.Frame(left)
        dpad.pack(pady=6)
        self._button(dpad, "up", "↑ (z)", 6).grid(row=0, column=1)
        self._button(dpad, "left", "← (q)", 6).grid(row=1, column=0)
        self._button(dpad, "right", "→ (d)", 6).grid(row=1, column=2)
        self._button(dpad, "down", "↓ (s)", 6).grid(row=2, column=1)

        # --- centre
        center = ttk.LabelFrame(body, text="Centre")
        center.pack(side="left", fill="y", padx=4)
        row = ttk.Frame(center)
        row.pack(pady=2)
        self._button(row, "select", "SELECT (F1)").pack(side="left", padx=4)
        self._button(row, "start", "START (F2)").pack(side="left", padx=4)
        sticks = ttk.Frame(center)
        sticks.pack(pady=4)
        self.pads, self.stick_labels = {}, {}
        for col, (side, title) in enumerate([("L", "Stick G : flèches\n(avancer / pas de côté)"),
                                             ("R", "Stick D : Maj+flèches\n(tourner)")]):
            f = ttk.Frame(sticks)
            f.grid(row=0, column=col, padx=6)
            ttk.Label(f, text=title, justify="center").pack()
            self.pads[side] = StickPad(f, lambda x, y, s=side: self._stick_from_mouse(s, x, y))
            self.pads[side].pack()
            self.stick_labels[side] = ttk.Label(f, text="x 0.00   y 0.00", font=("TkFixedFont", 9))
            self.stick_labels[side].pack()
        ttk.Label(center, text="Espace : sticks au centre", foreground="#555").pack()

        # --- droite
        right = ttk.LabelFrame(body, text="Droite")
        right.pack(side="left", fill="y", padx=4)
        self._button(right, "R2", "R2 (c)").pack(fill="x", padx=6, pady=2)
        self._button(right, "R1", "R1 (e)").pack(fill="x", padx=6, pady=2)
        abxy = ttk.Frame(right)
        abxy.pack(pady=6)
        self._button(abxy, "Y", "Y (i)", 6).grid(row=0, column=1)
        self._button(abxy, "X", "X (u)", 6).grid(row=1, column=0)
        self._button(abxy, "B", "B (k)", 6).grid(row=1, column=2)
        self._button(abxy, "A", "A (j)", 6).grid(row=2, column=1)

        macros = ttk.LabelFrame(self.root, text="Macros (deploy_real.py : Start, puis A ; Select pour arrêter)")
        macros.pack(fill="x", **pad)
        for i, (label, combo) in enumerate(self.MACROS):
            ttk.Button(macros, text=label, command=lambda c=combo: self._macro(c)).grid(
                row=0, column=i, padx=4, pady=4, sticky="ew")
            macros.columnconfigure(i, weight=1)

        self.status = ttk.Label(self.root, text="1) Connecter   2) F5 pour activer l'envoi   "
                                                "(la fenêtre doit avoir le focus pour le clavier)",
                                foreground="#555")
        self.status.pack(fill="x", padx=8, pady=(0, 6))

    def _button(self, parent, name, text, width=None):
        b = tk.Button(parent, text=text, width=width or 12, relief="raised", bg="#e9e9e9",
                      activebackground="#e8603c")
        b.bind("<ButtonPress-1>", lambda e: self._set_button(name, True))
        b.bind("<ButtonRelease-1>", lambda e: self._set_button(name, False))
        self.button_widgets[name] = b
        return b

    # ---------------------------------------------------------------- actions
    def _connect(self):
        if self.connected:
            return
        try:
            self.link.connect(int(self.domain_var.get()), self.iface_var.get().strip())
        except Exception as exc:  # interface inconnue, SDK absent...
            self.conn_label.configure(text=f"Erreur : {exc}", foreground="#b00")
            return
        self.connected = True
        self.conn_label.configure(text=f"Connecté ({self.iface_var.get()}, domaine {self.domain_var.get()})",
                                  foreground="#080")
        for w in (self.iface_entry, self.domain_entry, self.connect_btn):
            w.configure(state="disabled")

    def _on_toggle_send(self):
        if self.sending.get() and not self.connected:
            self._connect()
            if not self.connected:
                self.sending.set(False)

    def _toggle_send_key(self, _event=None):
        self.sending.set(not self.sending.get())
        self._on_toggle_send()

    def _set_button(self, name, pressed):
        self.state.buttons[name] = pressed
        w = self.button_widgets.get(name)
        if w is not None:
            w.configure(relief="sunken" if pressed else "raised", bg="#e8603c" if pressed else "#e9e9e9")

    def _macro(self, combo):
        for name in combo:
            self._set_button(name, True)
        self.root.after(MACRO_HOLD_MS, lambda: [self._set_button(n, False) for n in combo])

    def _stick_from_mouse(self, side, x, y):
        self.mouse_stick = side if (x or y) else None
        self.state.set_stick(side, x, y)

    # ---------------------------------------------------------------- clavier
    def _bind_keyboard(self):
        self.mouse_stick = None
        self.root.bind("<KeyPress>", self._key_press)
        self.root.bind("<KeyRelease>", self._key_release)
        self.root.bind("<F5>", self._toggle_send_key)
        self.key_to_button = {v.lower(): k for k, v in self.BUTTON_KEYS.items()}

    def _key_press(self, event):
        key = event.keysym
        job = self._release_jobs.pop(key, None)   # répétition automatique : on annule le relâchement
        if job:
            self.root.after_cancel(job)
        if key == "space":
            self.held_keys.clear()
            self.state.center_sticks()
            return
        self.held_keys.add(key)
        name = self.key_to_button.get(key.lower())
        if name:
            self._set_button(name, True)

    def _key_release(self, event):
        key = event.keysym
        # sous X11 la répétition envoie relâché/appuyé : on attend un peu avant de valider
        self._release_jobs[key] = self.root.after(40, lambda: self._do_release(key))

    def _do_release(self, key):
        self._release_jobs.pop(key, None)
        self.held_keys.discard(key)
        name = self.key_to_button.get(key.lower())
        if name:
            self._set_button(name, False)

    def _sticks_from_keyboard(self):
        if self.mouse_stick:
            return
        k = self.held_keys
        shift = bool({"Shift_L", "Shift_R"} & k)
        dx = (1 if "Right" in k else 0) - (1 if "Left" in k else 0)
        dy = (1 if "Up" in k else 0) - (1 if "Down" in k else 0)
        v = self.speed.get()
        if shift:
            self.state.set_stick("R", dx * v, dy * v)
            self.state.set_stick("L", 0.0, 0.0)
        else:
            self.state.set_stick("L", dx * v, dy * v)
            self.state.set_stick("R", 0.0, 0.0)

    # ---------------------------------------------------------------- boucle 50 Hz
    def _loop(self):
        self._sticks_from_keyboard()
        for side, (x, y) in (("L", (self.state.lx, self.state.ly)), ("R", (self.state.rx, self.state.ry))):
            self.pads[side].show(x, y)
            self.stick_labels[side].configure(text=f"x {x:+.2f}   y {y:+.2f}")
        self.speed_label.configure(text=f"{self.speed.get():.1f}")
        sending = self.sending.get() and self.connected
        self.light.active = sending
        if sending:
            try:
                self.link.send(self.state)
            except Exception as exc:
                self.status.configure(text=f"Erreur d'envoi : {exc}", foreground="#b00")
        self.root.after(SEND_PERIOD_MS, self._loop)


def main():
    parser = argparse.ArgumentParser(description="Télécommande virtuelle Unitree (simulation)")
    parser.add_argument("--iface", default="lo", help="interface réseau DDS (simulation : lo)")
    parser.add_argument("--domain", type=int, default=0, help="domaine DDS (simulateur : 0)")
    parser.add_argument("--autostart", action="store_true", help="connecter et activer l'envoi au lancement")
    args = parser.parse_args()

    root = tk.Tk()
    app = VirtualRemoteApp(root, args.iface, args.domain)
    if args.autostart:
        app._connect()
        app.sending.set(app.connected)
    root.focus_force()
    root.mainloop()


if __name__ == "__main__":
    main()
