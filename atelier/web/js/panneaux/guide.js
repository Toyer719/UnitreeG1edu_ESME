// Panneau du comportement du guide dans l'onglet Simulation (vague 4, section 11.4 du plan) :
// agent Comportement du guide. simulation.js appelle monter(element, outils) et, en fermant
// l'onglet, fermer() de l'objet renvoyé. outils : {lieu, etage, plan, carte}.
//
// Il montre ce que fait le guide (mission, visiteur suivi, retour prévu), les messages dits au
// visiteur (/guide/evenement, champ evenements de /ws/etat), permet d'accompagner un visiteur
// jusqu'à une salle (POST /api/guide/aller {cible, accompagner: true, retour}), de conduire le
// faux visiteur de la simulation (POST /api/guide/visiteur) et de régler les délais du guide du
// lieu (GET/PUT /api/lieux/{id}/guide).

import { api, urlLieu } from '../api.js';
import { abonner } from '../direct.js';
import * as F from '../formulaire.js';
import { afficherErreur, afficherMessage } from '../messages.js';

export const LIBELLES_ETATS = {
  attente: 'Au repos',
  en_route: 'En visite',
  retour: 'Retour au point principal',
  bloque: 'Bloqué : quelque chose gêne le passage',
  attente_passage: 'Attend qu\'un passant s\'écarte',
  detour: 'Détour par un autre couloir',
  attente_visiteur: 'Attend le visiteur',
  perdu: 'Perdu : attend de retrouver sa position',
  arrive: 'Arrivé',
  echec: 'Échec',
};

const MODES_VISITEUR = [
  { id: 'suivre', texte: 'Suivre', titre: 'Le faux visiteur suit le robot à 1,2 m' },
  { id: 'trainer', texte: 'Traîner', titre: 'Il avance à 0,15 m/s : le robot ralentit puis l\'attend' },
  { id: 'partir', texte: 'Partir', titre: 'Il s\'en va : le robot l\'attend, puis abandonne et rentre' },
  { id: 'arreter', texte: 'S\'arrêter', titre: 'Il s\'arrête sur place' },
];

// Réglages de la section guide de lieu.yaml (atelier.lieu.comportement.DELAIS_GUIDE)
const REGLAGES = [
  { cle: 'retour_auto', texte: 'Retour automatique au point principal', type: 'case' },
  { cle: 'delai_avant_retour_s', texte: 'Attente à destination avant le retour', unite: 's', min: 0, max: 600 },
  { cle: 'delai_visiteur_s', texte: 'Attente du visiteur qui ne suit plus', unite: 's', min: 1, max: 600 },
  { cle: 'distance_ralentir_m', texte: 'Visiteur plus loin : ralentir', unite: 'm', min: 0.5, max: 10 },
  { cle: 'distance_attendre_m', texte: 'Visiteur plus loin : l\'attendre', unite: 'm', min: 1, max: 15 },
  { cle: 'ralenti', texte: 'Vitesse en ralenti (fraction)', unite: '', min: 0.1, max: 1 },
  { cle: 'delai_perdu_s', texte: 'Robot perdu : attente avant l\'échec', unite: 's', min: 1, max: 600 },
  { cle: 'delai_passant_s', texte: 'Passant qui bouche : attente avant le détour', unite: 's', min: 0, max: 300 },
];

function heure(texte) {
  if (!texte) return '';
  const m = /T(\d\d:\d\d:\d\d)/.exec(texte);
  return m ? m[1] : '';
}

export function texteVisiteur(g) {
  if (!g || !g.accompagner) return g && g.mission === 'visite' ? 'Visite sans accompagnement.' : '';
  const v = g.visiteur;
  if (!v || v.age_s === null || v.age_s === undefined) return 'Visiteur : recherche derrière le robot…';
  if (!v.vu) return 'Visiteur : plus vu depuis ' + Math.round(v.age_s) + ' s.';
  return 'Visiteur : à ' + (Math.round(v.distance_m * 10) / 10).toLocaleString('fr-FR') + ' m.';
}

