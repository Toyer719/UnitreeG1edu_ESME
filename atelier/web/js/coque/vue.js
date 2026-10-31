// Vue centrale de l'espace de travail (vague 5, section 12.2 du plan, décision I7) : trois vues,
// choisies dans la barre flottante (« heads-up » de SolidWorks) : 3D (la carte 3D partagée de
// js/carte3d/), Plan 2D (la racine des écrans : leur carte Leaflet, ou leur page) et Caméra (Réel).
// En 3D : vues prédéfinies Dessus, Iso, Face, Recadrer, et les calques. Module de l'agent Coquille.
//
// construireVue(element, {surVue(nom), surCadrage(nom), surCalque(nom, visible), surPlafond(oui)})
//   → {plan, trois, camera, choisir(nom), courante(), permettre(vues), barre(visible), calques(etat),
//      plafond(oui), detruire()}
// Repères : [data-role=vue], [data-role=vue-plan] (racine des écrans), [data-role=vue-3d],
// [data-role=vue-camera], [data-role=barre-vue] avec [data-vue=3d|plan|camera],
// [data-cadrage=dessus|iso|face|recadrer], [data-calque=<nom>].

import { icone } from './icones.js';

export const NOMS_VUES = { '3d': '3D', plan: 'Plan 2D', camera: 'Caméra' };
export const NOMS_CALQUES = {
  nuage: 'Nuage de points', carte2d: 'Carte 2D au sol', monde: 'Monde (murs et meubles)', points: 'Salles et accueil',
  itineraires: 'Itinéraires', zones: 'Zones', robot: 'Robot', pietons: 'Piétons', trajet: 'Trajet du scan',
};
const CADRAGES = [
  { id: 'dessus', libelle: 'Dessus', icone: 'dessus', aide: 'Vue de dessus (Ctrl+5)' },
  { id: 'iso', libelle: 'Iso', icone: 'iso', aide: 'Vue en perspective (Ctrl+7)' },
  { id: 'face', libelle: 'Face', icone: 'face', aide: 'Vue de face (Ctrl+1)' },
  { id: 'recadrer', libelle: 'Recadrer', icone: 'recadrer', aide: 'Tout voir (touche F)' },
];

function el(balise, classe, texte) {
  const e = document.createElement(balise);
  if (classe) e.className = classe;
  if (texte !== undefined && texte !== null) e.textContent = texte;
  return e;
}

function boutonBarre(libelle, nomIcone, aide) {
  const b = el('button', 'bouton-vue');
  b.type = 'button';
  b.title = aide || libelle;
  b.appendChild(icone(nomIcone, 18));
  b.appendChild(el('span', 'bouton-vue-libelle', libelle));
  return b;
}

