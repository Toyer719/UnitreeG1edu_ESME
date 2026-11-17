"""Détection YOLO11n, suivi BoT-SORT et encodage corporel OSNet."""
import os
from pathlib import Path

os.environ.setdefault('YOLO_AUTOINSTALL','false')
import torch
from ultralytics import YOLO
from .osnet_encoder import OSNetEncoder


class Tracking:
    def __init__(self, models_dir, device='auto', imgsz=640, threads=4):
        torch.set_num_threads(threads)
        self.device=('cuda:0' if torch.cuda.is_available() else 'cpu') if device=='auto' else device
        if self.device.startswith('cuda') and not torch.cuda.is_available():
            raise RuntimeError('CUDA demandé mais indisponible. Vérifier le pilote et PyTorch, ou utiliser --device cpu.')
        self.imgsz=imgsz
        self.config=str(Path(__file__).with_name('botsort.yaml'))
        models_dir=Path(models_dir)
        paths=[models_dir/'yolo11n.pt',models_dir/'osnet_x0_25_msmt17.pth']
        if any(not p.is_file() for p in paths):
            raise FileNotFoundError('Modèles manquants : lancer python -m suivi_personne.modeles (ou installer.sh).')
        print('Calcul YOLO + OSNet :',self.device,flush=True)
        self.model=YOLO(str(paths[0]))
        self.encoder=OSNetEncoder(paths[1],self.device)
        self.checked=False

    def process(self,frame):
        result=self.model.track(frame,persist=True,tracker=self.config,classes=[0],conf=.1,
                                imgsz=self.imgsz,device=self.device,verbose=False)[0]
        if not self.checked:
            tracker=self.model.predictor.trackers[0]
            if not tracker.args.with_reid or tracker.encoder is None:
                raise RuntimeError('Comparaison d’apparence BoT-SORT inactive')
            self.checked=True
        b=result.boxes
        if b.id is None:return [],[]
        boxes=[(int(i),tuple(map(int,box)),float(c))
               for i,box,c in zip(b.id.tolist(),b.xyxy.tolist(),b.conf.tolist())]
        return boxes,self.encoder.encoder(frame,boxes)
