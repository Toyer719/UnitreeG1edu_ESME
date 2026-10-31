// Écran Carte (arbre › Carte, Dessiner › Avancé › Refaire la carte) : la carte 2D du robot sur le plan
// (Leaflet, CRS.Simple, coordonnées en mètres) et ses informations dans le panneau. En Simulation, elle se
// fabrique depuis le monde inventé (g1-monde generer) ; elle se refait seule après « Enregistrer » du monde
// et des zones. Pour un étage scanné, « Refaire » ne touche pas la carte du scan : il refait le masque des
// zones interdites et le monde de simulation.

import { api, urlEtage } from '../api.js';
import { contexte, etageCourant, rechargerLieu } from '../contexte.js';
import { preparerEcran } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import { nb } from '../geometrie.js';
import { afficherErreur, afficherRapport } from '../messages.js';
import { creerPlan } from '../plan.js';

// Légende de la carte du plan : en thème sombre, l'image est inversée (atelier.css : obstacles clairs sur
// fond sombre) ; la légende dit donc ce qu'on voit, dans les deux thèmes
export function legendeCarte(theme) {
  return theme === 'clair' ? 'Noir : obstacle ; blanc : libre ; gris : inconnu. Le robot s\'en sert pour se déplacer.'
    : 'Clair : obstacle ; sombre : libre ; gris : inconnu (thème sombre). Le robot s\'en sert pour se déplacer.';
}

function themeCourant() {
  return document.documentElement.getAttribute('data-theme') === 'clair' ? 'clair' : 'sombre';
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  ecran.vue.innerHTML = '<div class="plan" data-role="plan"></div>';
  const plan = creerPlan(ecran.vue.querySelector('[data-role=plan]'));
  let info = null;
  let enCours = false;

  function scannee() {
    const e = etageCourant();
    return !!(e && e.source_carte === 'scan');
  }

  function afficherInfos() {
    const p = ouvrirPanneau(ecran.panneau, { titre: 'Carte du robot', aide: legendeCarte(themeCourant()) });
    const z = p.corps;
    if (!info) {
      F.paragraphe(z, 'Pas encore de carte pour cet étage.' + (scannee() ? ' Faites un scan (Scanner › Scan).'
        : ' Dessinez le monde (Dessiner), puis enregistrez : la carte se fait seule.'));
    } else {
      const b = info.bornes;
      F.valeur(z, 'Faite depuis', scannee() ? 'le scan du robot' : 'le monde dessiné');
      F.valeur(z, 'Surface', nb(b.xmax - b.xmin, 1) + ' × ' + nb(b.ymax - b.ymin, 1) + ' m');
      F.valeur(z, 'Précision', nb(info.resolution * 100, 1) + ' cm par point');
      if (info.modifiee) F.valeur(z, 'Faite le', new Date(info.modifiee * 1000).toLocaleString('fr-FR'));
      const d = F.el('details', 'bloc-avance');
      d.appendChild(F.el('summary', '', 'Avancé'));
      F.valeur(d, 'Image', info.largeur + ' × ' + info.hauteur + ' pixels');
      F.valeur(d, 'Coin bas gauche', '[' + nb(b.xmin, 2) + ' ; ' + nb(b.ymin, 2) + '] m');
      F.valeur(d, 'Fichier', 'cartes/' + etage + '.yaml, ' + info.image);
      z.appendChild(d);
    }
    const ligne = F.el('div', 'formulaire-ligne');
    const b = F.bouton(ligne, scannee() ? 'Refaire le masque des zones' : 'Refaire la carte', refaire, 'bouton bouton-principal');
    b.setAttribute('data-role', 'fabriquer');
    b.disabled = enCours;
    z.appendChild(ligne);
    if (scannee()) F.paragraphe(z, 'La carte du scan reste telle quelle.', 'panneau-note');
  }

  async function afficher() {
    try {
      const r = await plan.afficherFond(lieu, etage);
      info = r.info;
    } catch (e) {
      afficherErreur(e);
    }
    afficherInfos();
  }

  async function refaire() {
    if (enCours) return;
    enCours = true;
    afficherInfos();
    coque.message('Fabrication de la carte… (quelques secondes)', 'info');
    try {
      const r = await api.envoyer(urlEtage(lieu, etage) + '/monde/generer');
      const faits = [];
      if (r.fichiers.carte) faits.push('carte du robot');
      if (r.fichiers.interdit) faits.push('masque des zones interdites');
      if (r.fichiers.sdf) faits.push('monde de Gazebo');
      coque.message('Fait en ' + nb(r.duree_s, 1) + ' s : ' + faits.join(', ') + '.', 'succes', [], r.sortie);
      afficherRapport(r.rapport);
      plan.cadre_initial = false;
      rechargerLieu().catch(() => {});
      coque.lieuModifie('carte');
    } catch (err) {
      afficherErreur(err);
    } finally {
      enCours = false;
      await afficher();
    }
  }

  // la légende suit le thème
  const surTheme = () => afficherInfos();
  document.addEventListener('atelier-theme', surTheme);

  ecran.vue.classList.add('chargement');
  const pret = afficher().finally(() => ecran.vue.classList.remove('chargement'));
  if (ecran.commande === 'refaire') pret.then(refaire);
  return {
    modifie: () => false,
    commande: (nom) => { if (nom === 'refaire') refaire(); },
    vue: () => {
      plan.carte.invalidateSize();
      if (plan.cadrageEnAttente) plan.recadrer();
    },
    recadrer: () => { if (info) plan.cadrer(info.bornes.xmin, info.bornes.ymin, info.bornes.xmax, info.bornes.ymax); },
    fermer: () => {
      document.removeEventListener('atelier-theme', surTheme);
      plan.detruire();
    },
  };
}
