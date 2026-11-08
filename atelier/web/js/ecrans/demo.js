// Écran Démo (Équipe › Démo, vague 6, section 13.4 du plan) : lancer et arrêter la démo d'accueil, l'adresse de
// la borne en grand, la personnalité, la voix, le code opérateur, les statistiques. Module de l'agent Borne et
// orchestrateur. Squelette livré par l'agent Contrats : il dit seulement que la démo n'est pas encore faite.
//
// Contrat des écrans (section 12.2) : ouvrir(racine, options) → {modifie(), fermer(), commande(nom, valeur)} ;
// commandes du ruban : lancer (POST /api/demo/lancer), arreter (POST /api/demo/arreter), borne (l'adresse de la
// borne, [data-role=adresse-borne]), reglages (demo.yaml : PUT /api/lieux/{id}/demo). L'état vient du champ demo de
// /ws/etat (dernier /accueil/etat) ; repères : [data-role=demo-etat] (data-etat = l'état de la démo),
// [data-role=demo-statistiques]. Aucune donnée insérée en HTML ; jamais de fenêtre du navigateur.

import { preparerEcran } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  function dessiner(commande) {
    const p = ouvrirPanneau(ecran.panneau, { titre: 'Démo d\'accueil' });
    const etat = F.paragraphe(p.corps, 'La démo d\'accueil arrive bientôt (borne, voix, visite guidée).');
    etat.setAttribute('data-role', 'demo-etat');
    etat.setAttribute('data-etat', 'arretee');
    etat.setAttribute('data-commande-demandee', commande || '');
  }
  dessiner(ecran.commande);
  return {
    modifie: () => false,
    fermer: () => {},
    commande: (nom) => dessiner(nom),
  };
}
