// Dialogues (Équipe › Dialogues ; vague 4, section 11.6 du plan, et vague 5, section 12.2) :
// le chatbot à règles du lieu (dialogues.yaml) : des règles, essayées dans l'ordre, avec leurs
// motifs (ce que dit le visiteur), leur réponse et leur action (guider vers une salle, dire,
// changer de personnalité, arrêter). « Essayer » montre la réponse et l'action d'une phrase sans
// robot ; « Envoyer au robot » la publie sur /visiteur/texte, pour le nœud dialogue. L'essai et les
// règles sont dans la vue, la règle choisie dans le panneau (✓ Enregistrer, ✗ Annuler).

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { blocAvance, panneauEdition, preparerEcran } from '../coque/ecran.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur } from '../messages.js';
import { age, creerEditeur, note, suivreEtat } from '../equipe/commun.js';

const AIDE = 'Le robot essaie les règles dans l\'ordre : la première qui correspond à la phrase du visiteur l\'emporte ; '
  + 'sinon, il répond le repli.';
const ABSENT = 'Ce fichier est facultatif : sans lui, le nœud dialogue d\'exemple prend les règles d\'exemple. '
  + 'Partez de l\'exemple (chercher une salle, bonjour, merci, mode discret, stop), adaptez-le, puis enregistrez.';
