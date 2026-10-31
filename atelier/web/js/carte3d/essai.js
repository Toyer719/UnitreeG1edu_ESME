// Page d'essai de la carte 3D (essais/carte3d.html, vague 5, section 12.3 du plan) : la carte seule, sans
// la coque, sur un lieu de l'Atelier. Jamais liée par l'interface ; sert aux tests dans Firefox sans
// fenêtre et aux captures. Adresse : /essais/carte3d.html?lieu=demo[&etage=rdc][&mode=reel|simu]
// [&nuage=URL|0][&direct=1][&global=carte3d][&image=1][&animation=0][&barre=0] ; ?vide=1 : rien (tests).
//   mode reel : le nuage de l'étage (GET …/nuage) et la carte 2D au sol ; mode simu : le monde en volumes et
//   la carte 2D au sol ; par défaut, reel si l'étage est scanné (source_carte: scan), simu sinon ;
//   nuage=0 : pas de nuage (un test le charge lui-même) ; direct=1 : robot et piétons de /ws/etat.
// Expose window.carte3d (la carte), window.edition3d (édition des salles) et window.essaiCarte3d
// ({pret, nuage, erreurs}) pour les tests.

import { api, urlEtage, urlLieu } from '../api.js';
import { creerCarte3D } from './carte3d.js';
import { suivreEnDirect } from './direct3d.js';
import { creerEditionSalles } from './edition.js';

const parametres = new URLSearchParams(location.search);
const $ = (role) => document.querySelector('[data-role="' + role + '"]');
const essai = { pret: false, nuage: null, monde: null, carte2d: null, erreurs: [] };
window.essaiCarte3d = essai;

function message(texte, genre) {
  const m = $('etat-message');
  m.textContent = texte;
  m.className = 'essai-message essai-' + (genre || 'info');
}

function noterErreur(quoi, e) {
  const texte = quoi + ' : ' + ((e && e.message) || e);
  essai.erreurs.push(texte);
  return texte;
}

