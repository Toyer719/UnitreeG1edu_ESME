import hashlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from suivi_personne.modeles import telecharger


class TestModeles(unittest.TestCase):
    def test_refuse_empreinte_incorrecte_sans_ecraser(self):
        expected=hashlib.sha256(b'correct').hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'model.pt';path.write_bytes(b'original')
            with patch('suivi_personne.modeles.MODELES',{'model.pt':('https://example.invalid/model',expected)}),patch('urllib.request.urlopen',return_value=io.BytesIO(b'incorrect')):
                with self.assertRaises(RuntimeError):telecharger(tmp)
            self.assertEqual(path.read_bytes(),b'original')
            self.assertEqual(list(Path(tmp).glob('*.part')),[])

    def test_telechargement_et_pas_de_reseau_si_deja_verifie(self):
        data=b'model';expected=hashlib.sha256(data).hexdigest()
        with tempfile.TemporaryDirectory() as tmp:
            with patch('suivi_personne.modeles.MODELES',{'model.pt':('https://example.invalid/model',expected)}),patch('urllib.request.urlopen',return_value=io.BytesIO(data)) as request:
                telecharger(tmp);telecharger(tmp)
                self.assertEqual(request.call_count,1)
            self.assertEqual((Path(tmp)/'model.pt').read_bytes(),data)


if __name__=='__main__':unittest.main()
