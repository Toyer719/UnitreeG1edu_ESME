// Écran Salles (Placer › Salle, Placer › Accueil) : placer les destinations du guide et l'accueil, dans la
// carte 3D (vue par défaut, vague 5 : section 12.3 du plan) ou sur le plan 2D. Un appui sur le sol pose le
// point, un glissé depuis là règle l'orientation (le robot s'arrête tourné vers la salle) ; glisser un point
// le déplace. Le panneau de droite : nom, autres noms, phrase d'arrivée, x, y et orientation en degrés ;
// ✓ Enregistrer écrit salles.yaml (PUT …/salles?synchroniser=true : chaque salle reçoit son nœud de même id
// dans itineraires.yaml, et l'accueil recopie sa pose dans lieu.yaml et le départ du robot). Les deux vues
// lisent et écrivent la même liste ; Annuler et Rétablir (Ctrl+Z, Ctrl+Y) par historique.js.
//
// Vague 4 (section 11.2 du plan) : le point principal du lieu est la salle qui porte l'étiquette
// « principal » (à défaut, la salle « accueil ») : l'étoile ambre, le badge « principal ». C'est l'accueil :
// le robot y démarre en simulation, on l'y pose au démarrage (« Repérer »), et il y revient après chaque
// visite. « Faire de cette salle l'accueil » déplace l'étiquette ; l'accueil ne se supprime pas sans en
// avoir choisi un autre.

import { api, urlLieu } from '../api.js';
import { sallesDansLOrdre } from '../carte3d/geometrie3d.js';
import { contexte, rechargerLieu } from '../contexte.js';
import { blocAvance, panneauEdition, preparerEcran } from '../coque/ecran.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { Historique } from '../historique.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, iconeOrientee, ll, suivrePointeur } from '../plan.js';

const L = window.L;
const PAS = 0.05;      // m : les salles s'accrochent aux 5 cm
const PAS_ANGLE = 15;  // degrés : l'orientation glissée s'accroche par pas de 15° (valeur exacte dans le panneau)
export const ETIQUETTE_PRINCIPAL = 'principal';
const ID_PRINCIPAL_IMPLICITE = 'accueil';
const AIDES = {
  choisir: 'Cliquez sur un point pour le modifier ; glissez-le pour le déplacer, sa poignée pour le tourner.',
  salle: 'Cliquez sur le sol devant la porte, puis tirez vers la salle.',
  accueil: 'Cliquez là où le robot attend les visiteurs, puis tirez dans le sens où il regarde.',
};

// ---------------------------------------------------------------- point principal (partagé avec Simulation et Monde)

// La salle du point principal d'une liste : celle qui porte l'étiquette ; à défaut, la salle
// « accueil » ; null s'il n'y en a pas (ou s'il y en a deux : salles.yaml les refuse).
export function sallePrincipale(salles) {
  const marquees = salles.filter((s) => (s.etiquettes || []).includes(ETIQUETTE_PRINCIPAL));
  if (marquees.length === 1) return marquees[0];
  if (marquees.length) return null;
  return salles.find((s) => s.id === ID_PRINCIPAL_IMPLICITE) || null;
}

