"""Téléchargements publics épinglés, vérification SHA256 et remplacement atomique."""
import argparse
import hashlib
import os
from pathlib import Path
import tempfile
import urllib.request

MODELES = {
    'yolo11n.pt': (
        'https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo11n.pt',
        '0ebbc80d4a7680d14987a577cd21342b65ecfd94632bd9a8da63ae6417644ee1'),
    'osnet_x0_25_msmt17.pth': (
        'https://huggingface.co/kaiyangzhou/osnet/resolve/a5c5cc037c24235cda3b21085b93ad77c9616224/'
        'osnet_x0_25_msmt17_combineall_256x128_amsgrad_ep150_stp60_lr0.0015_b64_fb10_softmax_labelsmooth_flip_jitter.pth',
        'cf55163d78fc44c62c82f85ab62d39f10438679b5abe8c698ae08cfa84aa6e18'),
}


def dossier_defaut():
    return Path(os.environ.get('SUIVI_MODELS_DIR',
                str(Path.home()/'.cache/suivi-personne/modeles'))).expanduser()


def sha256(path):
    h = hashlib.sha256()
    with open(path,'rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            h.update(chunk)
    return h.hexdigest()


def telecharger(dossier):
    dossier=Path(dossier).expanduser()
    dossier.mkdir(parents=True,exist_ok=True)
    for name,(url,expected) in MODELES.items():
        dest=dossier/name
        if dest.is_file() and sha256(dest)==expected:
            print(f'{name} : déjà vérifié',flush=True)
            continue
        print(f'Téléchargement de {name}…',flush=True)
        temporary=None
        try:
            with tempfile.NamedTemporaryFile(dir=dossier,prefix=name+'.',suffix='.part',delete=False) as out:
                temporary=Path(out.name)
                request=urllib.request.Request(url,headers={'User-Agent':'suivi-personne/0.1'})
                with urllib.request.urlopen(request,timeout=60) as response:
                    while True:
                        data=response.read(1024*1024)
                        if not data:break
                        out.write(data)
            if sha256(temporary)!=expected:
                raise RuntimeError(f'Empreinte SHA256 incorrecte pour {name} ; fichier refusé')
            temporary.replace(dest)
            print(f'{name} : vérifié',flush=True)
        finally:
            if temporary is not None:temporary.unlink(missing_ok=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--models-dir',type=Path,default=dossier_defaut())
    args=parser.parse_args()
    try:telecharger(args.models_dir)
    except Exception as exc:parser.exit(1,f'Échec du téléchargement : {exc}\n')


if __name__=='__main__':main()
