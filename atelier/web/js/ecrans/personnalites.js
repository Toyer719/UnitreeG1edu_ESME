// Personnalités (vague 4, section 11.6 du plan) : écran de l'agent Équipe.
// Les modes de personnalité du robot dans ce lieu (personnalites.yaml) : nom, salutation, voix,
// couleur de la LED, geste de salut, vitesse maximale et phrases des événements du guide. Une
// seule est active : « Rendre active » l'écrit dans le fichier et l'annonce sur
// /personnalite/active, que la voix et le chatbot de l'équipe écoutent.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage } from '../messages.js';
import { age, aide, champNombreFacultatif, creerEditeur, note, suivreEtat } from '../equipe/commun.js';

const AIDE = 'Chaque mode change la façon dont le robot parle et se comporte : ce qu\'il dit en saluant, sa voix, '
  + 'la couleur de sa LED, son geste de salut, sa vitesse maximale et les phrases qu\'il dit pendant une visite. '
  + 'Une seule personnalité est active ; la partie voix de l\'équipe la reçoit sur /personnalite/active.';
const ABSENT = 'Ce fichier est facultatif : sans lui, le robot garde sa voix et les phrases par défaut du guide. '
  + 'Partez de l\'exemple (deux modes : « Accueillant » et « Discret »), adaptez-le, puis enregistrez.';
const NOUVELLE = { nom: 'Nouvelle personnalité', salutation: 'Bonjour ! Où voulez-vous aller ?' };

function hex(led) {
  const h = (v) => ('0' + Math.max(0, Math.min(255, v | 0)).toString(16)).slice(-2);
  return '#' + h(led.r) + h(led.g) + h(led.b);
}

function depuisHex(texte) {
  const m = /^#?([0-9a-f]{2})([0-9a-f]{2})([0-9a-f]{2})$/i.exec(texte || '');
  return m ? { r: parseInt(m[1], 16), g: parseInt(m[2], 16), b: parseInt(m[3], 16) } : null;
}

