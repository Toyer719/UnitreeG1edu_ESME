// Écran Itinéraires (Placer › Nœud, Placer › Relier) : le graphe du guide, sur le plan 2D. Clic pour
// poser un nœud, clic sur deux nœuds pour les relier par un couloir. Un couloir de plus de 8 m est
// signalé (le vrai robot avance par tronçons de 8 m au plus) : « Couper en deux » ajoute un nœud au
// milieu. Le panneau montre l'élément choisi ; ✓ Enregistrer écrit itineraires.yaml ; Annuler et
// Rétablir par historique.js ; la vue 3D de la coque suit les changements.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { blocAvance, panneauEdition, preparerEcran } from '../coque/ecran.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { Historique } from '../historique.js';
import { afficherErreur, afficherRapport } from '../messages.js';
import { creerPlan, ll } from '../plan.js';

const L = window.L;
const PAS = 0.25;

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez sur un nœud ou un couloir pour le modifier ; glissez un nœud pour le déplacer." },
  { id: 'noeud', texte: 'Nœud', aide: "Cliquez pour poser un point de passage, au milieu des couloirs et à chaque croisement." },
  { id: 'relier', texte: 'Relier', aide: "Cliquez sur un nœud, puis sur un autre : un couloir les relie. Clic dans le vide (ou Échap) pour repartir." },
];

