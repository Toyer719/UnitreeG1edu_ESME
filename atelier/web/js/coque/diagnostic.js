// « Vérifier le robot » dans l'Atelier (vague 6, section 13.2 du plan) : module de l'agent Diagnostic.
// Squelette livré par l'agent Contrats : les fonctions du contrat existent et ne font encore rien.
//
// Contrat (les outils de la coque : {mode, repetition, lieu, etage, message(texte, genre, details),
// confirmer(texte, options) → promesse, ouvrirCommande(id), api}) :
//   monterDiagnosticAccueil(element, outils) → {rafraichir(), detruire()}
//       sous les vérifications de la carte « Robot réel » de l'accueil : le bouton « Vérifier le robot »
//       ([data-role=verifier-robot]) et le résumé du dernier diagnostic ([data-role=diagnostic-resume]) ;
//   monterDiagnosticBarre(element, outils) → {detruire()}
//       dans la barre d'outils, en Réel (et répétition) seulement : le bouton [data-role=verifier-robot] ;
//   ouvrirDiagnostic(outils) → promesse
//       la fenêtre du diagnostic dans la page ([data-role=diagnostic]) : chaque vérification en
//       [data-verification=<id>][data-etat=ok|attention|probleme|inconnu], sa phrase et, s'il y en a une, le bouton
//       de son action ([data-action=<id>]) qui demande confirmation (outils.confirmer), puis
//       POST /api/robot/diagnostic/<action> {confirme: true} ; « Vérifier à nouveau » ([data-role=reverifier]) ;
//   executer(nom, valeur, outils)
//       la commande du ruban robot.verifier (nom « verifier ») : ouvre la fenêtre du diagnostic.
// Données : GET /api/robot/diagnostic?mode=reel|repetition (schéma diagnostic). Textes simples, sans jargon ROS ;
// aucune donnée insérée en HTML (textContent) ; jamais de fenêtre du navigateur (confirm, alert).

export const ETATS_VERIFICATION = ['ok', 'attention', 'probleme', 'inconnu'];

export function monterDiagnosticAccueil(element, outils) {
  return { rafraichir: () => {}, detruire: () => {} };
}

export function monterDiagnosticBarre(element, outils) {
  return { detruire: () => {} };
}

export function ouvrirDiagnostic(outils) {
  return Promise.resolve(null);
}

export function executer(nom, valeur, outils) {
  if (nom === 'verifier') return ouvrirDiagnostic(outils);
  return null;
}
