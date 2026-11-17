import argparse
import json
import os
from pathlib import Path
import signal
import time

from . import __version__
from .modeles import dossier_defaut, MODELES, sha256


def main():
    parser=argparse.ArgumentParser(description='YOLO11n + BoT-SORT + OSNet, sélection de cible au clic.')
    parser.add_argument('--version',action='version',version=__version__)
    parser.add_argument('--source',default='0',help='Index webcam, /dev/videoN, fichier, URL MJPEG HTTP ou RTSP')
    parser.add_argument('--device',default='auto',help='auto, cpu ou cuda:0')
    parser.add_argument('--models-dir',type=Path,default=dossier_defaut())
    parser.add_argument('--imgsz',type=int,default=640)
    parser.add_argument('--threads',type=int,default=4)
    parser.add_argument('--width',type=int,default=1280,help='Résolution demandée pour une webcam locale')
    parser.add_argument('--height',type=int,default=720)
    parser.add_argument('--fps',type=int,default=30)
    parser.add_argument('--fourcc',default=None,help='Format webcam facultatif, par exemple YUYV ou MJPG')
    parser.add_argument('--frames',type=int,default=0,help='Traiter N images sans fenêtre')
    parser.add_argument('--timeout',type=float,default=60,help='Délai total maximal du test sans fenêtre')
    parser.add_argument('--diagnostic',action='store_true',help='Afficher versions, GPU et présence des modèles, sans caméra')
    args=parser.parse_args()
    if min(args.imgsz,args.threads,args.width,args.height,args.fps)<=0 or args.frames<0 or args.timeout<=0:
        parser.error('Tailles, cadence, threads et délai doivent être positifs ; frames >= 0')
    if args.fourcc is not None and len(args.fourcc)!=4:parser.error('--fourcc doit contenir quatre caractères')
    if args.device not in ('auto','cpu') and not (args.device.startswith('cuda:') and args.device[5:].isdigit()):
        parser.error('--device : auto, cpu ou cuda:N')
    # Les réglages Ultralytics générés sont distincts des sources Git.
    runtime=Path(os.environ.get('XDG_CACHE_HOME',str(Path.home()/'.cache')))/'suivi-personne/ultralytics'
    os.environ.setdefault('YOLO_CONFIG_DIR',str(runtime))
    from .tracking import Tracking
    from .sources import ouvrir
    if args.diagnostic:
        import torch
        import ultralytics
        print(json.dumps({'version':__version__,'ultralytics':ultralytics.__version__,
                          'torch':torch.__version__,'cuda':torch.cuda.is_available(),
                          'gpu':torch.cuda.get_device_name(0) if torch.cuda.is_available() else None,
                          'models_dir':str(args.models_dir),
                          'modeles':{name:(args.models_dir/name).is_file() for name in MODELES}},indent=2))
        return
    if not args.frames:
        try:import tkinter
        except ImportError:parser.exit(1,'Tkinter manquant : sur Ubuntu/Debian, installer python3-tk.\n')
    camera=None
    try:
        for name,(_,expected) in MODELES.items():
            path=args.models_dir/name
            if not path.is_file():raise FileNotFoundError(f'{name} manquant. Lancer python -m suivi_personne.modeles --models-dir {args.models_dir}')
            if sha256(path)!=expected:raise ValueError(f'Empreinte incorrecte : {name}. Relancer le téléchargement des modèles.')
        tracker=Tracking(args.models_dir,args.device,args.imgsz,args.threads)
        camera=ouvrir(args.source,width=args.width,height=args.height,fps=args.fps,fourcc=args.fourcc)
        if args.frames:
            end=time.monotonic()+args.timeout
            count=number=0
            durations=[]
            while count<args.frames and time.monotonic()<end:
                data=camera.get()
                if data is None or data[0]==number:
                    if camera.finished:break
                    time.sleep(.02)
                    continue
                number,received,frame=data
                start=time.monotonic()
                boxes,features=tracker.process(frame)
                elapsed=time.monotonic()-start
                count+=1;durations.append(elapsed)
                print(json.dumps({'image':count,'resolution':[frame.shape[1],frame.shape[0]],
                                  'ids':[i for i,_,_ in boxes],
                                  'signatures_osnet':sum(f is not None for f in features),
                                  'calcul_ms':round(elapsed*1000)}),flush=True)
            if count!=args.frames:
                raise RuntimeError(f'{count}/{args.frames} images traitées : '+(camera.error or 'fin de vidéo ou délai dépassé'))
            import statistics
            print(f'Test réussi : {count} images, calcul médian {statistics.median(durations)*1000:.0f} ms.')
        else:
            from .viewer import Viewer
            viewer=Viewer(camera,tracker)
            signal.signal(signal.SIGTERM,lambda *_:viewer.root.after(0,viewer.close))
            try:viewer.root.mainloop()
            finally:viewer.close()
    except (OSError,RuntimeError,ValueError) as exc:
        parser.exit(1,f'Erreur : {exc}\n')
    finally:
        if camera is not None:camera.close()


if __name__=='__main__':main()