function pluriel(n, mot) {
  return n + ' ' + mot + (n > 1 ? 's' : '');
}

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const carte3d = ecran.carte3d;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { itin: { noeuds: {}, couloirs: [] }, salles: [], outil: 'choisir', choisi: null, depuis: null, modifie: false,
    charge: false, outilDemande: null };
  const hist = new Historique();

  ecran.vue.innerHTML = '<div class="plan" data-role="plan"></div>';
  const plan = creerPlan(ecran.vue.querySelector('[data-role=plan]'));
  const carte = plan.carte;
  const calqueCouloirs = L.layerGroup().addTo(carte);
  const calqueNoeuds = L.layerGroup().addTo(carte);

  const noeuds = () => etat.itin.noeuds;
  const estSalle = (id) => etat.salles.some((s) => s.id === id);
  // un nœud de salle se nomme comme sa salle ; les autres gardent leur identifiant
  const nomNoeud = (id) => {
    const s = etat.salles.find((x) => x.id === id);
    return s ? s.nom : id;
  };
  const longueur = (c) => G.distance([noeuds()[c[0]].x, noeuds()[c[0]].y], [noeuds()[c[1]].x, noeuds()[c[1]].y]);
  const memeCouloir = (c, a, b) => (c[0] === a && c[1] === b) || (c[0] === b && c[1] === a);

  function modifier(f) {
    hist.noter(etat.itin);
    f();
    etat.modifie = true;
    rafraichir();
  }

  function dessiner() {
    calqueCouloirs.clearLayers();
    calqueNoeuds.clearLayers();
    etat.itin.couloirs.forEach((c, i) => {
      const a = noeuds()[c[0]], b = noeuds()[c[1]];
      if (!a || !b || a.etage !== etage || b.etage !== etage) return;
      const trop = longueur(c) > G.COULOIR_MAX;
      const choisi = etat.choisi && etat.choisi.genre === 'couloir' && etat.choisi.indice === i;
      const ligne = L.polyline([ll(a.x, a.y), ll(b.x, b.y)], {
        className: 'couloir' + (trop ? ' trop-long' : '') + (choisi ? ' choisi' : ''), weight: 6,
      });
      ligne.bindTooltip(G.nb(longueur(c), 1) + ' m' + (trop ? ' : plus de 8 m !' : ''), { sticky: true });
      ligne.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        if (etat.outil !== 'choisir') return;
        etat.choisi = { genre: 'couloir', indice: i };
        rafraichir();
      });
      ligne.addTo(calqueCouloirs);
    });
    Object.keys(noeuds()).forEach((id) => {
      const n = noeuds()[id];
      if (n.etage !== etage) return;
      const choisi = (etat.choisi && etat.choisi.genre === 'noeud' && etat.choisi.id === id) || etat.depuis === id;
      const m = L.marker(ll(n.x, n.y), {
        icon: L.divIcon({ className: 'noeud' + (estSalle(id) ? ' noeud-salle' : '') + (choisi ? ' choisi' : ''), iconSize: [18, 18], iconAnchor: [9, 9] }),
        draggable: etat.outil === 'choisir', keyboard: false,
      });
      m.bindTooltip(nomNoeud(id), { permanent: estSalle(id), direction: 'top', offset: [0, -8], className: 'etiquette' });
      m.on('click', (e) => {
        L.DomEvent.stopPropagation(e);
        cliquerNoeud(id);
      });
      m.on('dragend', () => {
        const p = m.getLatLng();
        modifier(() => {
          n.x = G.accrocher(p.lng, PAS);
          n.y = G.accrocher(p.lat, PAS);
        });
        if (estSalle(id)) {
          coque.message('Le nœud « ' + id + ' » est celui d\'une salle : il doit rester à la position de la salle. '
            + 'Déplacez plutôt la salle (Placer › Salle).', 'avertissement');
        }
      });
      m.addTo(calqueNoeuds);
    });
  }

  function cliquerNoeud(id) {
    if (etat.outil === 'relier') {
      if (!etat.depuis) {
        etat.depuis = id;
      } else if (etat.depuis !== id) {
        const a = etat.depuis;
        if (etat.itin.couloirs.some((c) => memeCouloir(c, a, id))) {
          coque.message('Ces deux nœuds sont déjà reliés.', 'info');
        } else {
          modifier(() => etat.itin.couloirs.push([a, id]));
          const l = longueur([a, id]);
          if (l > G.COULOIR_MAX) {
            coque.message('Ce couloir fait ' + G.nb(l, 1) + ' m : au-delà de 8 m, le vrai robot ne peut pas le parcourir d\'un coup. '
              + 'Choisissez-le, puis « Couper en deux ».', 'avertissement');
          }
        }
        etat.depuis = id;      // on continue depuis ce nœud
      }
      rafraichir();
      return;
    }
    if (etat.outil === 'choisir') {
      etat.choisi = { genre: 'noeud', id: id };
      rafraichir();
    }
  }

  carte.on('click', (e) => {
    if (etat.outil === 'noeud') {
      const p = G.accrocherPoint([e.latlng.lng, e.latlng.lat], PAS);
      const id = G.idLibre('n', Object.keys(noeuds()));
      modifier(() => { noeuds()[id] = { etage: etage, x: p[0], y: p[1] }; });
    } else if (etat.outil === 'choisir') {
      etat.choisi = null;
      rafraichir();
    } else if (etat.outil === 'relier' && etat.depuis) {
      etat.depuis = null;         // repartir d'un autre nœud
      rafraichir();
    }
  });

  function choisirOutil(id) {
    if (!OUTILS.some((o) => o.id === id)) id = 'choisir';
    etat.outil = id;
    etat.depuis = null;
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    coque.activer(id === 'choisir' ? null : id);
    coque.aide(OUTILS.find((o) => o.id === id).aide);
    rafraichir();
  }

  function couperEnDeux(i) {
    const c = etat.itin.couloirs[i];
    const a = noeuds()[c[0]], b = noeuds()[c[1]];
    const id = G.idLibre('n', Object.keys(noeuds()));
    modifier(() => {
      noeuds()[id] = { etage: etage, x: G.arrondir((a.x + b.x) / 2), y: G.arrondir((a.y + b.y) / 2) };
      etat.itin.couloirs.splice(i, 1, [c[0], id], [id, c[1]]);
      etat.choisi = null;
    });
  }

  function renommer(ancien, nouveau) {
    const n = noeuds()[ancien];
    const copie = {};
    Object.keys(noeuds()).forEach((k) => { copie[k === ancien ? nouveau : k] = k === ancien ? n : noeuds()[k]; });
    etat.itin.noeuds = copie;
    etat.itin.couloirs = etat.itin.couloirs.map((c) => c.map((x) => (x === ancien ? nouveau : x)));
  }

  function panneau() {
    const ch = etat.choisi;
    const titre = ch && ch.genre === 'noeud' ? 'Nœud' : (ch && ch.genre === 'couloir' ? 'Couloir' : 'Itinéraires');
    const z = panneauEdition(ecran.panneau, titre, null,
      { modifie: () => etat.modifie, enregistrer: enregistrer, annuler: abandonner }).corps;
    if (ch && ch.genre === 'noeud' && noeuds()[ch.id]) {
      const n = noeuds()[ch.id];
      F.titre(z, '« ' + nomNoeud(ch.id) + ' »');
      if (estSalle(ch.id)) {
        F.paragraphe(z, 'C\'est le nœud de la salle « ' + nomNoeud(ch.id) + ' » : il suit la salle (Placer › Salle).', 'panneau-note');
        F.valeur(z, 'Position', '[' + G.nb(n.x) + ' ; ' + G.nb(n.y) + '] m');
      } else {
        F.champNombre(z, 'x', n.x, { pas: PAS, unite: 'm' }, (v) => modifier(() => { n.x = v; }));
        F.champNombre(z, 'y', n.y, { pas: PAS, unite: 'm' }, (v) => modifier(() => { n.y = v; }));
        F.champTexte(blocAvance(z, 'Avancé'), 'Identifiant', ch.id, (v) => {
          v = v.trim();
          const refus = G.verifierId(v, Object.keys(noeuds()).concat(etat.salles.map((s) => s.id)).filter((x) => x !== ch.id), 'un nœud ou une salle');
          if (refus) {
            coque.message(refus, 'erreur');
            panneau();
            return;
          }
          modifier(() => {
            renommer(ch.id, v);
            etat.choisi = { genre: 'noeud', id: v };
          });
        });
      }
      const voisins = etat.itin.couloirs.filter((c) => c.indexOf(ch.id) >= 0).map((c) => (c[0] === ch.id ? c[1] : c[0]));
      F.valeur(z, 'Relié à', voisins.length ? voisins.map(nomNoeud).join(', ') : 'rien (le guide ne pourra pas y passer)');
      F.bouton(z, 'Supprimer le nœud', () => modifier(() => {
        delete noeuds()[ch.id];
        etat.itin.couloirs = etat.itin.couloirs.filter((c) => c.indexOf(ch.id) < 0);
        etat.choisi = null;
      }), 'bouton bouton-danger');
      return;
    }
    if (ch && ch.genre === 'couloir' && etat.itin.couloirs[ch.indice]) {
      const c = etat.itin.couloirs[ch.indice];
      F.titre(z, 'Couloir ' + nomNoeud(c[0]) + ' – ' + nomNoeud(c[1]));
      const l = longueur(c);
      F.valeur(z, 'Longueur', G.nb(l, 2) + ' m');
      if (l > G.COULOIR_MAX) F.paragraphe(z, 'Plus de 8 m : coupez-le en deux (ou plus).', 'panneau-alerte');
      F.bouton(z, 'Couper en deux', () => couperEnDeux(ch.indice));
      F.bouton(z, 'Supprimer le couloir', () => modifier(() => {
        etat.itin.couloirs.splice(ch.indice, 1);
        etat.choisi = null;
      }), 'bouton bouton-danger');
      return;
    }
    const ids = Object.keys(noeuds()).filter((k) => noeuds()[k].etage === etage);
    const couloirs = etat.itin.couloirs.filter((c) => noeuds()[c[0]] && noeuds()[c[1]] && noeuds()[c[0]].etage === etage);
    F.paragraphe(z, pluriel(ids.length, 'nœud') + ', ' + pluriel(couloirs.length, 'couloir')
      + ' : le guide va de nœud en nœud par le plus court chemin.');
    const trop = couloirs.filter((c) => longueur(c) > G.COULOIR_MAX);
    if (trop.length) {
      const p = F.paragraphe(z, trop.length + ' couloir(s) de plus de 8 m (en rouge) :', 'panneau-alerte');
      const ul = F.el('ul', 'liste-choix');
      trop.forEach((c) => {
        const li = F.el('li');
        F.bouton(li, nomNoeud(c[0]) + ' – ' + nomNoeud(c[1]) + ' : ' + G.nb(longueur(c), 1) + ' m', () => {
          etat.choisi = { genre: 'couloir', indice: etat.itin.couloirs.indexOf(c) };
          rafraichir();
        }, 'bouton-lien');
        ul.appendChild(li);
      });
      p.after(ul);
    }
    const isoles = etat.salles.filter((s) => s.etage === etage && !etat.itin.couloirs.some((c) => c.indexOf(s.id) >= 0));
    if (isoles.length) {
      F.paragraphe(z, (isoles.length > 1 ? 'Salles reliées à rien : ' : 'Salle reliée à rien : ')
        + isoles.map((s) => '« ' + s.nom + ' »').join(', ') + '. Reliez ' + (isoles.length > 1 ? 'leur nœud' : 'son nœud')
        + ' (carré bleu) au reste : Placer › Relier.', 'panneau-alerte');
    }
    F.paragraphe(z, 'Les nœuds carrés bleus sont ceux des salles : ils se créent en enregistrant les salles.', 'panneau-note');
  }

  function afficher3D() {
    if (carte3d) carte3d.afficherItineraires(etat.itin);
  }

  function rafraichir() {
    dessiner();
    afficher3D();
    panneau();
  }

  function clavier(ev) {
    const c = ev.target;
    if (c && (c.tagName === 'INPUT' || c.tagName === 'TEXTAREA' || c.tagName === 'SELECT')) return;
    if (ev.key === 'Escape') {
      etat.depuis = null;
      etat.choisi = null;
      rafraichir();
    }
  }
  document.addEventListener('keydown', clavier);

  async function enregistrer() {
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/itineraires', etat.itin);
      etat.modifie = false;
      afficherRapport(r.rapport, 'Itinéraires enregistrés.');
      coque.lieuModifie('itineraires');
      panneau();
      return true;
    } catch (e) {
      afficherErreur(e);
      return false;
    }
  }

  async function abandonner() {
    if (!etat.modifie) return;
    if (!(await coque.confirmer('Abandonner les changements des itinéraires et revenir à la version enregistrée ?',
      { titre: 'Annuler les modifications', ok: 'Abandonner', annuler: 'Garder', danger: true }))) return;
    await charger();
  }

  function deplacerHistorique(sens) {
    const autre = sens < 0 ? hist.annuler(etat.itin) : hist.refaire(etat.itin);
    if (!autre) return;
    etat.itin = autre;
    etat.modifie = true;
    if (etat.choisi && etat.choisi.genre === 'noeud' && !noeuds()[etat.choisi.id]) etat.choisi = null;
    if (etat.choisi && etat.choisi.genre === 'couloir' && !etat.itin.couloirs[etat.choisi.indice]) etat.choisi = null;
    rafraichir();
  }

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.itin = await api.lire(urlLieu(lieu) + '/itineraires');
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      afficherErreur(e);
    }
    etat.modifie = false;
    etat.charge = true;
    hist.vider();
    const outil = etat.outilDemande || 'choisir';
    etat.outilDemande = null;
    choisirOutil(outil);
  }

  function commande(nom) {
    if (!OUTILS.some((o) => o.id === nom)) return;
    if (!etat.charge) {
      etat.outilDemande = nom;
      return;
    }
    choisirOutil(etat.outil === nom ? 'choisir' : nom);
  }

  ecran.vue.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  commande(ecran.commande);
  charger().finally(() => ecran.vue.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    enregistrer: enregistrer,
    defaire: () => deplacerHistorique(-1),
    refaire: () => deplacerHistorique(1),
    peutDefaire: () => hist.peutAnnuler,
    peutRefaire: () => hist.peutRefaire,
    commande: commande,
    selectionner: (genre, id) => {
      if (genre === 'noeud' && noeuds()[id]) {
        etat.choisi = { genre: 'noeud', id: id };
        carte.panTo(ll(noeuds()[id].x, noeuds()[id].y));
      } else if (genre === 'couloir' && etat.itin.couloirs[Number(id)]) {
        etat.choisi = { genre: 'couloir', indice: Number(id) };
      } else {
        return;
      }
      rafraichir();
    },
    vue: () => {
      plan.carte.invalidateSize();
      if (plan.cadrageEnAttente) plan.recadrer();
    },
    recadrer: () => plan.recadrer(),
    fermer: () => {
      document.removeEventListener('keydown', clavier);
      plan.detruire();
    },
  };
}