export function ouvrir(racine) {
  let choisie = null;          // id de la personnalité ouverte dans le panneau
  let annoncee = null;         // dernier /personnalite/active reçu par le serveur
  let editeur = null;

  function perso(d, id) {
    return d.personnalites.find((p) => p.id === id) || null;
  }

  function schemaPerso(etat) {
    return etat.infos.fichiers.personnalites.schema;
  }

  function aideChamp(etat, champ) {
    return aide(schemaPerso(etat), ['definitions', 'personnalite', 'properties', champ]);
  }

  function rendre(etat) {
    const d = etat.donnees;
    if (!perso(d, choisie)) choisie = d.active;
    const zone = etat.zones.contenu;
    zone.innerHTML = '';
    const espace = F.el('div', 'espace-deux equipe-espace');
    const gauche = F.el('div', 'equipe-liste');
    const cote = F.el('div', 'cote');
    const panneau = F.el('div', 'panneau');
    panneau.setAttribute('data-role', 'panneau');
    cote.appendChild(panneau);
    espace.appendChild(gauche);
    espace.appendChild(cote);
    zone.appendChild(espace);

    // état de l'annonce sur ROS 2
    const annonce = F.el('div', 'equipe-annonce');
    annonce.setAttribute('data-role', 'annonce');
    gauche.appendChild(annonce);
    majAnnonce(annonce, d);

    const liste = F.el('div', 'equipe-cartes');
    liste.setAttribute('data-role', 'liste');
    d.personnalites.forEach((p) => {
      const carte = F.el('div', 'equipe-carte' + (p.id === choisie ? ' choisie' : '') + (p.id === d.active ? ' active' : ''));
      carte.setAttribute('data-id', p.id);
      const tete = F.el('div', 'equipe-carte-tete');
      const pastille = F.el('span', 'equipe-led');
      pastille.style.background = p.led ? hex(p.led) : 'transparent';
      pastille.title = p.led ? 'LED ' + p.led.r + ', ' + p.led.g + ', ' + p.led.b : 'LED inchangée';
      tete.appendChild(pastille);
      tete.appendChild(F.el('strong', 'equipe-carte-nom', p.nom));
      tete.appendChild(F.el('span', 'equipe-carte-id code', p.id));
      if (p.id === d.active) tete.appendChild(F.el('span', 'pastille', 'active'));
      carte.appendChild(tete);
      if (p.description) carte.appendChild(F.el('p', 'equipe-carte-texte', p.description));
      carte.appendChild(F.el('p', 'equipe-carte-salut', '« ' + p.salutation + ' »'));
      const boutons = F.el('div', 'equipe-carte-boutons');
      F.bouton(boutons, 'Modifier', () => { choisie = p.id; editeur.rafraichir(); });
      if (p.id !== d.active) {
        F.bouton(boutons, 'Rendre active', () => rendreActive(p.id), 'bouton bouton-principal');
      }
      carte.appendChild(boutons);
      liste.appendChild(carte);
    });
    gauche.appendChild(liste);
    const ajout = F.bouton(gauche, 'Ajouter une personnalité', () => editeur.modifier((x) => {
      const id = G.idLibre('mode', x.personnalites.map((p) => p.id));
      x.personnalites.push({ id: id, nom: NOUVELLE.nom, salutation: NOUVELLE.salutation });
      choisie = id;
    }));
    ajout.disabled = d.personnalites.length >= 20;
    panneauPerso(etat, panneau);
  }

  function majAnnonce(zone, d) {
    if (!zone) return;
    zone.innerHTML = '';
    if (!annoncee) {
      zone.appendChild(F.el('span', '', 'Personnalité annoncée sur /personnalite/active : aucune reçue par l\'Atelier '
        + '(ROS 2 arrêté, ou personne ne l\'a encore annoncée).'));
      return;
    }
    zone.appendChild(F.el('span', '', 'Annoncée sur /personnalite/active : '));
    zone.appendChild(F.el('strong', '', annoncee.nom + ' (' + annoncee.id + ')'));
    zone.appendChild(F.el('span', 'equipe-age', ' ' + age(annoncee)
      + (annoncee.lieu && annoncee.lieu !== contexte.lieu ? ', lieu « ' + annoncee.lieu + ' »' : '')));
    if (d && annoncee.id !== d.active) {
      zone.appendChild(F.el('span', 'equipe-ecart', ' — différente de l\'active du fichier (' + d.active + ')'));
    }
  }

  function panneauPerso(etat, z) {
    const d = etat.donnees;
    const p = perso(d, choisie);
    z.innerHTML = '';
    if (!p) return;
    const modifier = (f) => editeur.modifier(() => f(p));
    F.titre(z, 'Personnalité « ' + p.nom + ' »' + (p.id === d.active ? ' (active)' : ''));

    F.champTexte(z, 'Nom affiché', p.nom, (v) => modifier((x) => { x.nom = v.trim() || x.nom; }));
    const champId = F.champTexte(z, 'Identifiant', p.id, (v) => {
      v = v.trim();
      const refus = G.verifierId(v, d.personnalites.filter((x) => x !== p).map((x) => x.id), 'une personnalité');
      if (refus) {
        afficherMessage(refus, 'erreur');
        editeur.rafraichir();
        return;
      }
      modifier((x) => {
        if (d.active === x.id) d.active = v;
        x.id = v;
        choisie = v;
      });
    });
    champId.parentNode.setAttribute('data-champ', 'id');
    F.champTexte(z, 'Description (pour l\'équipe)', p.description || '', (v) => modifier((x) => {
      if (v.trim()) x.description = v.trim();
      else delete x.description;
    }), { lignes: 2, indice: 'Facultatif : quand utiliser ce mode.' });
    const salut = F.champTexte(z, 'Salutation', p.salutation, (v) => modifier((x) => { x.salutation = v.trim() || x.salutation; }),
      { lignes: 2 });
    salut.parentNode.setAttribute('data-champ', 'salutation');
    note(z, aideChamp(etat, 'salutation'));

    F.titre(z, 'Voix');
    note(z, 'Réglages pour la partie voix de l\'équipe : 1 = normal ; volume de 0 à 100. Vides : ceux de la voix.');
    F.champTexte(z, 'Nom de la voix', (p.voix || {}).nom || '', (v) => modifier((x) => {
      majVoix(x, 'nom', v.trim() || null);
    }), { indice: 'ex. fr_FR-siwis-medium (vide : la voix par défaut)' });
    ['vitesse', 'hauteur'].forEach((c) => {
      champNombreFacultatif(z, c === 'vitesse' ? 'Vitesse de parole' : 'Hauteur', (p.voix || {})[c],
        { pas: 0.05, min: 0.5, max: 2, indice: '1' }, (v) => modifier((x) => majVoix(x, c, v)));
    });
    champNombreFacultatif(z, 'Volume', (p.voix || {}).volume, { pas: 5, min: 0, max: 100, indice: '80' },
      (v) => modifier((x) => majVoix(x, 'volume', v === null ? null : Math.round(v))));

    F.titre(z, 'LED et geste');
    const ligneLed = F.el('div', 'champ');
    ligneLed.appendChild(F.el('span', 'champ-libelle', 'Couleur de la LED'));
    const couleur = F.el('input');
    couleur.type = 'color';
    couleur.value = p.led ? hex(p.led) : '#000000';
    couleur.disabled = !p.led;
    couleur.addEventListener('change', () => modifier((x) => { x.led = depuisHex(couleur.value) || x.led; }));
    ligneLed.appendChild(couleur);
    ligneLed.appendChild(F.el('span', 'champ-unite', p.led ? p.led.r + ', ' + p.led.g + ', ' + p.led.b : ''));
    z.appendChild(ligneLed);
    F.caseACocher(z, 'Changer la couleur de la LED dans ce mode', !!p.led, (v) => modifier((x) => {
      if (v) x.led = x.led || { r: 0, g: 120, b: 255 };
      else delete x.led;
    }));
    const gestes = [{ id: '', texte: 'aucun' }].concat(Object.keys(etat.infos.gestes)
      .map((k) => ({ id: k, texte: k + ' — ' + etat.infos.gestes[k] })));
    F.listeDeroulante(z, 'Geste de salut', p.geste_salut === undefined ? '' : String(p.geste_salut), gestes,
      (v) => modifier((x) => {
        if (v) x.geste_salut = parseInt(v, 10);
        else delete x.geste_salut;
      }));
    note(z, 'Geste des bras d\'Unitree (service arm). Il n\'est jamais commandé par ce fichier : c\'est le nœud '
      + 'pilotage (ou le guide) qui garde la main sur les mouvements, voir docs/integration-equipe.md.');

    F.titre(z, 'Marche');
    champNombreFacultatif(z, 'Vitesse maximale', p.vitesse_max, { pas: 0.05, min: 0.05, max: 0.4, unite: 'm/s', indice: 'celle du guide' },
      (v) => modifier((x) => {
        if (v === null) delete x.vitesse_max;
        else x.vitesse_max = Math.min(0.4, Math.max(0.05, v));
      }));
    note(z, 'Vide : la vitesse du guide (0,4 m/s au plus, le plafond du pont). Plus bas, le robot guide plus lentement '
      + 'dans ce mode.');

    F.titre(z, 'Phrases pendant une visite');
    note(z, 'Elles remplacent les phrases par défaut du guide (événements de /guide/evenement). Vide : la phrase par '
      + 'défaut, montrée en gris. {nom} devient le nom de la salle visée. À l\'arrivée, la phrase propre à une salle '
      + '(onglet Salles) reste prioritaire.');
    const codes = etat.infos.codes_evenement;
    Object.keys(codes).forEach((code) => {
      const c = F.champTexte(z, code, (p.phrases || {})[code] || '', (v) => modifier((x) => {
        x.phrases = x.phrases || {};
        if (v.trim()) x.phrases[code] = v.trim();
        else delete x.phrases[code];
        if (!Object.keys(x.phrases).length) delete x.phrases;
      }), { indice: codes[code] });
      c.parentNode.setAttribute('data-phrase', code);
    });

    const bas = F.el('div', 'formulaire-ligne');
    if (p.id !== d.active) {
      F.bouton(bas, 'Rendre active', () => rendreActive(p.id), 'bouton bouton-principal');
      F.bouton(bas, 'Supprimer cette personnalité', () => {
        if (!window.confirm('Supprimer la personnalité « ' + p.nom + ' » ?')) return;
        editeur.modifier((x) => {
          x.personnalites = x.personnalites.filter((y) => y !== p);
          choisie = x.active;
        });
      }, 'bouton bouton-danger');
    } else {
      F.paragraphe(bas, 'C\'est la personnalité active : pour la supprimer, rendez d\'abord une autre active.', 'panneau-note');
    }
    z.appendChild(bas);
  }

  function majVoix(x, champ, v) {
    x.voix = x.voix || {};
    if (v === null) delete x.voix[champ];
    else x.voix[champ] = v;
    if (!Object.keys(x.voix).length) delete x.voix;
  }

  async function rendreActive(id) {
    if (editeur.modifie()) {
      if (!window.confirm('Les modifications seront d\'abord enregistrées. Continuer ?')) return;
      if (!(await editeur.enregistrer())) return;
    }
    try {
      const r = await api.envoyer(urlLieu(contexte.lieu) + '/personnalites/active', { id: id });
      editeur.etat.donnees.active = r.active;
      choisie = r.active;
      editeur.rafraichir();
      if (r.avertissement) afficherMessage(r.avertissement, 'avertissement');
      else afficherMessage('Personnalité « ' + r.message.nom + ' » active, annoncée sur /personnalite/active.', 'succes');
    } catch (e) {
      afficherErreur(e);
    }
  }

  editeur = creerEditeur(racine, 'personnalites', {
    titre: 'Personnalités', aide: AIDE, absent: ABSENT, rendre: rendre,
    apresChargement: (etat) => { choisie = etat.donnees ? etat.donnees.active : null; },
    depuisExemple: (d) => { choisie = d.active; },
  });
  const arreter = suivreEtat((e) => {
    const avant = JSON.stringify(annoncee && { id: annoncee.id, lieu: annoncee.lieu });
    annoncee = e && e.personnalite ? e.personnalite : null;
    majAnnonce(racine.querySelector('[data-role="annonce"]'), editeur.etat.donnees);
    if (avant !== JSON.stringify(annoncee && { id: annoncee.id, lieu: annoncee.lieu })) {
      racine.dataset.annoncee = annoncee ? annoncee.id : '';
    }
  }, 1500);

  return {
    modifie: () => editeur.modifie(),
    fermer: () => arreter(),
  };
}
