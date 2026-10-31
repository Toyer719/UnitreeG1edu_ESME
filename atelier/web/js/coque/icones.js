// Icônes de la coque (vague 5, section 12.2 du plan) : SVG en ligne, 24 × 24, trait de la couleur du
// texte (currentColor), sans bibliothèque. Chaque icône est un gabarit fixe (aucune donnée des fichiers) ;
// icone(nom) renvoie un élément <svg> neuf. Module de l'agent Coquille.

const SVG = 'http://www.w3.org/2000/svg';

// Dessins : du balisage SVG fixe, à l'intérieur d'un <svg viewBox="0 0 24 24">
export const DESSINS = {
  // ---------------------------------------------------------------- barre d'outils et coque
  maison: '<path d="M3 11.5 12 4l9 7.5"/><path d="M5.5 10v9.5h5v-5h3v5h5V10"/>',
  defaire: '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
  refaire: '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
  enregistrer: '<path d="M5 4h11l3 3v13H5z"/><path d="M8 4v5h7V4"/><rect x="8" y="13" width="8" height="5" rx="1"/>',
  theme: '<circle cx="12" cy="12" r="8"/><path d="M12 4a8 8 0 0 1 0 16z" fill="currentColor"/>',
  reglages: '<circle cx="12" cy="12" r="3"/><path d="M12 2.8v3M12 18.2v3M2.8 12h3M18.2 12h3M5.5 5.5l2.1 2.1M16.4 16.4l2.1 2.1M5.5 18.5l2.1-2.1M16.4 7.6l2.1-2.1"/>',
  arret: '<path d="M8 3h8l5 5v8l-5 5H8l-5-5V8z"/><path d="M8.5 12h7" stroke-width="2.6"/>',
  cadenas: '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
  'cadenas-ouvert': '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 7.6-1.7"/>',
  arbre: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/><path d="M5.5 8h1.5M5.5 11h1.5M5.5 14h1.5"/>',
  panneau: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="M15 4v16"/><path d="M17 8h2M17 11h2M17 14h2"/>',
  replier: '<path d="m6 15 6-6 6 6"/>',
  deplier: '<path d="m6 9 6 6 6-6"/>',
  chevron: '<path d="m9 6 6 6-6 6"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  coche: '<path d="m5 12.5 4.5 4.5L19 7.5"/>',
  croix: '<path d="M6 6l12 12M18 6 6 18"/>',
  alerte: '<path d="M12 3.5 2.5 20h19z"/><path d="M12 10v4.5"/><circle cx="12" cy="17.2" r=".6" fill="currentColor"/>',
  info: '<circle cx="12" cy="12" r="9"/><path d="M12 11v6"/><circle cx="12" cy="7.8" r=".6" fill="currentColor"/>',
  messages: '<path d="M4 5h16v11H9l-5 4z"/><path d="M8 9h8M8 12h5"/>',
  console: '<rect x="3" y="4" width="18" height="16" rx="2"/><path d="m7 9 3 3-3 3M12 15h5"/>',
  aide: '<circle cx="12" cy="12" r="9"/><path d="M9.5 9.5a2.5 2.5 0 1 1 3.4 2.3c-.6.3-.9.8-.9 1.5v.7"/><circle cx="12" cy="17" r=".6" fill="currentColor"/>',
  serveur: '<rect x="4" y="4" width="16" height="7" rx="1.5"/><rect x="4" y="13" width="16" height="7" rx="1.5"/><path d="M8 7.5h.01M8 16.5h.01" stroke-width="2.4"/>',
  ros: '<circle cx="6" cy="6" r="2"/><circle cx="18" cy="6" r="2"/><circle cx="12" cy="18" r="2"/><path d="M8 6h8M7 8l4 8M17 8l-4 8"/>',
  batterie: '<rect x="3" y="7" width="16" height="10" rx="2"/><path d="M21 10.5v3"/><path d="M6 10v4M9 10v4" stroke-width="2.4"/>',
  lieu: '<path d="M4 20V8l8-4 8 4v12"/><path d="M9 20v-6h6v6M2.5 20h19"/><path d="M9 10h.01M15 10h.01" stroke-width="2.4"/>',
  etage: '<path d="m12 3 9 5-9 5-9-5z"/><path d="m3 12 9 5 9-5"/><path d="m3 16 9 5 9-5"/>',
  // ---------------------------------------------------------------- vue centrale
  '3d': '<path d="m12 3 8 4.5v9L12 21l-8-4.5v-9z"/><path d="m4 7.5 8 4.5 8-4.5M12 12v9"/>',
  plan: '<path d="m3 6 6-2 6 2 6-2v14l-6 2-6-2-6 2z"/><path d="M9 4v14M15 6v14"/>',
  camera: '<rect x="3" y="7" width="13" height="11" rx="2"/><path d="m16 11 5-3v9l-5-3z"/>',
  dessus: '<rect x="4" y="4" width="16" height="16" rx="2"/><path d="M12 8v8M8 12h8"/>',
  iso: '<path d="m12 4 7 4v8l-7 4-7-4V8z"/><path d="m5 8 7 4 7-4"/>',
  face: '<rect x="5" y="6" width="14" height="12" rx="1"/><path d="M5 18h14"/><path d="M3 21h18"/>',
  recadrer: '<path d="M4 9V4h5M15 4h5v5M20 15v5h-5M9 20H4v-5"/><rect x="9" y="9" width="6" height="6" rx="1"/>',
  calques: '<path d="m12 4 9 5-9 5-9-5z"/><path d="m3 14 9 5 9-5"/>',
  // ---------------------------------------------------------------- Dessiner (monde de la simulation)
  fleche: '<path d="M5 3l13 7.5-5.5 1.5L10 18z"/><path d="m12.5 12 5 6"/>',
  mur: '<rect x="3" y="5" width="18" height="14" rx="1"/><path d="M3 10h18M3 15h18M9 5v5M15 10v5M9 15v4"/>',
  porte: '<path d="M3 20h3V5h4M14 5h4v15h3"/><path d="M10 5v15" stroke-dasharray="2 2"/><path d="M14 5v15" stroke-dasharray="2 2"/>',
  objet: '<path d="M4 10h16v3H4z"/><path d="M6 13v6M18 13v6"/><path d="M7 10V6h10v4"/>',
  pieton: '<circle cx="12" cy="4.5" r="2"/><path d="M12 7v7M12 14l-3 6M12 14l3 6M8 10.5l4-2 4 2"/>',
  depart: '<path d="M6 21V4"/><path d="M6 4h11l-2.5 3.5L17 11H6"/>',
  carte: '<path d="M4 5h16v14H4z"/><path d="M4 12h6v7M10 5v4h6v10M16 9h4"/>',
  // ---------------------------------------------------------------- Placer
  salle: '<path d="M12 21s-6.5-6.2-6.5-11a6.5 6.5 0 0 1 13 0c0 4.8-6.5 11-6.5 11z"/><circle cx="12" cy="10" r="2.3"/>',
  etoile: '<path d="m12 3 2.7 5.6 6.1.9-4.4 4.3 1 6.1L12 17l-5.4 2.9 1-6.1L3.2 9.5l6.1-.9z"/>',
  noeud: '<circle cx="12" cy="12" r="3.5"/><path d="M12 3v5.5M12 15.5V21M3 12h5.5M15.5 12H21"/>',
  relier: '<circle cx="5.5" cy="18.5" r="2.5"/><circle cx="18.5" cy="5.5" r="2.5"/><path d="m7.5 16.5 9-9"/>',
  interdit: '<circle cx="12" cy="12" r="9"/><path d="m5.6 5.6 12.8 12.8"/>',
  lent: '<path d="M4 17a8 8 0 0 1 16 0"/><path d="m12 17 3.5-5"/><path d="M4 17h2M18 17h2M12 9V7"/>',
  zone: '<path d="M4 7l7-3 9 4-2 11-12 1z" stroke-dasharray="3 2"/>',
  // ---------------------------------------------------------------- Simuler et Naviguer
  lancer: '<path d="M7 4.5v15l12-7.5z"/>',
  stop: '<rect x="6" y="6" width="12" height="12" rx="2"/>',
  cible: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3.5"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/>',
  visiteur: '<circle cx="9" cy="7" r="2.5"/><path d="M4.5 20v-4a4.5 4.5 0 0 1 9 0v4"/><circle cx="17" cy="9" r="2"/><path d="M15 20v-3a3.5 3.5 0 0 1 6.5-1.8"/>',
  retour: '<path d="M9 14 4 9l5-5"/><path d="M4 9h11a5 5 0 0 1 0 10h-3"/>',
  scan: '<path d="M4 8V4h4M16 4h4v4M20 16v4h-4M8 20H4v-4"/><path d="M4 12h16" stroke-dasharray="2 2"/><circle cx="12" cy="12" r="2.5"/>',
  valider: '<circle cx="12" cy="12" r="9"/><path d="m7.5 12.5 3 3 6-6.5"/>',
  reperer: '<circle cx="12" cy="10" r="3"/><path d="M12 21s-7-6-7-11a7 7 0 0 1 14 0c0 5-7 11-7 11z"/><path d="M12 1.5v2M3 10H1.5M22.5 10H21"/>',
  position: '<circle cx="12" cy="12" r="3"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/><circle cx="12" cy="12" r="7.5"/>',
  // ---------------------------------------------------------------- Piloter
  main: '<path d="M8 13V5.5a1.5 1.5 0 0 1 3 0V12"/><path d="M11 11V4.5a1.5 1.5 0 0 1 3 0V12"/><path d="M14 11.5V6a1.5 1.5 0 0 1 3 0v8a7 7 0 0 1-7 7h-1a6 6 0 0 1-5-3l-2.3-4a1.6 1.6 0 0 1 2.7-1.7L8 15"/>',
  posture: '<circle cx="12" cy="4" r="2"/><path d="M12 6.5v7M8 9.5l4-2 4 2M12 13.5 9 20M12 13.5l3 6.5"/>',
  geste: '<circle cx="9" cy="5" r="2"/><path d="M9 7.5v7M9 14.5 7 20M9 14.5l2 5.5M9 10l-4 2M9 10l5-4 2-3"/>',
  voix: '<path d="M4 9.5h3l5-4.5v14l-5-4.5H4z"/><path d="M15.5 9a4 4 0 0 1 0 6M18 6.5a7.5 7.5 0 0 1 0 11"/>',
  led: '<path d="M9 17h6M10 20h4"/><path d="M8.5 14A6 6 0 1 1 15.5 14c-.8.7-1 1.6-1 3h-5c0-1.4-.2-2.3-1-3z"/>',
  joystick: '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="3.5"/><path d="M12 4.5v1.5M12 18v1.5M4.5 12H6M18 12h1.5"/>',
  danse: '<circle cx="13" cy="4" r="2"/><path d="M13 6.5 11 13l3 3-1 5M11 13l-4 2-2 5M12.5 8.5l4.5 2.5 3-3M12.5 8.5 8 7 6 4"/>',
  choregraphie: '<path d="M9 18V5l11-2v13"/><circle cx="6.5" cy="18" r="2.5"/><circle cx="17.5" cy="16" r="2.5"/>',
  portique: '<path d="M4 21V4h16v17"/><path d="M12 4v4"/><circle cx="12" cy="10" r="2"/><path d="M12 12v5M9.5 14h5"/>',
  volume: '<path d="M4 9.5h3l5-4.5v14l-5-4.5H4z"/><path d="M16 9.5a3 3 0 0 1 0 5"/><path d="M19 12h2" />',
  spectacle: '<path d="M12 3l2.5 5 5.5.8-4 3.9.9 5.5-4.9-2.6-4.9 2.6.9-5.5-4-3.9 5.5-.8z"/>',
  // ---------------------------------------------------------------- Équipe
  personnalite: '<circle cx="12" cy="12" r="9"/><path d="M8.5 14.5a4.5 4.5 0 0 0 7 0"/><path d="M9 9.5h.01M15 9.5h.01" stroke-width="2.6"/>',
  dialogue: '<path d="M4 5h11v8H8l-4 3.5z"/><path d="M15 9h5v8l-3-2.5h-6v-1.5"/>',
  // ---------------------------------------------------------------- modes (accueil)
  simulation: '<rect x="2.5" y="4" width="19" height="13" rx="2"/><path d="M8 21h8M12 17v4"/><path d="m9 13 3-6 3 6"/>',
  robot: '<rect x="7" y="2.5" width="10" height="7" rx="3"/><path d="M9.5 6h5" stroke-width="2.2"/><path d="M8 11h8l1 6H7z"/><path d="M9.5 17v4.5M14.5 17v4.5M8 12l-3 5M16 12l3 5"/>',
  liaison: '<path d="M2 9a14 14 0 0 1 20 0"/><path d="M5.5 12.5a9 9 0 0 1 13 0"/><path d="M9 16a4 4 0 0 1 6 0"/><circle cx="12" cy="19.5" r=".8" fill="currentColor"/>',
  cable: '<path d="M7 3v5M11 3v5"/><rect x="5" y="8" width="8" height="5" rx="1"/><path d="M9 13v2a4 4 0 0 0 4 4h7"/>',
  telecommande: '<rect x="2.5" y="8" width="19" height="10" rx="5"/><circle cx="7.5" cy="13" r="2"/><circle cx="16.5" cy="13" r="2"/><path d="M8 4v4M16 4v4"/>',
};

