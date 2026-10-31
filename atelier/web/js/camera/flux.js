// Vue de la caméra de poitrine (See3CAM) avec les cadres des visiteurs (vague 5, section 12.7 du
// plan) : le flux MJPEG de GET /api/camera/flux dans une balise <img>, les cadres « boite » de
// /visiteurs/detectes (champ visiteurs de /ws/etat) dessinés par-dessus. Module de l'agent Caméra ;
// squelette livré par l'agent Contrats. La coque s'en sert pour la vue « Caméra » et l'incrustation
// dans Piloter et Naviguer. Repères : [data-role=camera-flux], [data-role=camera-cadres],
// [data-role=camera-etat].

// options : {source: 'poitrine' | 'visiteurs', cadres: true, petit: false (incrustation)}
export function creerVueCamera(conteneur, options) {   // eslint-disable-line no-unused-vars
  return {
    demarrer: () => {},
    arreter: () => {},
    etat: () => ({ actif: false, images: 0, age_s: null }),
    detruire: () => {},
  };
}
