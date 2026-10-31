// Carte 3D de l'Atelier (vague 5, section 12.3 du plan) : le nuage de points du scan (ou le monde de
// Gazebo) dans une vue three.js qu'on tourne et déplace à la souris, où l'on pose l'accueil, les salles
// et leur orientation. Module de l'agent Carte 3D ; squelette livré par l'agent Contrats : exports du
// contrat, sans effet. Repère : celui de la carte (map), z vers le haut, sans aucune conversion (x, y
// et theta sont ceux du plan 2D et de salles.yaml) ; le sol est à z = 0 (le nuage d'affichage a déjà
// le plan du sol soustrait).

export const VUES = ['dessus', 'iso', 'face'];
export const CALQUES = ['nuage', 'carte2d', 'monde', 'points', 'itineraires', 'zones', 'robot', 'pietons', 'trajet'];
export const OUTILS = ['naviguer', 'salle', 'accueil', 'noeud', 'mesurer'];
export const HAUTEUR_COUPE = 2.2;      // m : points plus hauts cachés par défaut (plafond)
export const FOND = '#1e1e1e';         // fond de la vue, quel que soit le thème (--vue-fond)

// Crée la carte dans conteneur (élément vide, de taille fixée par la coque). options :
//   {etage (obligatoire : seuls les éléments de cet étage sont montrés), nomGlobal (ex. 'carte3d' :
//    window.carte3d pour les tests), hauteurCoupe (2.2), plafond (false : points au-dessus cachés)}
// Sans WebGL : un message dans le conteneur ([data-role=carte3d-sans-webgl]), etat().webgl faux, et
// toutes les méthodes restent appelables sans effet.
export function creerCarte3D(conteneur, options) {   // eslint-disable-line no-unused-vars
  const rien = () => {};
  const abonner = () => rien;
  return {
    chargerNuage: () => Promise.resolve({ points: 0, bornes: null, grille: null }),  // (url) → {points, bornes, grille}
    afficherPoints: rien,         // (positions Float32Array x y z…, bornes) : nuage déjà en mémoire
    afficherMonde: rien,          // (monde de GET …/monde, {urlMaillage}) : murs, objets, carte extrudée
    afficherCarte2D: rien,        // (url de carte.png, bornes {xmin, ymin, xmax, ymax}) : la carte posée au sol
    afficherSalles: rien,         // (salles de GET …/salles, idPrincipal)
    afficherItineraires: rien,    // ({noeuds, couloirs})
    afficherZones: rien,          // ({interdites, lentes})
    afficherRobot: rien,          // ({x, y, theta} | null)
    afficherPietons: rien,        // ([{id, x, y}])
    afficherTrajet: rien,         // ([[x, y, theta], …]) : trajet du scan
    vue: rien,                    // ('dessus' | 'iso' | 'face')
    recadrer: rien,               // ({xmin, ymin, xmax, ymax} facultatif) : tout voir
    centrerSur: rien,             // (x, y)
    calque: () => true,           // (nom, visible ?) → visible
    coupe: rien,                  // (hauteur en m, ou null : plafond montré)
    outil: rien,                  // ('naviguer' | 'salle' | 'accueil' | 'noeud' | 'mesurer', {id})
    choisir: rien,                // (genre, id) : mettre en valeur un repère (genre : salle, noeud, zone)
    surSelection: abonner,        // (fn({genre, id})) → désabonner
    surPose: abonner,             // (fn({outil, id, x, y, theta, fini})) → désabonner
    surPointeur: abonner,         // (fn({x, y} | null)) → désabonner
    versEcran: () => null,        // (x, y, z = 0) → {x, y} en pixels du conteneur, ou null
    versSol: () => null,          // (px, py) → {x, y} au sol, ou null (on vise le ciel)
    redimensionner: rien,
    etat: () => ({ webgl: false, points: 0, vue: 'iso', outil: 'naviguer', calques: {}, camera: null }),
    detruire: rien,
  };
}
