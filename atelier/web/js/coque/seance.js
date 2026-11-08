// La boîte noire dans l'Atelier (vague 6, section 13.3 du plan) : module de l'agent Boîte noire.
// Squelette livré par l'agent Contrats : les fonctions du contrat existent et ne font encore rien.
//
// Contrat (outils de la coque : voir diagnostic.js) :
//   surEspace(outils)
//       appelée par la coque à chaque ouverture de l'espace de travail : en Réel (vrai robot ou répétition),
//       la séance s'ouvre seule (POST /api/seance/demarrer {mode, lieu, etage, ouverture: 'auto'}) ; en
//       Simulation, rien ;
//   monterSeanceBarre(element, outils) → {detruire()}
//       dans la barre d'outils : le badge « ● Enregistrement » ([data-role=seance], data-etat=enregistrement|
//       coupe|arrete) tant qu'une séance est ouverte (champ seance de /ws/etat) ; un clic : le petit menu de la
//       séance (Terminer la séance, Rapport) ;
//   executer(nom, valeur, outils)
//       commandes du ruban seance.terminer (« terminer » : confirmation dans la page, POST /api/seance/arreter,
//       puis le lien du rapport [data-role=rapport-seance]) et seance.rapport (« rapport » : le dernier rapport).
// Textes simples ; aucune donnée insérée en HTML ; jamais de fenêtre du navigateur.

export function surEspace(outils) {
  return null;
}

export function monterSeanceBarre(element, outils) {
  return { detruire: () => {} };
}

export function executer(nom, valeur, outils) {
  // 'terminer' : Terminer la séance ; 'rapport' : le rapport de la dernière séance (squelette : rien encore)
  if ((nom === 'terminer' || nom === 'rapport') && outils && outils.message) {
    outils.message('La boîte noire arrive bientôt : pas encore de séance enregistrée.', 'info');
  }
  return null;
}
