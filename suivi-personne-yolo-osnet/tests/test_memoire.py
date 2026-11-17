import unittest
import numpy as np
from suivi_personne.memoire import MemoireCible


class TestMemoire(unittest.TestCase):
    def test_retour_nouvelle_piste_apres_longue_absence(self):
        m=MemoireCible();m.choisir([1,0,0],1,0)
        self.assertEqual(m.comparer([],1)['etat'],'perdue')
        for t in [60,60.2]:
            self.assertEqual(m.comparer([(1300,[1,0,0])],t)['etat'],'verification')
        self.assertEqual(m.comparer([(1300,[1,0,0])],60.4)['piste'],1300)

    def test_refuse_autre_personne_meme_ancien_id(self):
        m=MemoireCible();m.choisir([1,0,0],1,0)
        for t in [.2,.4,.6]:
            r=m.comparer([(1,[0,1,0])],t)
            self.assertEqual(r['etat'],'perdue')
            self.assertIsNone(r['piste'])
        np.testing.assert_array_equal(m.ancre,[1,0,0])

    def test_ambiguite_et_confirmation_consecutive(self):
        m=MemoireCible();m.choisir([1,0,0],1,0)
        r=m.comparer([(2,[1,0,0]),(3,[.99,.01,0])],2)
        self.assertEqual(r['etat'],'ambigue')
        m.comparer([(2,[1,0,0])],3)
        m.comparer([],3.2)
        self.assertEqual(m.comparer([(2,[1,0,0])],3.4)['etat'],'verification')
        self.assertEqual(len(m.galerie),1)

    def test_effacer_et_memoire_bornee(self):
        m=MemoireCible();m.choisir([1,0,0],1,0)
        for t in range(1,100):m.comparer([(1,[1,0,0])],t/2)
        self.assertLessEqual(len(m.galerie),16)
        m.effacer()
        self.assertEqual(m.comparer([(1,[1,0,0])],100)['etat'],'selection')

    def test_mouvement_assoupli_mais_retour_reste_strict(self):
        m=MemoireCible();m.choisir([1,0,0],1,0)
        v=[.68,np.sqrt(1-.68**2),0]
        self.assertEqual(m.comparer([(1,v)],.2)['etat'],'visible')
        self.assertEqual(m.comparer([(2,v)],.4)['etat'],'perdue')
        self.assertEqual(m.comparer([(1,v)],3)['etat'],'perdue')
        self.assertEqual(len(m.galerie),1)


if __name__=='__main__':unittest.main()