export function monter(element, outils) {
  if (!outils || !outils.lieu) {
    element.hidden = true;
    return { fermer: () => {} };
  }
  element.hidden = false;
  element.textContent = '';
  F.titre(element, 'Comportement du guide');
  const etatLigne = element.appendChild(F.el('div', 'comportement-etat', 'Guide non lancé'));
  const visiteurLigne = element.appendChild(F.el('div', 'comportement-visiteur', ''));
  const retourLigne = element.appendChild(F.el('div', 'comportement-retour', ''));

  // Accompagner un visiteur
  const bloc = element.appendChild(F.el('div', 'comportement-accompagner'));
  let cible = '';
  let retour = true;
  const choix = F.listeDeroulante(bloc, 'Destination', '', [{ id: '', texte: 'Chargement…' }], (v) => { cible = v; });
  F.caseACocher(bloc, 'Puis retour au point principal', retour, (v) => { retour = v; });
  const boutonAccompagner = F.bouton(bloc, 'Accompagner un visiteur', async () => {
    if (!cible) return;
    boutonAccompagner.disabled = true;
    try {
      const r = await api.envoyer('/api/guide/aller', { cible: cible, accompagner: true, retour: retour });
      afficherMessage(r.avertissement || 'Le robot part avec le visiteur.', r.avertissement ? 'avertissement' : 'info');
    } catch (e) {
      afficherErreur(e);
    } finally {
      boutonAccompagner.disabled = false;
    }
  }, 'bouton bouton-principal');
  // Le point principal (étiquette « principal », ou la salle accueil d'un lieu d'avant la vague 4)
  const lectureGuide = api.lire(urlLieu(outils.lieu) + '/guide');
  Promise.all([api.lire(urlLieu(outils.lieu) + '/salles'), lectureGuide.catch(() => null)]).then(([salles, g]) => {
    const principal = g && g.principal ? g.principal.salle : null;
    const ici = (salles || []).filter((s) => !outils.etage || s.etage === outils.etage);
    choix.textContent = '';
    ici.forEach((s) => {
      const o = F.el('option', '', s.nom + (s.id === principal ? ' (point principal)' : ''));
      o.value = s.id;
      choix.appendChild(o);
    });
    cible = ici.length ? ici[0].id : '';
    choix.value = cible;
  }).catch(() => { choix.textContent = ''; });

  // Faux visiteur de la simulation
  const faux = element.appendChild(F.el('details', 'comportement-faux-visiteur'));
  faux.appendChild(F.el('summary', '', 'Faux visiteur (simulation)'));
  F.paragraphe(faux, 'Avec une scène d\'accompagnement : le piéton « visiteur » suit le robot, traîne ou s\'en va.',
    'panneau-note');
  const rangee = faux.appendChild(F.el('div', 'comportement-modes'));
  MODES_VISITEUR.forEach((m) => {
    const b = F.bouton(rangee, m.texte, async () => {
      try {
        const r = await api.envoyer('/api/guide/visiteur', { mode: m.id });
        afficherMessage(r.avertissement || ('Faux visiteur : ' + m.texte.toLowerCase() + '.'),
          r.avertissement ? 'avertissement' : 'info');
      } catch (e) {
        afficherErreur(e);
      }
    });
    b.title = m.titre;
  });

  // Messages au visiteur
  const messages = element.appendChild(F.el('details', 'comportement-evenements'));
  messages.open = true;
  messages.appendChild(F.el('summary', '', 'Messages au visiteur'));
  const liste = messages.appendChild(F.el('ul', 'liste-evenements'));
  let derniereCle = '';

  // Réglages du lieu
  const reglages = element.appendChild(F.el('details', 'comportement-reglages'));
  reglages.appendChild(F.el('summary', '', 'Réglages du guide (ce lieu)'));
  const formulaire = reglages.appendChild(F.el('div', 'formulaire'));
  const valeurs = {};
  function dessinerReglages(r) {
    formulaire.textContent = '';
    REGLAGES.forEach((d) => {
      const actuel = (r.guide && r.guide[d.cle] !== undefined) ? r.guide[d.cle] : r.defauts[d.cle];
      valeurs[d.cle] = actuel;
      if (d.type === 'case') {
        F.caseACocher(formulaire, d.texte, actuel, (v) => { valeurs[d.cle] = v; });
      } else {
        F.champNombre(formulaire, d.texte, actuel, { min: d.min, max: d.max, unite: d.unite, decimales: 2 },
          (v) => { valeurs[d.cle] = v; });
      }
    });
    const ligne = formulaire.appendChild(F.el('div', 'formulaire-ligne'));
    F.bouton(ligne, 'Enregistrer les réglages', async () => {
      const corps = {};
      REGLAGES.forEach((d) => { if (valeurs[d.cle] !== r.defauts[d.cle]) corps[d.cle] = valeurs[d.cle]; });
      try {
        const reponse = await api.ecrire(urlLieu(outils.lieu) + '/guide', corps);
        afficherMessage('Réglages du guide enregistrés. ' + (reponse.note || ''), 'succes');
        dessinerReglages(reponse);
      } catch (e) {
        afficherErreur(e);
      }
    });
    F.bouton(ligne, 'Valeurs par défaut', async () => {
      try {
        const reponse = await api.ecrire(urlLieu(outils.lieu) + '/guide', {});
        afficherMessage('Réglages du guide remis par défaut.', 'succes');
        dessinerReglages(reponse);
      } catch (e) {
        afficherErreur(e);
      }
    });
  }
  lectureGuide.then(dessinerReglages).catch(() => {
    F.paragraphe(formulaire, 'Réglages illisibles : vérifiez lieu.yaml (arbre › le lieu, Vérifier).', 'panneau-alerte');
  });

  function dessinerEvenements(evenements) {
    const cle = evenements.map((e) => e.code + (e.temps || '')).join('|');
    if (cle === derniereCle) return;
    derniereCle = cle;
    liste.textContent = '';
    if (!evenements.length) {
      liste.appendChild(F.el('li', 'panneau-note', 'Aucun message pour le moment.'));
      return;
    }
    evenements.slice().reverse().forEach((e) => {
      const li = F.el('li', 'evenement evenement-' + e.code);
      li.appendChild(F.el('span', 'evenement-heure', heure(e.temps)));
      li.appendChild(F.el('span', 'evenement-texte', e.texte));
      li.title = 'Code : ' + e.code + (e.salle ? ' — salle : ' + e.salle : '');
      liste.appendChild(li);
    });
  }

  const desabonner = abonner((d) => {
    const g = d.guide;
    if (!g) {
      etatLigne.textContent = 'Guide non lancé';
      etatLigne.className = 'comportement-etat';
      visiteurLigne.textContent = '';
      retourLigne.textContent = '';
    } else {
      let t = LIBELLES_ETATS[g.etat] || ('État : ' + g.etat);
      if (g.cible && g.etat !== 'attente') t += ' (' + g.cible + ')';
      if (g.depuis_s !== undefined && g.etat !== 'attente') t += ' depuis ' + Math.round(g.depuis_s) + ' s';
      etatLigne.textContent = t;
      etatLigne.className = 'comportement-etat comportement-' + g.etat;
      visiteurLigne.textContent = texteVisiteur(g);
      retourLigne.textContent = (g.retour_dans_s !== undefined && g.retour_dans_s !== null)
        ? 'Retour au point principal dans ' + Math.ceil(g.retour_dans_s) + ' s.' : (g.message || '');
    }
    dessinerEvenements(d.evenements || []);
  });
  return { fermer: () => desabonner() };
}