export function construireVue(element, options) {
  options = options || {};
  element.textContent = '';
  element.classList.add('vue');
  element.setAttribute('data-role', 'vue');
  const plan = el('div', 'vue-calque vue-plan');
  plan.setAttribute('data-role', 'vue-plan');
  const trois = el('div', 'vue-calque vue-3d');
  trois.setAttribute('data-role', 'vue-3d');
  const camera = el('div', 'vue-calque vue-camera');
  camera.setAttribute('data-role', 'vue-camera');
  [plan, trois, camera].forEach((x) => element.appendChild(x));

  // barre flottante
  const barre = el('div', 'barre-vue');
  barre.setAttribute('data-role', 'barre-vue');
  const groupeVues = el('div', 'barre-vue-groupe');
  const boutonsVues = {};
  ['3d', 'plan', 'camera'].forEach((nom) => {
    const b = boutonBarre(NOMS_VUES[nom], nom, nom === '3d' ? 'Vue 3D : tournez (clic gauche), déplacez (clic droit), '
      + 'zoomez (molette)' : (nom === 'plan' ? 'Plan 2D, vu de dessus' : 'Caméra du robot'));
    b.setAttribute('data-vue', nom);
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', () => choisir(nom, true));
    boutonsVues[nom] = b;
    groupeVues.appendChild(b);
  });
  barre.appendChild(groupeVues);
  const groupeCadrages = el('div', 'barre-vue-groupe barre-vue-3d');
  CADRAGES.forEach((c) => {
    const b = boutonBarre(c.libelle, c.icone, c.aide);
    b.setAttribute('data-cadrage', c.id);
    b.addEventListener('click', () => { if (options.surCadrage) options.surCadrage(c.id); });
    groupeCadrages.appendChild(b);
  });
  barre.appendChild(groupeCadrages);
  // calques (menu)
  const groupeCalques = el('div', 'barre-vue-groupe barre-vue-calques');
  const boutonCalques = boutonBarre('Calques', 'calques', 'Ce que montre la vue 3D');
  boutonCalques.setAttribute('aria-haspopup', 'true');
  boutonCalques.setAttribute('aria-expanded', 'false');
  boutonCalques.setAttribute('data-role', 'calques');
  const menuCalques = el('div', 'menu-calques');
  menuCalques.hidden = true;
  const casesCalques = {};
  Object.keys(NOMS_CALQUES).forEach((nom) => {
    const l = el('label', 'menu-calques-ligne');
    const c = el('input');
    c.type = 'checkbox';
    c.setAttribute('data-calque', nom);
    c.addEventListener('change', () => { if (options.surCalque) options.surCalque(nom, c.checked); });
    l.appendChild(c);
    l.appendChild(el('span', '', NOMS_CALQUES[nom]));
    casesCalques[nom] = l;
    menuCalques.appendChild(l);
  });
  const lignePlafond = el('label', 'menu-calques-ligne menu-calques-plafond');
  const casePlafond = el('input');
  casePlafond.type = 'checkbox';
  casePlafond.setAttribute('data-role', 'plafond');
  casePlafond.addEventListener('change', () => { if (options.surPlafond) options.surPlafond(casePlafond.checked); });
  lignePlafond.appendChild(casePlafond);
  lignePlafond.appendChild(el('span', '', 'Afficher le plafond'));
  menuCalques.appendChild(lignePlafond);
  boutonCalques.addEventListener('click', () => {
    menuCalques.hidden = !menuCalques.hidden;
    boutonCalques.setAttribute('aria-expanded', menuCalques.hidden ? 'false' : 'true');
  });
  groupeCalques.appendChild(boutonCalques);
  groupeCalques.appendChild(menuCalques);
  barre.appendChild(groupeCalques);
  element.appendChild(barre);
  function fermerCalques(ev) {
    if (!menuCalques.hidden && !groupeCalques.contains(ev.target)) {
      menuCalques.hidden = true;
      boutonCalques.setAttribute('aria-expanded', 'false');
    }
  }
  document.addEventListener('mousedown', fermerCalques, true);

  let courante = null;
  let permises = ['3d', 'plan', 'camera'];

  function choisir(nom, parUtilisateur) {
    if (permises.indexOf(nom) < 0) nom = permises[0] || 'plan';
    const change = nom !== courante;
    courante = nom;
    plan.hidden = nom !== 'plan';
    trois.hidden = nom !== '3d';
    camera.hidden = nom !== 'camera';
    element.setAttribute('data-vue', nom);
    Object.keys(boutonsVues).forEach((k) => boutonsVues[k].setAttribute('aria-pressed', k === nom ? 'true' : 'false'));
    groupeCadrages.hidden = nom !== '3d';
    groupeCalques.hidden = nom !== '3d';
    if (change && options.surVue) options.surVue(nom, !!parUtilisateur);
    return nom;
  }

  return {
    plan: plan,
    trois: trois,
    camera: camera,
    choisir: (nom) => choisir(nom, false),
    courante: () => courante,
    // vues proposées dans la barre (ex. ['3d', 'plan'] ; [] : barre cachée, la racine de l'écran seule)
    permettre: (vues) => {
      permises = vues && vues.length ? vues.slice() : ['plan'];
      Object.keys(boutonsVues).forEach((k) => { boutonsVues[k].hidden = permises.indexOf(k) < 0; });
      groupeVues.hidden = permises.length < 2;
      // une seule vue (Plan 2D sans WebGL) : pas de barre du tout
      barre.hidden = !vues || permises.length < 2;
      if (permises.indexOf(courante) < 0) choisir(permises[0], false);
    },
    permises: () => permises.slice(),
    calques: (etat, disponibles) => {
      Object.keys(casesCalques).forEach((nom) => {
        casesCalques[nom].hidden = disponibles ? disponibles.indexOf(nom) < 0 : false;
        casesCalques[nom].querySelector('input').checked = etat[nom] !== false;
      });
    },
    plafond: (oui) => { casePlafond.checked = !!oui; },
    detruire: () => {
      document.removeEventListener('mousedown', fermerCalques, true);
      element.textContent = '';
    },
  };
}