// Élément <svg> d'une icône (classe « icone » et « icone-<nom> ») ; une icône inconnue donne un carré
export function icone(nom, taille) {
  const svg = document.createElementNS(SVG, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24');
  svg.setAttribute('width', String(taille || 24));
  svg.setAttribute('height', String(taille || 24));
  svg.setAttribute('fill', 'none');
  svg.setAttribute('stroke', 'currentColor');
  svg.setAttribute('stroke-width', '1.8');
  svg.setAttribute('stroke-linecap', 'round');
  svg.setAttribute('stroke-linejoin', 'round');
  svg.setAttribute('aria-hidden', 'true');
  svg.setAttribute('focusable', 'false');
  // « ico- » et non « icone- » : .icone-fleche est déjà l'épingle orientée des salles sur le plan (atelier.css)
  svg.setAttribute('class', 'icone ico-' + nom);
  svg.innerHTML = Object.prototype.hasOwnProperty.call(DESSINS, nom) ? DESSINS[nom]
    : '<rect x="5" y="5" width="14" height="14" rx="3"/>';
  return svg;
}

// Illustrations des deux cartes de l'accueil (gabarits fixes ; couleurs : classes ill-* de atelier.css,
// qui lisent les jetons du thème)
export const ILLUSTRATIONS = {
  simu: '<svg viewBox="0 0 240 150" aria-hidden="true" class="illustration">'
    + '<rect x="30" y="12" width="180" height="108" rx="10" class="ill-ecran"/>'
    + '<path d="M100 138h40M120 120v18" class="ill-trait"/>'
    + '<path d="M48 104V30h70M140 30h52v74H48M98 30v34h40" class="ill-mur"/>'
    + '<path d="M66 92 C 92 88, 104 62, 128 70 S 168 64, 178 48" class="ill-chemin"/>'
    + '<circle cx="66" cy="92" r="7" class="ill-accueil"/><circle cx="178" cy="48" r="7" class="ill-salle"/>'
    + '<circle cx="118" cy="64" r="9" class="ill-robot"/><path d="M118 64h11" class="ill-cap"/>'
    + '</svg>',
  reel: '<svg viewBox="0 0 240 150" aria-hidden="true" class="illustration">'
    + '<g class="ill-points-bas"><circle cx="34" cy="120" r="2.4"/><circle cx="46" cy="114" r="2.4"/>'
    + '<circle cx="58" cy="122" r="2.4"/><circle cx="70" cy="116" r="2.4"/><circle cx="168" cy="118" r="2.4"/>'
    + '<circle cx="182" cy="124" r="2.4"/><circle cx="196" cy="116" r="2.4"/><circle cx="208" cy="122" r="2.4"/></g>'
    + '<g class="ill-points-milieu"><circle cx="40" cy="96" r="2.4"/><circle cx="52" cy="84" r="2.4"/>'
    + '<circle cx="188" cy="92" r="2.4"/><circle cx="200" cy="80" r="2.4"/></g>'
    + '<g class="ill-points-haut"><circle cx="46" cy="62" r="2.4"/><circle cx="194" cy="56" r="2.4"/>'
    + '<circle cx="206" cy="66" r="2.4"/></g>'
    + '<g class="ill-g1"><rect x="101" y="14" width="38" height="30" rx="13"/><path d="M120 44v6"/>'
    + '<path d="M98 52h44l6 40h-56z"/><path d="M98 56 84 86M142 56l14 30"/><path d="M108 92v40M132 92v40"/>'
    + '<path d="M100 134h14M126 134h14"/></g><path d="M110 29h20" class="ill-visiere"/>'
    + '<path d="M156 30a26 26 0 0 1 36 0M164 38a14 14 0 0 1 20 0" class="ill-onde"/>'
    + '</svg>',
};