async function demarrer() {
  if (parametres.get('vide') === '1') {          // page vide (avec l'importmap) : tests des fonctions seules
    essai.pret = true;
    document.body.setAttribute('data-pret', '1');
    return;
  }
  const lieu = parametres.get('lieu') || 'demo';
  const info = await api.lire(urlLieu(lieu));
  const etage = parametres.get('etage') || (info.etages[0] && info.etages[0].id);
  const etageInfo = info.etages.find((e) => e.id === etage) || {};
  const mode = parametres.get('mode') || (etageInfo.source_carte === 'scan' ? 'reel' : 'simu');
  $('essai-lieu').textContent = (info.nom || lieu) + ' · ' + (etageInfo.nom || etage) + ' · '
    + (mode === 'reel' ? 'Réel (nuage du scan)' : 'Simulation (monde)');
  document.body.setAttribute('data-mode', mode);

  const carte = creerCarte3D($('vue-3d'), { etage: etage, nomGlobal: parametres.get('global') || 'carte3d',
    barre: parametres.get('barre') !== '0', conserverImage: parametres.get('image') === '1',
    animation: parametres.get('animation') !== '0' });
  const edition = creerEditionSalles(carte, { lieu: lieu, etage: etage, panneau: $('panneau'), message: message });
  window.edition3d = edition;

  // outils
  const boutons = Array.from(document.querySelectorAll('[data-outil]'));
  const montrerOutil = () => {
    const nom = carte.etat().outil;
    boutons.forEach((b) => b.setAttribute('aria-pressed', b.getAttribute('data-outil') === nom ? 'true' : 'false'));
    const aides = {
      naviguer: 'Glisser : tourner. Clic droit glissé : déplacer. Molette : zoom. Clic sur une épingle : la choisir ; '
        + 'la glisser : la déplacer ; glisser sa poignée blanche : la tourner.',
      accueil: 'Cliquez sur le sol là où le robot attend les visiteurs, et glissez vers où il regarde.',
      salle: 'Cliquez sur le sol devant la porte, et glissez vers la salle pour l\'orienter.',
      mesurer: 'Cliquez deux points du sol : la distance s\'affiche.',
    };
    $('etat-outil').textContent = aides[nom] || '';
  };
  const choisirOutil = (nom) => {
    carte.outil(nom);
    montrerOutil();
  };
  boutons.forEach((b) => b.addEventListener('click', () => choisirOutil(b.getAttribute('data-outil'))));
  const majBoutons = (r) => {
    $('annuler').disabled = !r.peutAnnuler;
    $('retablir').disabled = !r.peutRetablir;
    $('etat-enregistrement').textContent = r.modifie ? 'Modifications non enregistrées' : 'Tout est enregistré';
    montrerOutil();            // après une pose, l'édition revient à « naviguer »
  };
  edition.surChangement(majBoutons);
  $('annuler').addEventListener('click', () => edition.annuler());
  $('retablir').addEventListener('click', () => edition.retablir());
  $('enregistrer').addEventListener('click', async () => {
    $('enregistrer').disabled = true;
    try {
      await edition.enregistrer();
    } catch (e) {
      message(noterErreur('Enregistrement', e) + ((e.erreurs || []).length ? ' — ' + e.erreurs.join(' ; ') : ''), 'erreur');
    } finally {
      $('enregistrer').disabled = false;
    }
  });
  document.addEventListener('keydown', (ev) => {
    if (!(ev.ctrlKey || ev.metaKey) || ev.target.closest('input, textarea')) return;
    const touche = ev.key.toLowerCase();
    if (touche === 'z' && !ev.shiftKey) edition.annuler();
    else if (touche === 'y' || (touche === 'z' && ev.shiftKey)) edition.retablir();
    else if (touche === 's') edition.enregistrer().catch((e) => message(noterErreur('Enregistrement', e), 'erreur'));
    else return;
    ev.preventDefault();
  });
  carte.surPointeur((p) => {
    $('etat-coordonnees').textContent = p ? 'x ' + p.x.toFixed(2) + ' m · y ' + p.y.toFixed(2) + ' m' : '';
  });
  choisirOutil('naviguer');

  // contenu de l'étage
  await edition.charger();
  const [itineraires, zones] = await Promise.all([
    api.lire(urlLieu(lieu) + '/itineraires').catch((e) => { noterErreur('Itinéraires', e); return null; }),
    api.lire(urlLieu(lieu) + '/zones').catch((e) => { noterErreur('Zones', e); return null; }),
  ]);
  if (itineraires) carte.afficherItineraires(itineraires);
  if (zones) carte.afficherZones(zones);
  try {
    const infoCarte = await api.lire(urlEtage(lieu, etage) + '/carte.yaml');
    const r = await carte.afficherCarte2D(urlEtage(lieu, etage) + '/carte.png', infoCarte.bornes);
    essai.carte2d = r.ok || r.sansWebgl ? (r.ok ? 'ok' : 'sans WebGL') : noterErreur('Carte 2D', r.erreur);
  } catch (e) {
    essai.carte2d = noterErreur('Carte 2D', e);
  }
  if (mode === 'simu') {
    try {
      const monde = await api.lire(urlEtage(lieu, etage) + '/monde');
      const r = await carte.afficherMonde(monde, { urlMaillage: urlEtage(lieu, etage) + '/monde/maillage' });
      essai.monde = r.ok || r.sansWebgl ? (r.ok ? 'ok' : 'sans WebGL') : noterErreur('Monde', r.erreur);
      essai.maillage = r.maillage;
    } catch (e) {
      essai.monde = noterErreur('Monde', e);
    }
  }
  const nuage = parametres.get('nuage');
  if (mode === 'reel' && nuage !== '0') {
    try {
      const r = await carte.chargerNuage(nuage || urlEtage(lieu, etage) + '/nuage');
      essai.nuage = r;
      message('Nuage de ' + r.points.toLocaleString('fr-FR') + ' points.', 'info');
    } catch (e) {
      essai.nuage = { erreur: e.message, statut: e.statut || null };
      message(e.message, 'avertissement');
    }
  }
  if (parametres.get('direct') === '1') suivreEnDirect(carte);
  essai.pret = true;
  document.body.setAttribute('data-pret', '1');
}

demarrer().catch((e) => {
  message(noterErreur('Démarrage', e), 'erreur');
  essai.pret = true;
  document.body.setAttribute('data-pret', 'erreur');
});