// Icône du point principal : la flèche de la salle (le sens du robot), une étoile au centre.
export function iconePrincipal(theta, classes) {
  const deg = -theta * 180 / Math.PI;     // à l'écran, y vers le bas : on tourne dans l'autre sens
  return L.divIcon({
    className: 'icone-orientee salle principal' + (classes ? ' ' + classes : ''),
    html: '<div class="icone-fleche" style="transform: rotate(' + deg + 'deg)"></div>'
      + '<span class="etoile-principal" aria-hidden="true">★</span>',
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

// Étiquette posée à côté d'une salle sur la carte : son nom, et le badge « principal ».
export function etiquetteSalle(nom, principale) {
  const e = document.createElement('span');
  if (principale) {
    const b = document.createElement('span');
    b.className = 'badge-principal';
    b.textContent = 'principal';
    e.appendChild(b);
    e.appendChild(document.createTextNode(' '));
  }
  e.appendChild(document.createTextNode(nom));
  return e;
}

function copie(v) {
  return JSON.parse(JSON.stringify(v));
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const carte3d = ecran.carte3d;
  const etat = { salles: [], choisi: null, outil: 'choisir', modifie: false, trace: null, idsAuto: new Set(),
    geste: null, charge: false, ferme: false };
  const hist = new Historique();
  const desabonner = [];

  ecran.vue.innerHTML = '<div class="plan" data-role="plan"></div>';
  const plan = creerPlan(ecran.vue.querySelector('[data-role=plan]'));
  const carte = plan.carte;
  const calque = L.layerGroup().addTo(carte);
  const calqueTrace = L.layerGroup().addTo(carte);
  let panneau = null;

  function sallesEtage() {
    return etat.salles.filter((s) => s.etage === etage);
  }

  function salle(id) {
    return etat.salles.find((s) => s.id === id) || null;
  }

  function principale() {
    return sallePrincipale(etat.salles);
  }

  // Toute modification passe par ici : copie pour « annuler », puis redessin
  function modifier(f, sansHistorique) {
    if (!sansHistorique) hist.noter(etat.salles);
    f();
    etat.modifie = true;
    rafraichir();
  }

  function idNouvelle() {
    return G.idLibre('salle', etat.salles.map((s) => s.id));
  }

  // « Faire de cette salle l'accueil » : l'étiquette passe à cette salle, et à elle seule
  function fairePrincipal(s) {
    const avant = principale();
    modifier(() => {
      etat.salles.forEach((x) => {
        const autres = (x.etiquettes || []).filter((e) => e !== ETIQUETTE_PRINCIPAL);
        if (x === s) x.etiquettes = [ETIQUETTE_PRINCIPAL].concat(autres);
        else if (autres.length) x.etiquettes = autres;
        else delete x.etiquettes;
      });
    });
    coque.message('« ' + s.nom + ' » sera l\'accueil (le point principal) à l\'enregistrement'
      + (avant && avant !== s ? ', à la place de « ' + avant.nom + ' »' : '') + '.', 'info');
  }

  function refuserSuppression(s) {
    coque.message('« ' + s.nom + ' » est le point principal du lieu (l\'accueil : le robot y démarre et y revient '
      + 'après chaque visite). Choisissez d\'abord un autre point principal (« Faire de cette salle l\'accueil » sur '
      + 'une autre salle), puis supprimez celle-ci.', 'erreur');
  }

  function supprimer(s) {
    if (s === principale()) {
      refuserSuppression(s);
      return;
    }
    modifier(() => {
      etat.salles = etat.salles.filter((x) => x !== s);
      if (etat.choisi === s.id) etat.choisi = null;
    });
  }

  // Pose (x, y, theta) de l'accueil ; le crée s'il n'existe pas encore
  function poserAccueil(x, y, theta) {
    let p = principale();
    if (!p) {
      const id = salle(ID_PRINCIPAL_IMPLICITE) ? idNouvelle() : ID_PRINCIPAL_IMPLICITE;
      p = { id: id, nom: 'Accueil', alias: ['accueil'], etage: etage, pose: { x: x, y: y, theta: theta },
        phrase_arrivee: '', etiquettes: [ETIQUETTE_PRINCIPAL] };
      etat.salles.push(p);
    }
    p.etage = etage;
    p.pose = { x: G.arrondir(x, 3), y: G.arrondir(y, 3), theta: G.arrondir(G.normaliserAngle(theta), 4) };
    return p;
  }

  function nouvelleSalle(id, x, y, theta) {
    const s = { id: id, nom: 'Nouvelle salle', alias: [], etage: etage,
      pose: { x: G.arrondir(x, 3), y: G.arrondir(y, 3), theta: G.arrondir(G.normaliserAngle(theta), 4) },
      phrase_arrivee: '' };
    etat.idsAuto.add(id);
    etat.salles.push(s);
    return s;
  }

  // ------------------------------------------------------------ plan 2D

  function poigneeOrientation(s, m, estPrincipale) {
    // poignée d'orientation, à 1 m devant la salle (1,5 m pour la flèche du point principal)
    const r = estPrincipale ? 1.5 : 1.0;
    const icone = (theta) => (estPrincipale ? iconePrincipal(theta, s.id === etat.choisi ? 'choisi' : '')
      : iconeOrientee('salle choisi', theta));
    const poignee = L.marker(ll(s.pose.x + r * Math.cos(s.pose.theta), s.pose.y + r * Math.sin(s.pose.theta)), {
      icon: L.divIcon({ className: 'poignee' + (estPrincipale ? ' poignee-principal' : ''), iconSize: [18, 18], iconAnchor: [9, 9] }),
      draggable: true, keyboard: false,
      title: estPrincipale ? 'Glisser pour tourner la flèche de l\'accueil (le sens du robot)' : 'Glisser pour orienter',
    });
    const ligne = L.polyline([ll(s.pose.x, s.pose.y), poignee.getLatLng()],
      { className: 'ligne-poignee' + (estPrincipale ? ' fleche-principal' : ''), interactive: false });
    poignee.on('dragstart', () => { etat.choisi = s.id; });
    poignee.on('drag', () => {
      const q = poignee.getLatLng();
      ligne.setLatLngs([ll(s.pose.x, s.pose.y), q]);
      m.setIcon(icone(G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE)));
    });
    poignee.on('dragend', () => {
      const q = poignee.getLatLng();
      modifier(() => { s.pose.theta = G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE); });
    });
    ligne.addTo(calque);
    poignee.addTo(calque);
  }

  function dessiner() {
    calque.clearLayers();
    const p = principale();
    sallesEtage().forEach((s) => {
      const choisie = s.id === etat.choisi;
      const estPrincipale = s === p;
      const m = L.marker(ll(s.pose.x, s.pose.y), {
        icon: estPrincipale ? iconePrincipal(s.pose.theta, choisie ? 'choisi' : '')
          : iconeOrientee('salle' + (choisie ? ' choisi' : ''), s.pose.theta),
        draggable: etat.outil === 'choisir', keyboard: false,
        title: estPrincipale ? s.nom + ' (point principal)' : s.nom,
        zIndexOffset: estPrincipale ? 500 : 0,
      });
      m.bindTooltip(etiquetteSalle(s.nom, estPrincipale), { permanent: true, direction: 'right', offset: [14, 0], className: 'etiquette' });
      m.on('click', () => choisir(s.id));
      m.on('dragstart', () => { etat.choisi = s.id; });
      m.on('dragend', () => {
        const q = m.getLatLng();
        modifier(() => {
          s.pose.x = G.accrocher(q.lng, PAS);
          s.pose.y = G.accrocher(q.lat, PAS);
        });
      });
      m.addTo(calque);
      // la flèche de l'accueil se tourne toujours ; celle d'une autre salle, une fois choisie
      if (etat.outil === 'choisir' && (choisie || estPrincipale)) poigneeOrientation(s, m, estPrincipale);
    });
  }

  function dessinerTrace() {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (!t) return;
    const icone = t.accueil ? iconePrincipal(t.theta, 'trace') : iconeOrientee('salle trace', t.theta);
    L.marker(ll(t.x, t.y), { icon: icone, interactive: false }).addTo(calqueTrace);
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: (p) => {
      if (etat.outil !== 'salle' && etat.outil !== 'accueil') return false;
      const q = G.accrocherPoint(p, PAS);
      const p0 = principale();
      etat.trace = { x: q[0], y: q[1], theta: etat.outil === 'accueil' && p0 ? p0.pose.theta : 0,
        accueil: etat.outil === 'accueil' };
      dessinerTrace();
      return true;
    },
    deplacer: (p) => {
      const t = etat.trace;
      if (!t) return;
      if (G.distance([t.x, t.y], p) > 0.2) t.theta = G.accrocherAngle(Math.atan2(p[1] - t.y, p[0] - t.x), PAS_ANGLE);
      dessinerTrace();
    },
    fin: () => {
      const t = etat.trace;
      etat.trace = null;
      dessinerTrace();
      if (!t) return;
      if (t.accueil) {
        modifier(() => { etat.choisi = poserAccueil(t.x, t.y, t.theta).id; });
      } else {
        modifier(() => { etat.choisi = nouvelleSalle(idNouvelle(), t.x, t.y, t.theta).id; });
      }
      choisirOutil('choisir');
      focaliserNom();
    },
    annuler: () => { etat.trace = null; dessinerTrace(); },
  });

  // ------------------------------------------------------------ carte 3D

  function afficher3D() {
    if (!carte3d) return;
    const p = principale();
    carte3d.afficherSalles(etat.salles, p ? p.id : null);
    // la même salle choisie dans la vue 3D et dans le panneau (aucune : plus d'anneau ni de poignée)
    carte3d.choisir(etat.choisi ? 'salle' : null, etat.choisi || null);
  }

  // surPose de la carte 3D : {outil, genre, id, x, y, theta, fini, geste, annule}
  function recevoirPose(e) {
    if (!e || e.genre !== 'salle' || etat.ferme) return;
    if (e.annule) {
      if (etat.geste) {
        etat.salles = etat.geste.avant;
        etat.geste = null;
        rafraichir();
      }
      return;
    }
    if (!etat.geste) etat.geste = { avant: copie(etat.salles), id: e.id || null };
    let s = null;
    if (e.outil === 'accueil') {
      s = poserAccueil(e.x, e.y, e.theta === null || e.theta === undefined ? (principale() ? principale().pose.theta : 0) : e.theta);
    } else {
      const id = e.id || etat.geste.id || null;
      s = id ? salle(id) : null;
      if (!s) {
        s = nouvelleSalle(id || idNouvelle(), e.x, e.y, e.theta || 0);
        etat.geste.id = s.id;
      } else {
        s.pose = { x: G.arrondir(e.x, 3), y: G.arrondir(e.y, 3),
          theta: G.arrondir(G.normaliserAngle(e.theta === null || e.theta === undefined ? s.pose.theta : e.theta), 4) };
      }
    }
    etat.choisi = s.id;
    if (e.fini) {
      hist.noter(etat.geste.avant);
      etat.geste = null;
      etat.modifie = true;
      const pose = e.outil === 'salle' || e.outil === 'accueil';
      rafraichir();
      if (pose) {
        choisirOutil('choisir');
        if (e.outil === 'salle') focaliserNom();
        // un simple clic : la salle regarde vers 0° ; on dit comment la tourner
        if (e.outil === 'salle' && e.geste === 'poser' && e.oriente === false) {
          coque.message('Salle posée, tournée vers 0° (la droite du plan) : glissez la poignée blanche au bout de sa '
            + 'flèche pour la tourner, ou corrigez l\'orientation à droite.', 'info');
        }
      }
    } else {
      // pendant le geste : le plan 2D et le panneau suivent sans tout redessiner
      dessiner();
      majChampsPose(s);
    }
  }

  if (carte3d) {
    // seulement les salles : un nœud d'itinéraire ne se glisse pas depuis cet écran
    desabonner.push(carte3d.surPose(recevoirPose, { genres: ['salle'] }));
  }

  // ------------------------------------------------------------ outils

  function choisirOutil(id) {
    etat.outil = id;
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    if (carte3d) {
      if (id === 'salle') carte3d.outil('salle', { id: null });
      else if (id === 'accueil') carte3d.outil('accueil', { id: principale() ? principale().id : null });
      else carte3d.outil('naviguer');
    }
    coque.activer(id === 'choisir' ? null : id);
    coque.aide(AIDES[id]);
    dessiner();
    majPanneau();
  }

  function choisir(id) {
    etat.choisi = id;
    if (carte3d) carte3d.choisir('salle', id);
    coque.choisirDansArbre(id ? 'salle' : null, id);
    rafraichir();
  }

  function focaliserNom() {
    const champ = ecran.panneau.querySelector('[data-champ="nom"] input');
    if (champ) {
      champ.focus();
      champ.select();
    }
  }

  // ------------------------------------------------------------ panneau

  function badge(parent) {
    return parent.appendChild(F.el('span', 'badge-principal', 'principal'));
  }

  const champsPose = {};

  function majChampsPose(s) {
    if (!s || s.id !== etat.choisi) return;
    const ecrireChamp = (cle, v, d) => {
      if (champsPose[cle] && document.activeElement !== champsPose[cle]) {
        champsPose[cle].value = String(Math.round(v * Math.pow(10, d)) / Math.pow(10, d));
      }
    };
    ecrireChamp('x', s.pose.x, 3);
    ecrireChamp('y', s.pose.y, 3);
    ecrireChamp('theta', G.degres(s.pose.theta), 1);
  }

  function actionsEdition() {
    return { modifie: () => etat.modifie, enregistrer: enregistrer, annuler: abandonner };
  }

  function majPanneau() {
    if (etat.ferme) return;
    const s = salle(etat.choisi);
    const p = principale();
    const titre = s ? (s === p ? 'Accueil' : 'Salle') : 'Points de l\'étage';
    panneau = panneauEdition(ecran.panneau, titre, null, actionsEdition());
    const z = panneau.corps;
    Object.keys(champsPose).forEach((k) => delete champsPose[k]);
    if (s) {
      const estPrincipale = s === p;
      if (estPrincipale) {
        const t = F.paragraphe(z, 'Le robot y démarre, y attend les visiteurs et y revient après chaque visite.', 'panneau-note note-principal');
        t.insertBefore(document.createTextNode(' '), t.firstChild);
        t.insertBefore(badge(t), t.firstChild);
      }
      const champNom = F.champTexte(z, 'Nom', s.nom, (v) => modifier(() => {
        s.nom = v.trim() || s.nom;
        if (etat.idsAuto.has(s.id)) {
          // identifiant fabriqué depuis le nom, tant que l'utilisateur ne l'a pas choisi lui-même
          const nouvel = G.idDepuisNom(s.nom);
          if (nouvel && !G.verifierId(nouvel, etat.salles.filter((x) => x !== s).map((x) => x.id))) {
            etat.idsAuto.delete(s.id);
            etat.idsAuto.add(nouvel);
            s.id = nouvel;
            etat.choisi = nouvel;
          }
        }
      }));
      champNom.parentNode.setAttribute('data-champ', 'nom');
      const alias = F.champTexte(z, 'Autres noms', s.alias.join(', '), (v) => modifier(() => {
        s.alias = v.split(',').map((a) => a.trim()).filter((a) => a);
      }), { indice: 'ex. labo de physique, b204' });
      alias.parentNode.setAttribute('data-champ', 'alias');
      const phrase = F.champTexte(z, 'Phrase à l\'arrivée', s.phrase_arrivee, (v) => modifier(() => { s.phrase_arrivee = v.trim(); }),
        { lignes: 2, indice: 'Vide : le robot annonce le nom de la salle.' });
      phrase.parentNode.setAttribute('data-champ', 'phrase');
      const pose = F.el('div', 'champs-pose');
      champsPose.x = F.champNombre(pose, 'x', s.pose.x, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.x = G.arrondir(v, 3); }));
      champsPose.x.parentNode.setAttribute('data-champ', 'x');
      champsPose.y = F.champNombre(pose, 'y', s.pose.y, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.y = G.arrondir(v, 3); }));
      champsPose.y.parentNode.setAttribute('data-champ', 'y');
      champsPose.theta = F.champNombre(pose, 'Orientation', G.degres(s.pose.theta), { pas: 15, unite: '°', decimales: 1 },
        (v) => modifier(() => { s.pose.theta = G.arrondir(G.normaliserAngle(G.radians(v)), 4); }));
      champsPose.theta.parentNode.setAttribute('data-champ', 'orientation');
      champsPose.theta.title = '0° : vers l\'est (la droite du plan), 90° : vers le nord (le haut).';
      z.appendChild(pose);
      const actions = F.el('div', 'formulaire-ligne');
      if (!estPrincipale) {
        F.bouton(actions, 'Faire de cette salle l\'accueil', () => fairePrincipal(s), 'bouton bouton-faire-principal');
      }
      // le point principal ne se supprime pas : on dit pourquoi et quoi faire
      F.bouton(actions, 'Supprimer', () => supprimer(s), 'bouton bouton-danger').setAttribute('data-role', 'supprimer-salle');
      F.bouton(actions, 'Fermer', () => choisir(null), 'bouton bouton-discret');
      z.appendChild(actions);
      const avance = blocAvance(z, 'Avancé');
      const figee = estPrincipale || s.id === ID_PRINCIPAL_IMPLICITE;
      const champId = F.champTexte(avance, 'Identifiant', s.id, (v) => {
        v = v.trim();
        const refus = G.verifierId(v, etat.salles.filter((x) => x !== s).map((x) => x.id), 'une salle');
        if (refus) {
          coque.message(refus, 'erreur');
          majPanneau();
          return;
        }
        modifier(() => {
          etat.idsAuto.delete(s.id);
          s.id = v;
          etat.choisi = v;
        });
      }, { lectureSeule: figee });
      champId.parentNode.setAttribute('data-champ', 'id');
      if (figee) {
        champId.title = estPrincipale ? 'L\'accueil garde son identifiant (son nœud dans les itinéraires a le même).'
          : 'L\'accueil garde toujours l\'identifiant « accueil ».';
      }
      F.paragraphe(avance, 'Chaque salle a un nœud de même identifiant dans les itinéraires : reliez-le au reste '
        + '(Placer › Relier).', 'panneau-note');
      return;
    }
    const ici = sallesEtage();
    const liste = F.el('ul', 'liste-choix liste-points');
    // dans l'ordre des épingles de la vue 3D, avec leur numéro
    const tries = sallesDansLOrdre(ici, p ? p.id : null);
    tries.forEach((n) => {
      const x = n.salle;
      const li = F.el('li');
      const b = F.bouton(li, x.nom, () => {
        choisir(x.id);
        if (coque.vue() === 'plan') carte.panTo(ll(x.pose.x, x.pose.y));
        else if (carte3d) carte3d.centrerSur(x.pose.x, x.pose.y);
      }, 'ligne-point' + (x === p ? ' ligne-accueil' : ''));
      b.setAttribute('data-salle', x.id);
      if (x === p) {
        b.insertBefore(F.el('span', 'etoile', '★'), b.firstChild);
        badge(b);
      } else if (n.numero !== null && n.numero !== undefined) {
        b.insertBefore(F.el('span', 'numero-salle', String(n.numero)), b.firstChild);
      }
      liste.appendChild(li);
    });
    if (!ici.length) F.paragraphe(z, 'Aucune salle : choisissez « Salle » dans le ruban, puis cliquez sur le sol.');
    z.appendChild(liste);
    if (!p) {
      F.paragraphe(z, 'Ce lieu n\'a pas encore d\'accueil (le point principal, où le robot démarre et revient) : '
        + 'choisissez « Accueil » dans le ruban.', 'panneau-note note-sans-principal');
    } else if (p.etage !== etage) {
      F.paragraphe(z, 'L\'accueil « ' + p.nom + ' » est sur un autre étage (' + p.etage + ').', 'panneau-note');
    }
  }

  function rafraichir() {
    if (etat.ferme) return;
    dessiner();
    afficher3D();
    majPanneau();
  }

  // ------------------------------------------------------------ enregistrer, annuler

  async function enregistrer() {
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/salles?synchroniser=true', etat.salles);
      etat.modifie = false;
      // les fichiers mis à jour en plus, dits avec des mots (itineraires.yaml : les itinéraires, lieu.yaml…)
      const NOMS_FICHIERS = { 'itineraires.yaml': 'les itinéraires', 'lieu.yaml': 'la fiche du lieu' };
      const autres = r.enregistre.filter((f) => f !== 'salles.yaml').map((f) => NOMS_FICHIERS[f] || 'le départ du robot');
      const uniques = autres.filter((x, i) => autres.indexOf(x) === i);
      const p = principale();
      afficherRapport(r.rapport, 'Salles enregistrées' + (uniques.length ? ' ; mis à jour aussi : ' + uniques.join(', ') : '') + '.'
        + (p ? ' Accueil : « ' + p.nom + ' ».' : ''));
      rechargerLieu().catch(() => {});
      coque.lieuModifie('salles');
      majPanneau();
      return true;
    } catch (e) {
      afficherErreur(e);
      return false;
    }
  }

  async function abandonner() {
    if (!etat.modifie) return;
    if (!(await coque.confirmer('Abandonner les changements des salles et revenir à la version enregistrée ?',
      { titre: 'Annuler les modifications', ok: 'Abandonner', annuler: 'Garder', danger: true }))) return;
    await charger();
  }

  function defaire() {
    const precedent = hist.annuler(etat.salles);
    if (!precedent) return;
    etat.salles = precedent;
    etat.modifie = true;
    if (!salle(etat.choisi)) etat.choisi = null;
    rafraichir();
  }

  function refaire() {
    const suivant = hist.refaire(etat.salles);
    if (!suivant) return;
    etat.salles = suivant;
    etat.modifie = true;
    if (!salle(etat.choisi)) etat.choisi = null;
    rafraichir();
  }

  function clavier(ev) {
    const c = ev.target;
    if (c && (c.tagName === 'INPUT' || c.tagName === 'TEXTAREA' || c.tagName === 'SELECT')) return;
    if (ev.key === 'Escape') {
      etat.trace = null;
      dessinerTrace();
      if (etat.outil !== 'choisir') choisirOutil('choisir');
    } else if ((ev.key === 'Delete' || ev.key === 'Backspace') && salle(etat.choisi)) {
      ev.preventDefault();
      supprimer(salle(etat.choisi));
    }
  }
  document.addEventListener('keydown', clavier);

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      afficherErreur(e);
    }
    etat.modifie = false;
    etat.charge = true;
    hist.vider();
    if (!salle(etat.choisi)) etat.choisi = null;
    const outil = etat.outilDemande || 'choisir';
    etat.outilDemande = null;
    choisirOutil(outil);
    rafraichir();
  }

  function commande(nom) {
    if (nom === 'salle' || nom === 'accueil') {
      if (!etat.charge) {
        etat.outilDemande = nom;
        return;
      }
      choisirOutil(etat.outil === nom ? 'choisir' : nom);
    }
  }

  ecran.vue.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  commande(ecran.commande);
  charger().finally(() => ecran.vue.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    enregistrer: enregistrer,
    defaire: defaire,
    refaire: refaire,
    peutDefaire: () => hist.peutAnnuler,
    peutRefaire: () => hist.peutRefaire,
    commande: commande,
    selectionner: (genre, id) => {
      if (genre !== 'salle') return;
      choisir(salle(id) ? id : null);
      const s = salle(id);
      if (s && coque.vue() === 'plan') carte.panTo(ll(s.pose.x, s.pose.y));
    },
    vue: () => {
      plan.carte.invalidateSize();
      if (plan.cadrageEnAttente) plan.recadrer();
      choisirOutil(etat.outil);
    },
    recadrer: () => plan.recadrer(),
    fermer: () => {
      etat.ferme = true;
      document.removeEventListener('keydown', clavier);
      desabonner.forEach((f) => f());
      if (carte3d) carte3d.outil('naviguer');
      arreterPointeur();
      plan.detruire();
    },
  };
}
