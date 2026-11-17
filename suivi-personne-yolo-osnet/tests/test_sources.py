import io
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import cv2
import numpy as np
from suivi_personne.sources import MJPEGSource, VideoSource


class TestSources(unittest.TestCase):
    def test_reconnexion_efface_image_et_conserve_sequence(self):
        source=MJPEGSource('http://camera.invalid/stream')
        source.latest=(1,0,'ancienne')
        calls=[]
        def attempt():
            calls.append(1)
            if len(calls)==1:raise TimeoutError('timed out')
            self.assertIsNone(source.latest)
            self.assertIn('reconnexion',source.error)
            source.publish(np.zeros((48,64,3),np.uint8))
            source.stop.set()
        with patch.object(source,'read_once',side_effect=attempt),patch.object(source.stop,'wait'):
            source.read()
        self.assertEqual(len(calls),2)
        self.assertEqual(source.error,'')

    def test_mjpeg_avec_ou_sans_content_length(self):
        source=MJPEGSource('http://camera.invalid/stream')
        _,encoded=cv2.imencode('.jpg',np.zeros((48,64,3),np.uint8))
        data=encoded.tobytes()
        for number,header in enumerate([b'Content-Length: '+str(len(data)).encode(),b'Content-Type: image/jpeg'],1):
            payload=b'--frame\r\n'+header+b'\r\n\r\n'+data+b'\r\n'
            with patch('urllib.request.urlopen',return_value=io.BytesIO(payload)):
                with self.assertRaises(EOFError):source.read_once()
            self.assertEqual(source.latest[0],number)
            self.assertEqual(source.latest[2].shape,(48,64,3))

    def test_fichier_video_finit_et_libere_lecteur(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'sample.avi'
            writer=cv2.VideoWriter(str(path),cv2.VideoWriter_fourcc(*'MJPG'),10,(64,48))
            self.assertTrue(writer.isOpened())
            for k in range(4):writer.write(np.full((48,64,3),k*40,np.uint8))
            writer.release()
            source=VideoSource(str(path)).start()
            try:
                source.thread.join(timeout=3)
                self.assertTrue(source.finished)
                self.assertEqual(source.get()[0],4)
                self.assertEqual(source.get()[2].shape,(48,64,3))
            finally:source.close()


if __name__=='__main__':unittest.main()
