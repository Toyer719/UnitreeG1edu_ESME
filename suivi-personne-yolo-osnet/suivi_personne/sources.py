"""Sources vidéo : MJPEG HTTP, webcam, RTSP ou fichier ; dernière image seulement."""
from pathlib import Path
import threading
import time
import urllib.request

import cv2
import numpy as np


class Source:
    def __init__(self,label,timeout=8):
        self.label=label
        self.timeout=timeout
        self.stop=threading.Event()
        self.lock=threading.Lock()
        self.latest=None
        self.error=''
        self.sequence=0
        self.finished=False
        self.thread=threading.Thread(target=self.read,daemon=True)

    def start(self):
        self.thread.start()
        return self

    def publish(self,frame):
        with self.lock:
            self.sequence+=1
            self.latest=self.sequence,time.monotonic(),frame
            self.error=''

    def get(self):
        with self.lock:return self.latest

    def read(self):
        while not self.stop.is_set():
            try:
                self.read_once()
                if self.finished:return
            except Exception as exc:
                if self.stop.is_set():break
                with self.lock:
                    self.latest=None
                    self.error=f'{exc} — reconnexion automatique…'
                self.stop.wait(1)

    def close(self):
        self.stop.set()
        self.thread.join(timeout=self.timeout+1)


class MJPEGSource(Source):
    def __init__(self,url,timeout=8):
        super().__init__('Flux caméra HTTP',timeout)
        self.url=url

    def read_once(self):
        with urllib.request.urlopen(self.url,timeout=self.timeout) as response:
            data=b''
            while not self.stop.is_set():
                chunk=response.read1(65536)
                if not chunk:raise EOFError('Flux interrompu')
                data+=chunk
                while True:
                    start=data.find(b'\xff\xd8')
                    if start<0:
                        data=data[-1:]
                        break
                    end=data.find(b'\xff\xd9',start+2)
                    if end<0:
                        data=data[start:]
                        break
                    jpeg=data[start:end+2]
                    data=data[end+2:]
                    frame=cv2.imdecode(np.frombuffer(jpeg,np.uint8),cv2.IMREAD_COLOR)
                    if frame is not None:self.publish(frame)
                if len(data)>4_000_000:raise ValueError('Image MJPEG trop grande ou invalide')


class VideoSource(Source):
    def __init__(self,source,width=1280,height=720,fps=30,fourcc=None):
        self.source=int(source) if str(source).isdigit() else str(source)
        self.finite=isinstance(self.source,str) and Path(self.source).is_file() and not self.source.startswith('/dev/')
        super().__init__('Fichier vidéo' if self.finite else f'Caméra {source}')
        self.width,self.height,self.fps,self.fourcc=width,height,fps,fourcc

    def read_once(self):
        capture=cv2.VideoCapture()
        try:
            # Ces délais sont pris en charge par FFmpeg pour les flux réseau.
            if isinstance(self.source,str) and self.source.startswith(('rtsp://','rtsps://')):
                opened=capture.open(self.source,cv2.CAP_FFMPEG,
                                   [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC,8000,cv2.CAP_PROP_READ_TIMEOUT_MSEC,8000])
            else:opened=capture.open(self.source)
            if not opened:raise RuntimeError(f'Impossible d’ouvrir la source {self.source}')
            if not self.finite:
                if self.fourcc:capture.set(cv2.CAP_PROP_FOURCC,cv2.VideoWriter_fourcc(*self.fourcc))
                capture.set(cv2.CAP_PROP_FRAME_WIDTH,self.width)
                capture.set(cv2.CAP_PROP_FRAME_HEIGHT,self.height)
                capture.set(cv2.CAP_PROP_FPS,self.fps)
                capture.set(cv2.CAP_PROP_BUFFERSIZE,1)
            fps=capture.get(cv2.CAP_PROP_FPS)
            interval=1/(fps if np.isfinite(fps) and fps>0 else self.fps)
            while not self.stop.is_set():
                start=time.monotonic()
                ok,frame=capture.read()
                if not ok:
                    if self.finite:
                        self.finished=True
                        return
                    raise EOFError('La caméra ne fournit plus d’image')
                self.publish(frame)
                if self.finite:self.stop.wait(max(0,interval-(time.monotonic()-start)))
        finally:capture.release()


def ouvrir(source,**kwargs):
    if str(source).startswith(('http://','https://')):
        return MJPEGSource(str(source)).start()
    return VideoSource(source,**kwargs).start()
