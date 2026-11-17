"""Interface de sélection de cible ; aucune commande de robot."""
import queue
import threading
import time
import cv2
from .memoire import MemoireCible

class Viewer:

    def __init__(self, camera, tracker):
        import tkinter as tk
        from PIL import Image, ImageTk
        (self.tk, self.Image, self.ImageTk) = (tk, Image, ImageTk)
        self.root = tk.Tk()
        self.root.title('Suivi personne — YOLO + BoT-SORT + OSNet — ' + camera.label)
        self.status = tk.StringVar(value='Chargement du suivi…')
        tk.Label(self.root, text='Clique dans ton cadre pour verrouiller la cible.', font=('Sans', 14)).pack(pady=6)
        tk.Label(self.root, text='Caméra + apparence corporelle • aucun ordre moteur • aucune reconnaissance faciale').pack()
        tk.Label(self.root, textvariable=self.status, wraplength=960).pack(pady=6)
        body = tk.Frame(self.root)
        body.pack()
        self.canvas = tk.Canvas(body, width=960, height=540, bg='#101826')
        self.canvas.pack(side='left')
        self.canvas.bind('<Button-1>', self.click)
        tk.Button(self.root, text='Désélectionner la cible', command=self.clear).pack(pady=6)
        self.target = None
        self.commands = queue.Queue()
        self.features = {}
        self.memory = MemoireCible()
        self.displayed = []
        self.data = None
        self.lock = threading.Lock()
        self.error = ''
        (self.camera, self.tracker) = (camera, tracker)
        self.stop = threading.Event()
        self.closed = False
        self.last_drawn = 0
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.thread = threading.Thread(target=self.infer, daemon=True)
        self.thread.start()
        self.root.after(100, self.tick)

    def clear(self):
        self.commands.put(('clear', None, None))

    def click(self, event):
        possibles = [(i, box) for (i, box, _) in self.displayed if box[0] <= event.x <= box[2] and box[1] <= event.y <= box[3]]
        if possibles:
            (ident, _) = min(possibles, key=lambda p: (p[1][2] - p[1][0]) * (p[1][3] - p[1][1]))
            feature = self.features.get(ident)
            if feature is None:
                self.commands.put(('wait', None, ident))
                self.status.set('Verrouillage demandé — attente d’une signature exploitable')
                return
            self.commands.put(('select', feature.copy(), ident))
            print('Apparence cible choisie sur piste :', ident, flush=True)

    def infer(self):
        number = 0
        waiting = None
        try:
            while not self.stop.is_set():
                while True:
                    try:
                        (action, feature, ident) = self.commands.get_nowait()
                    except queue.Empty:
                        break
                    if action == 'clear':
                        self.memory.effacer()
                        waiting = None
                    elif action == 'wait':
                        waiting = (ident, time.monotonic() + 3)
                    else:
                        self.memory.choisir(feature, ident, time.monotonic())
                        waiting = None
                data = self.camera.get()
                if data is None or data[0] == number:
                    self.stop.wait(0.02)
                    continue
                (number, received, frame) = data
                if time.monotonic() - received > 1:
                    continue
                start = time.monotonic()
                (boxes, features) = self.tracker.process(frame)
                if waiting is not None:
                    (wanted, deadline) = waiting
                    vector = next((f for (b, f) in zip(boxes, features) if b[0] == wanted and f is not None), None)
                    if vector is not None:
                        self.memory.choisir(vector, wanted, time.monotonic())
                        waiting = None
                    elif time.monotonic() > deadline:
                        waiting = None
                state = self.memory.comparer([(b[0], f) for (b, f) in zip(boxes, features)], time.monotonic())
                if waiting is not None:
                    state['etat'] = 'verrouillage'
                state['galerie'] = len(self.memory.galerie)
                elapsed = time.monotonic() - start
                with self.lock:
                    self.data = (number, received, frame, boxes, elapsed, features, state)
        except Exception as exc:
            self.error = str(exc)

    def tick(self):
        if self.closed:
            return
        with self.lock:
            data = self.data
        if self.error or self.camera.error:
            self.status.set('ERREUR DU SUIVI — ' + self.error if self.error else self.camera.error)
            self.canvas.delete('all')
            self.displayed = []
        elif data and time.monotonic() - data[1] > 2:
            self.status.set('Image périmée — cible non localisée')
            self.canvas.delete('all')
            self.displayed = []
        elif data:
            (number, _, frame, boxes, elapsed, features, state) = data
            self.features = {b[0]: f for (b, f) in zip(boxes, features)}
            self.target = state['piste']
            (h, w) = frame.shape[:2]
            scale = min(960/w,540/h)
            rw,rh = round(w*scale),round(h*scale)
            ox,oy = (960-rw)//2,(540-rh)//2
            self.displayed = [(i, tuple(round(v*scale+(ox if j%2==0 else oy)) for j,v in enumerate(b)), c)
                              for i,b,c in boxes]
            img = self.Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).resize((rw,rh))
            self.photo = self.ImageTk.PhotoImage(img)
            self.canvas.delete('all')
            self.canvas.create_image(ox, oy, anchor='nw', image=self.photo)
            for (ident, (x1, y1, x2, y2), conf) in self.displayed:
                selected = ident == self.target
                color = '#54ff89' if selected else '#ffbd5b'
                self.canvas.create_rectangle(x1, y1, x2, y2, outline=color, width=4 if selected else 2)
                label = ('CIBLE MEMORISEE · ' if selected else '') + f'piste #{ident} · {conf:.0%}'
                self.canvas.create_text(x1 + 4, max(12, y1 - 12), anchor='w', text=label, fill=color, font=('Sans', 13, 'bold'))
            text = {'selection': 'Clique sur une personne pour la mémoriser', 'verrouillage': 'VERROUILLAGE DEMANDÉ — attente d’une signature exploitable', 'visible': 'CIBLE MÉMORISÉE VISIBLE', 'perdue': 'CIBLE NON CONFIRMÉE — mémoire conservée', 'ambigue': 'RESSEMBLANCE AMBIGUË — aucune cible choisie', 'verification': 'RETOUR POSSIBLE — vérification sur plusieurs images'}[state['etat']]
            score = '' if state['score'] is None else f" | similarité {state['score']:.2f}"
            self.status.set(f"{text}{score} | {w}×{h} | {state['galerie']} vue(s) mémorisée(s) | calcul {elapsed * 1000:.0f} ms")
        self.root.after(100, self.tick)

    def close(self):
        if self.closed:
            return
        self.closed = True
        self.stop.set()
        self.thread.join(timeout=5)
        self.camera.close()
        self.root.destroy()