const ACTIONS = [
  { id: 'guider', texte: 'Guider vers {salle}' },
  { id: 'dire', texte: 'Répondre seulement' },
  { id: 'personnalite', texte: 'Changer de personnalité' },
  { id: 'stop', texte: 'Arrêter le robot' },
  { id: 'geste', texte: 'Répondre et faire un geste des bras' },
];
const TEXTE_ACTION = { guider: 'guider', dire: 'répondre', personnalite: 'personnalité', stop: 'arrêt', geste: 'geste', repli: 'repli' };
const SYNTAXE = [
  ['{salle}', 'une salle du lieu : son identifiant, son nom ou un de ses autres noms (Placer › Salle), avec ou sans '
    + '« la », « au », « l’ »… devant. Obligatoire dans chaque motif d\'une règle « Guider ».'],
  ['{*}', 'n\'importe quels mots, ou aucun (ex. « merci {*} »).'],
  ['{nom_salle}, {salle}', 'dans la réponse d\'une règle « Guider » : le nom et l\'identifiant de la salle trouvée.'],
];

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const afficherMessage = (texte, genre) => coque.message(texte, genre);
  let choisie = null;          // rang de la règle ouverte dans le panneau
  let editeur = null;
  let personnalites = null;    // ids de personnalites.yaml (pour l'action personnalite), ou null
  let dernierEssai = null;
  let dernierEtat = null;      // dernier GET /api/equipe/etat

  function rendre(etat) {
    const d = etat.donnees;
    if (choisie !== null && choisie >= d.regles.length) choisie = d.regles.length ? d.regles.length - 1 : null;
    const zone = etat.zones.contenu;
    zone.innerHTML = '';
    zone.appendChild(cadreEssai(etat));
    const gauche = F.el('div', 'equipe-liste');
    zone.appendChild(gauche);

    const repli = F.champTexte(gauche, 'Repli', d.repli, (v) => editeur.modifier((x) => { x.repli = v.trim() || x.repli; }),
      { lignes: 2 });
    repli.parentNode.setAttribute('data-champ', 'repli');
    note(gauche, 'Ce que le robot répond quand aucune règle ne correspond.');
    F.titre(gauche, 'Règles (' + d.regles.length + '), dans l\'ordre où elles sont essayées');
    const table = F.el('table', 'tableau equipe-regles');
    table.setAttribute('data-role', 'regles');
    const tete = F.el('tr');
    ['', 'Règle', 'Action', 'Motifs', ''].forEach((t) => tete.appendChild(F.el('th', '', t)));
    table.appendChild(tete);
    d.regles.forEach((r, i) => {
      const tr = F.el('tr', i === choisie ? 'choisie' : '');
      tr.setAttribute('data-id', r.id);
      tr.appendChild(F.el('td', 'equipe-rang', String(i + 1)));
      const nom = F.el('td');
      F.bouton(nom, r.id, () => { choisie = i; editeur.rafraichir(); }, 'bouton-lien');
      tr.appendChild(nom);
      tr.appendChild(F.el('td', '', TEXTE_ACTION[r.action] + (r.action === 'personnalite' ? ' ' + r.personnalite : '')
        + (r.action === 'geste' ? ' ' + r.geste : '')));
      tr.appendChild(F.el('td', 'equipe-motifs', r.motifs.join(' · ')));
      const actions = F.el('td', 'equipe-deplacer');
      const haut = F.bouton(actions, '↑', () => deplacer(i, -1), 'bouton bouton-petit');
      haut.title = 'Essayer cette règle plus tôt';
      haut.disabled = i === 0;
      const bas = F.bouton(actions, '↓', () => deplacer(i, 1), 'bouton bouton-petit');
      bas.title = 'Essayer cette règle plus tard';
      bas.disabled = i === d.regles.length - 1;
      tr.appendChild(actions);
      table.appendChild(tr);
    });
    gauche.appendChild(table);
    const ajout = F.bouton(gauche, 'Ajouter une règle', () => editeur.modifier((x) => {
      const id = G.idLibre('regle', x.regles.map((r) => r.id));
      x.regles.push({ id: id, motifs: ['bonjour'], action: 'dire', reponse: 'Bonjour !' });
      choisie = x.regles.length - 1;
    }));
    ajout.disabled = d.regles.length >= 500;
    const aide = F.el('details', 'equipe-syntaxe');
    aide.appendChild(F.el('summary', '', 'Écrire un motif'));
    const ul = F.el('ul');
    SYNTAXE.forEach((s) => {
      const li = F.el('li');
      li.appendChild(F.el('span', 'code', s[0]));
      li.appendChild(document.createTextNode(' : ' + s[1]));
      ul.appendChild(li);
    });
    aide.appendChild(ul);
    aide.appendChild(F.el('p', 'panneau-note', 'Prudence : un motif fait seulement de {salle} ou de {*} n\'est essayé '
      + 'que sur toute la phrase ; et une phrase avec « ne », « pas » ou « jamais » ne fait partir le robot que si un '
      + 'motif la couvre en entier (« je ne cherche pas la B204 » ne guide pas).'));
    gauche.appendChild(aide);
    gauche.appendChild(cadreRobot());
    panneauRegle(etat);
  }

  function deplacer(i, sens) {
    editeur.modifier((x) => {
      const j = i + sens;
      if (j < 0 || j >= x.regles.length) return;
      const r = x.regles.splice(i, 1)[0];
      x.regles.splice(j, 0, r);
      if (choisie === i) choisie = j;
    });
  }

  function panneauRegle(etat) {
    const d = etat.donnees;
    const r = choisie === null ? null : d.regles[choisie];
    const z = panneauEdition(ecran.panneau, r ? 'Règle « ' + r.id + ' » (' + (choisie + 1) + 'ᵉ)' : 'Dialogues', null,
      { modifie: () => editeur.modifie(), enregistrer: () => editeur.enregistrer(), annuler: () => editeur.abandonner() }).corps;
    if (!r) {
      F.paragraphe(z, 'Cliquez sur une règle pour la modifier, ou ajoutez-en une.', 'panneau-note');
      return;
    }
    const modifier = (f) => editeur.modifier(() => f(r));
    F.champTexte(blocAvance(z, 'Avancé'), 'Identifiant', r.id, (v) => {
      v = v.trim();
      const refus = G.verifierId(v, d.regles.filter((x) => x !== r).map((x) => x.id), 'une règle');
      if (refus) {
        afficherMessage(refus, 'erreur');
        editeur.rafraichir();
        return;
      }
      modifier((x) => { x.id = v; });
    });
    F.listeDeroulante(z, 'Action', r.action, ACTIONS, (v) => modifier((x) => {
      x.action = v;
      if (v !== 'personnalite') delete x.personnalite;
      else x.personnalite = x.personnalite || (personnalites && personnalites[0]) || 'discret';
      if (v !== 'geste') delete x.geste;
      else x.geste = x.geste || 26;
      if (v !== 'guider') delete x.accompagner;
    }));
    const motifs = F.champTexte(z, 'Motifs (un par ligne)', r.motifs.join('\n'), (v) => modifier((x) => {
      const liste = v.split('\n').map((m) => m.trim()).filter((m, k, tous) => m && tous.indexOf(m) === k);
      if (liste.length) x.motifs = liste;
    }), { lignes: Math.min(8, Math.max(3, r.motifs.length + 1)) });
    motifs.parentNode.setAttribute('data-champ', 'motifs');
    if (r.action === 'guider') note(z, 'Chaque motif doit contenir {salle}, ex. « je cherche {salle} ».');
    const rep = F.champTexte(z, 'Réponse', r.reponse, (v) => modifier((x) => { x.reponse = v.trim() || x.reponse; }), { lignes: 2 });
    rep.parentNode.setAttribute('data-champ', 'reponse');
    if (r.action === 'guider') {
      note(z, '{nom_salle} : le nom de la salle trouvée (ex. « Je vous emmène à {nom_salle}. Suivez-moi ! »).');
      F.caseACocher(z, 'Accompagner le visiteur (le robot le suit des yeux, ralentit ou l\'attend)',
        r.accompagner !== false, (v) => modifier((x) => {
          if (v) delete x.accompagner;
          else x.accompagner = false;
        }));
    }
    if (r.action === 'personnalite') {
      if (personnalites && personnalites.length) {
        F.listeDeroulante(z, 'Personnalité', r.personnalite, personnalites.map((p) => ({ id: p, texte: p })),
          (v) => modifier((x) => { x.personnalite = v; }));
      } else {
        F.champTexte(z, 'Personnalité (id)', r.personnalite || '', (v) => modifier((x) => { x.personnalite = v.trim(); }));
        note(z, 'Le lieu n\'a pas encore de personnalités (Équipe › Personnalités).');
      }
    }
    if (r.action === 'geste') {
      const gestes = (etat.infos && etat.infos.gestes) || {};
      const choix = Object.keys(gestes).map((k) => ({ id: k, texte: k + ' — ' + gestes[k] }));
      F.listeDeroulante(z, 'Geste', String(r.geste || 26), choix.length ? choix : [{ id: '26', texte: '26' }],
        (v) => modifier((x) => { x.geste = parseInt(v, 10); }));
      note(z, 'Le robot fait le geste seulement au repos : ni piloté à la main, ni en visite, ni pendant une '
        + 'danse ; un toutes les 10 s au plus, puis les bras sont relâchés.');
    }
    if (r.action === 'stop') note(z, 'Le robot s\'arrête aussitôt, quoi qu\'il fasse.');
    const bas = F.el('div', 'formulaire-ligne');
    F.bouton(bas, 'Supprimer la règle', async () => {
      if (!(await coque.confirmer('Supprimer la règle « ' + r.id + ' » ?',
        { titre: 'Supprimer', ok: 'Supprimer', annuler: 'Garder', danger: true }))) return;
      editeur.modifier((x) => {
        x.regles.splice(choisie, 1);
        choisie = null;
      });
    }, 'bouton bouton-danger');
    F.bouton(bas, 'Fermer', () => { choisie = null; editeur.rafraichir(); });
    z.appendChild(bas);
  }

  // ------------------------------------------------------------ essayer une phrase

  function cadreEssai(etat) {
    const cadre = F.el('div', 'carte-section equipe-essai');
    cadre.setAttribute('data-role', 'essai');
    cadre.appendChild(F.el('h2', '', 'Essayer une phrase'));
    const ligne = F.el('div', 'formulaire-ligne');
    const champ = F.el('input');
    champ.type = 'text';
    champ.placeholder = 'ex. je cherche la salle B204';
    champ.setAttribute('data-role', 'phrase');
    champ.value = dernierEssai ? dernierEssai.texte : '';
    champ.addEventListener('keydown', (ev) => { if (ev.key === 'Enter') essayer(etat, champ.value); });
    ligne.appendChild(champ);
    F.bouton(ligne, 'Essayer', () => essayer(etat, champ.value), 'bouton bouton-principal');
    const envoyer = F.bouton(ligne, 'Envoyer au robot', () => envoyerAuRobot(champ.value));
    envoyer.title = 'Publie la phrase sur /visiteur/texte : le nœud dialogue la traite, et le robot peut partir';
    cadre.appendChild(ligne);
    const resultat = F.el('div', 'equipe-resultat');
    resultat.setAttribute('data-role', 'resultat');
    cadre.appendChild(resultat);
    montrerEssai(resultat, dernierEssai);
    return cadre;
  }

  async function essayer(etat, texte) {
    texte = (texte || '').trim();
    if (!texte) {
      afficherMessage('Tapez une phrase à essayer.', 'avertissement');
      return;
    }
    try {
      const r = await api.envoyer(urlLieu(contexte.lieu) + '/dialogues/essayer',
        { texte: texte, dialogues: etat.donnees, etage: contexte.etage });
      dernierEssai = r;
      montrerEssai(ecran.vue.querySelector('[data-role="resultat"]'), r);
    } catch (e) {
      afficherErreur(e);
    }
  }

  function montrerEssai(zone, r) {
    if (!zone) return;
    zone.innerHTML = '';
    if (!r) {
      zone.appendChild(F.el('p', 'panneau-note', 'La réponse et l\'action s\'afficheront ici, sans faire bouger le robot.'));
      return;
    }
    zone.appendChild(F.el('p', 'equipe-reponse', '« ' + r.reponse + ' »'));
    const details = F.el('ul', 'equipe-details');
    const ajouter = (t) => details.appendChild(F.el('li', '', t));
    if (r.regle) {
      ajouter('Règle « ' + r.regle + ' », motif « ' + r.motif + ' » ('
        + (r.passe === 'entiere' ? 'toute la phrase' : 'trouvé dans la phrase') + ')');
    } else {
      ajouter('Aucune règle ne correspond : le repli.');
    }
    if (r.guide) {
      ajouter('Action : guider vers ' + r.nom_salle + ' (' + r.salle + ')' + (r.guide.accompagner ? ', en accompagnant le visiteur' : ''));
      const li = F.el('li');
      li.appendChild(document.createTextNode('/guide/aller : '));
      li.appendChild(F.el('span', 'code', JSON.stringify(r.guide)));
      details.appendChild(li);
    } else if (r.action === 'guider' && r.raison === 'autre_etage') {
      ajouter('La salle ' + r.nom_salle + ' est à un autre étage : pas de guidage.');
    } else if (r.action === 'personnalite') {
      ajouter('Action : passer à la personnalité « ' + r.personnalite + ' ».');
    } else if (r.action === 'stop') {
      ajouter('Action : arrêter le robot.');
    } else if (r.action === 'geste') {
      ajouter('Action : répondre, puis le geste ' + r.geste + ' (robot au repos).');
    } else {
      ajouter('Action : répondre seulement.');
    }
    if (r.origine === 'onglet' && editeur && editeur.modifie()) ajouter('Avec les règles de l\'écran, pas encore enregistrées.');
    zone.appendChild(details);
  }

  async function envoyerAuRobot(texte) {
    texte = (texte || '').trim();
    if (!texte) {
      afficherMessage('Tapez une phrase à envoyer.', 'avertissement');
      return;
    }
    if (!(await coque.confirmer('Envoyer « ' + texte + ' » au nœud dialogue ? S\'il trouve une salle, il demande au '
      + 'guide d\'y aller : le robot (ou le robot simulé) peut partir. Il utilise les règles enregistrées.',
    { titre: 'Envoyer au robot', ok: 'Envoyer', annuler: 'Annuler', danger: true }))) return;
    try {
      const r = await api.envoyer('/api/equipe/visiteur', { texte: texte });
      if (r.avertissement) afficherMessage(r.avertissement, 'avertissement');
      else afficherMessage('Phrase envoyée sur /visiteur/texte.', 'succes');
    } catch (e) {
      afficherErreur(e);
    }
  }

  // ------------------------------------------------------------ ce que le robot a dit

  function cadreRobot() {
    const cadre = F.el('div', 'equipe-dit');
    const titreDit = cadre.appendChild(F.el('h3', 'panneau-titre', 'Ce que le robot a dit'));
    titreDit.title = 'Les phrases reçues sur /robot/dire';
    const liste = F.el('ul', 'equipe-phrases');
    liste.setAttribute('data-role', 'phrases');
    cadre.appendChild(liste);
    majPhrases(liste, dernierEtat);
    return cadre;
  }

  function majPhrases(liste, e) {
    if (!liste) return;
    liste.innerHTML = '';
    if (!e || !e.ros || !e.ros.actif) {
      liste.appendChild(F.el('li', 'vide', 'ROS 2 n\'est pas actif dans le serveur de l\'Atelier.'));
      return;
    }
    if (!e.dire.length) {
      liste.appendChild(F.el('li', 'vide', 'Rien encore : lancez le nœud dialogue et « Envoyer au robot ».'));
      return;
    }
    e.dire.slice().reverse().forEach((m) => {
      const li = F.el('li');
      li.appendChild(F.el('span', 'equipe-source', (m.source || '?') + (m.code ? ' · ' + m.code : '')));
      li.appendChild(F.el('span', '', ' « ' + m.texte + ' » '));
      li.appendChild(F.el('span', 'equipe-age', age(m)));
      liste.appendChild(li);
    });
  }

  const page = F.el('div', 'page-contenu');
  ecran.vue.appendChild(page);
  editeur = creerEditeur(page, 'dialogues', {
    titre: 'Dialogues', aide: AIDE, absent: ABSENT, rendre: rendre, sansBarre: true,
    apresChargement: async () => {
      try {
        const p = await api.lire(urlLieu(contexte.lieu) + '/personnalites');
        personnalites = p.personnalites.map((x) => x.id);
      } catch (e) {
        personnalites = null;
      }
    },
  });
  editeur.pret.then(() => {
    if (!editeur.etat.donnees) {
      const z = panneauEdition(ecran.panneau, 'Dialogues', null,
        { modifie: () => editeur.modifie(), enregistrer: () => editeur.enregistrer(), annuler: () => editeur.abandonner() }).corps;
      F.paragraphe(z, 'Partez de l\'exemple (au centre), puis choisissez une règle pour la modifier ici.', 'panneau-note');
    }
  });
  const arreter = suivreEtat((e) => {
    dernierEtat = e;
    majPhrases(ecran.vue.querySelector('[data-role="phrases"]'), e);
  }, 1500);

  return {
    modifie: () => editeur.modifie(),
    enregistrer: () => editeur.enregistrer(),
    fermer: () => arreter(),
  };
}
