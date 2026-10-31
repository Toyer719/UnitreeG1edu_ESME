// Personnalités (Équipe › Personnalités ; vague 4, section 11.6 du plan, et vague 5, section 12.2) :
// les modes de personnalité du robot dans ce lieu (personnalites.yaml) : nom, salutation, voix,
// couleur de la LED, geste de salut, vitesse maximale et phrases des événements du guide. Une
// seule est active : « Rendre active » l'écrit dans le fichier et l'annonce sur
// /personnalite/active, que la voix et le chatbot de l'équipe écoutent. Les cartes sont dans la vue,
// la personnalité choisie dans le panneau (✓ Enregistrer, ✗ Annuler) ; réglages rares en « Avancé ».

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { blocAvance, panneauEdition, preparerEcran } from '../coque/ecran.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur } from '../messages.js';
import { age, aide, champNombreFacultatif, creerEditeur, note, suivreEtat } from '../equipe/commun.js';

const AIDE = 'Chaque mode change ce que le robot dit en saluant, sa voix, sa couleur, son geste et ses phrases '
  + 'pendant une visite. Une seule personnalité est active.';
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

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  let choisie = null;          // id de la personnalité ouverte dans le panneau
  let annoncee = null;         // dernier /personnalite/active reçu par le serveur
  let editeur = null;
  const afficherMessage = (texte, genre) => coque.message(texte, genre);

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
    const gauche = F.el('div', 'equipe-liste');
    zone.appendChild(gauche);

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
    panneauPerso(etat);
  }

  function majAnnonce(zone, d) {
    if (!zone) return;
    zone.innerHTML = '';
    if (!annoncee) {
      zone.appendChild(F.el('span', '', 'Personnalité annoncée au robot : aucune pour l\'instant.'));
      zone.title = 'Rien reçu sur /personnalite/active (ROS 2 arrêté, ou personne ne l\'a encore annoncée).';
      return;
    }
    zone.title = 'Reçue sur /personnalite/active';
    zone.appendChild(F.el('span', '', 'Annoncée au robot : '));
    zone.appendChild(F.el('strong', '', annoncee.nom + ' (' + annoncee.id + ')'));
    zone.appendChild(F.el('span', 'equipe-age', ' ' + age(annoncee)
      + (annoncee.lieu && annoncee.lieu !== contexte.lieu ? ', lieu « ' + annoncee.lieu + ' »' : '')));
    if (d && annoncee.id !== d.active) {
      zone.appendChild(F.el('span', 'equipe-ecart', ' — différente de l\'active du fichier (' + d.active + ')'));
    }
  }

  function panneauPerso(etat) {
    const d = etat.donnees;
    const p = perso(d, choisie);
    const z = panneauEdition(ecran.panneau, p ? p.nom + (p.id === d.active ? ' (active)' : '') : 'Personnalités', null,
      { modifie: () => editeur.modifie(), enregistrer: () => editeur.enregistrer(), annuler: () => editeur.abandonner() }).corps;
    if (!p) return;
    const modifier = (f) => editeur.modifier(() => f(p));

    F.champTexte(z, 'Nom affiché', p.nom, (v) => modifier((x) => { x.nom = v.trim() || x.nom; }));
    const salut = F.champTexte(z, 'Salutation', p.salutation, (v) => modifier((x) => { x.salutation = v.trim() || x.salutation; }),
      { lignes: 2 });
    salut.parentNode.setAttribute('data-champ', 'salutation');
    F.champTexte(z, 'Description', p.description || '', (v) => modifier((x) => {
      if (v.trim()) x.description = v.trim();
      else delete x.description;
    }), { lignes: 2, indice: 'Facultatif : quand utiliser ce mode.' });

    const bas = F.el('div', 'formulaire-ligne');
    if (p.id !== d.active) {
      F.bouton(bas, 'Rendre active', () => rendreActive(p.id), 'bouton bouton-principal');
      F.bouton(bas, 'Supprimer', async () => {
        if (!(await coque.confirmer('Supprimer la personnalité « ' + p.nom + ' » ?',
          { titre: 'Supprimer', ok: 'Supprimer', annuler: 'Garder', danger: true }))) return;
        editeur.modifier((x) => {
          x.personnalites = x.personnalites.filter((y) => y !== p);
          choisie = x.active;
        });
      }, 'bouton bouton-danger');
    } else {
      F.paragraphe(bas, 'C\'est la personnalité active.', 'panneau-note');
    }
    z.appendChild(bas);

    const voix = blocAvance(z, 'Voix');
    note(voix, '1 = normal ; volume de 0 à 100. Vides : ceux de la voix.');
    F.champTexte(voix, 'Nom de la voix', (p.voix || {}).nom || '', (v) => modifier((x) => {
      majVoix(x, 'nom', v.trim() || null);
    }), { indice: 'ex. fr_FR-siwis-medium' });
    ['vitesse', 'hauteur'].forEach((c) => {
      champNombreFacultatif(voix, c === 'vitesse' ? 'Vitesse de parole' : 'Hauteur', (p.voix || {})[c],
        { pas: 0.05, min: 0.5, max: 2, indice: '1' }, (v) => modifier((x) => majVoix(x, c, v)));
    });
    champNombreFacultatif(voix, 'Volume', (p.voix || {}).volume, { pas: 5, min: 0, max: 100, indice: '80' },
      (v) => modifier((x) => majVoix(x, 'volume', v === null ? null : Math.round(v))));

    const led = blocAvance(z, 'Lumière et geste');
    const ligneLed = F.el('div', 'champ');
    ligneLed.appendChild(F.el('span', 'champ-libelle', 'Couleur'));
    const couleur = F.el('input');
    couleur.type = 'color';
    couleur.value = p.led ? hex(p.led) : '#000000';
    couleur.disabled = !p.led;
    couleur.addEventListener('change', () => modifier((x) => { x.led = depuisHex(couleur.value) || x.led; }));
    ligneLed.appendChild(couleur);
    led.appendChild(ligneLed);
    F.caseACocher(led, 'Changer la couleur dans ce mode', !!p.led, (v) => modifier((x) => {
      if (v) x.led = x.led || { r: 0, g: 120, b: 255 };
      else delete x.led;
    }));
    const gestes = [{ id: '', texte: 'aucun' }].concat(Object.keys(etat.infos.gestes)
      .map((k) => ({ id: k, texte: etat.infos.gestes[k] })));
    F.listeDeroulante(led, 'Geste de salut', p.geste_salut === undefined ? '' : String(p.geste_salut), gestes,
      (v) => modifier((x) => {
        if (v) x.geste_salut = parseInt(v, 10);
        else delete x.geste_salut;
      }));
    champNombreFacultatif(led, 'Vitesse maximale', p.vitesse_max, { pas: 0.05, min: 0.05, max: 0.4, unite: 'm/s', indice: 'celle du guide' },
      (v) => modifier((x) => {
        if (v === null) delete x.vitesse_max;
        else x.vitesse_max = Math.min(0.4, Math.max(0.05, v));
      }));

    const phrases = blocAvance(z, 'Phrases pendant une visite');
    note(phrases, 'Vide : la phrase par défaut, en gris. {nom} devient le nom de la salle visée.');
    const codes = etat.infos.codes_evenement;
    Object.keys(codes).forEach((code) => {
      const c = F.champTexte(phrases, code, (p.phrases || {})[code] || '', (v) => modifier((x) => {
        x.phrases = x.phrases || {};
        if (v.trim()) x.phrases[code] = v.trim();
        else delete x.phrases[code];
        if (!Object.keys(x.phrases).length) delete x.phrases;
      }), { indice: codes[code] });
      c.parentNode.setAttribute('data-phrase', code);
    });

    const avance = blocAvance(z, 'Avancé');
    const champId = F.champTexte(avance, 'Identifiant', p.id, (v) => {
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
    note(avance, aideChamp(etat, 'salutation'));
  }

  function majVoix(x, champ, v) {
    x.voix = x.voix || {};
    if (v === null) delete x.voix[champ];
    else x.voix[champ] = v;
    if (!Object.keys(x.voix).length) delete x.voix;
  }

  async function rendreActive(id) {
    if (editeur.modifie()) {
      if (!(await coque.confirmer('Les modifications seront d\'abord enregistrées. Continuer ?',
        { titre: 'Rendre active', ok: 'Enregistrer et continuer', annuler: 'Annuler' }))) return;
      if (!(await editeur.enregistrer())) return;
    }
    try {
      const r = await api.envoyer(urlLieu(contexte.lieu) + '/personnalites/active', { id: id });
      editeur.etat.donnees.active = r.active;
      choisie = r.active;
      editeur.rafraichir();
      if (r.avertissement) afficherMessage(r.avertissement, 'avertissement');
      else afficherMessage('Personnalité « ' + r.message.nom + ' » active.', 'succes');
    } catch (e) {
      afficherErreur(e);
    }
  }

  const page = F.el('div', 'page-contenu');
  ecran.vue.appendChild(page);
  editeur = creerEditeur(page, 'personnalites', {
    titre: 'Personnalités', aide: AIDE, absent: ABSENT, rendre: rendre, sansBarre: true,
    apresChargement: (etat) => { choisie = etat.donnees ? etat.donnees.active : null; },
    depuisExemple: (d) => { choisie = d.active; },
  });
  editeur.pret.then(() => {
    if (!editeur.etat.donnees) {
      const z = panneauEdition(ecran.panneau, 'Personnalités', null,
        { modifie: () => editeur.modifie(), enregistrer: () => editeur.enregistrer(), annuler: () => editeur.abandonner() }).corps;
      F.paragraphe(z, 'Partez de l\'exemple (au centre), puis choisissez une personnalité pour la modifier ici.', 'panneau-note');
    }
  });
  const arreter = suivreEtat((e) => {
    const avant = JSON.stringify(annoncee && { id: annoncee.id, lieu: annoncee.lieu });
    annoncee = e && e.personnalite ? e.personnalite : null;
    majAnnonce(ecran.vue.querySelector('[data-role="annonce"]'), editeur.etat.donnees);
    if (avant !== JSON.stringify(annoncee && { id: annoncee.id, lieu: annoncee.lieu })) {
      ecran.vue.dataset.annoncee = annoncee ? annoncee.id : '';
    }
  }, 1500);

  return {
    modifie: () => editeur.modifie(),
    enregistrer: () => editeur.enregistrer(),
    fermer: () => arreter(),
  };
}
