// Écran Itinéraires : le graphe du guide. Clic pour poser un nœud, clic sur deux nœuds pour
// les relier par un couloir. Un couloir de plus de 8 m est signalé (le vrai robot avance par
// tronçons de 8 m au plus) : « Couper en deux » ajoute un nœud au milieu.

import { api, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, ll } from '../plan.js';

const L = window.L;
const PAS = 0.25;

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez sur un nœud ou un couloir pour le modifier ; faites glisser un nœud pour le déplacer." },
  { id: 'noeud', texte: 'Ajouter un nœud', aide: "Cliquez pour poser un nœud (un point de passage), au milieu des couloirs et à chaque croisement." },
  { id: 'relier', texte: 'Relier deux nœuds', aide: "Cliquez sur un nœud, puis sur un autre : un couloir les relie, en ligne droite. Continuez depuis le dernier nœud, ou touche Échap pour repartir." },
];

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { itin: { noeuds: {}, couloirs: [] }, salles: [], outil: 'choisir', choisi: null, depuis: null, modifie: false };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche" data-role="outils"></div>
      <div class="barre-droite">
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer les itinéraires</button>
        <span class="etat-enregistrement" data-role="etat"></span>
      </div>
    </div>
    <p class="aide" data-role="aide"></p>
    <div class="espace-deux">
      <div class="plan" data-role="plan"></div>
      <div class="cote cote-etroit"><div class="panneau" data-role="panneau"></div></div>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const plan = creerPlan($('plan'));
  const carte = plan.carte;
  const calqueCouloirs = L.layerGroup().addTo(carte);
  const calqueNoeuds = L.layerGroup().addTo(carte);
  const outils = F.barreOutils($('outils'), OUTILS, etat.outil, choisirOutil);

  const noeuds = () => etat.itin.noeuds;
  const estSalle = (id) => etat.salles.some((s) => s.id === id);
  const longueur = (c) => G.distance([noeuds()[c[0]].x, noeuds()[c[0]].y], [noeuds()[c[1]].x, noeuds()[c[1]].y]);
  const memeCouloir = (c, a, b) => (c[0] === a && c[1] === b) || (c[0] === b && c[1] === a);

  function modifier(f) {
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
      m.bindTooltip(id, { permanent: estSalle(id), direction: 'top', offset: [0, -8], className: 'etiquette' });
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
          afficherMessage('Le nœud « ' + id + ' » est celui d\'une salle : il doit rester à la position de la salle. '
            + 'Pour le déplacer, déplacez la salle dans l\'onglet Salles.', 'avertissement');
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
          afficherMessage('Ces deux nœuds sont déjà reliés.', 'info');
        } else {
          modifier(() => etat.itin.couloirs.push([a, id]));
          const l = longueur([a, id]);
          if (l > G.COULOIR_MAX) {
            afficherMessage('Ce couloir fait ' + G.nb(l, 1) + ' m : au-delà de 8 m, le vrai robot ne peut pas le parcourir d\'un coup. '
              + 'Choisissez-le (outil Choisir) puis « Couper en deux ».', 'avertissement');
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
    }
  });

  function choisirOutil(id) {
    etat.outil = id;
    etat.depuis = null;
    outils.choisir(id);
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    $('aide').textContent = OUTILS.find((o) => o.id === id).aide;
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
    const z = $('panneau');
    z.innerHTML = '';
    const ch = etat.choisi;
    if (ch && ch.genre === 'noeud' && noeuds()[ch.id]) {
      const n = noeuds()[ch.id];
      F.titre(z, 'Nœud « ' + ch.id + ' »');
      if (estSalle(ch.id)) {
        F.paragraphe(z, 'C\'est le nœud de la salle « ' + ch.id + ' » : il suit la salle (onglet Salles).', 'panneau-note');
        F.valeur(z, 'Position', '[' + G.nb(n.x) + ' ; ' + G.nb(n.y) + '] m');
      } else {
        F.champTexte(z, 'Identifiant', ch.id, (v) => {
          v = v.trim();
          const refus = G.verifierId(v, Object.keys(noeuds()).concat(etat.salles.map((s) => s.id)).filter((x) => x !== ch.id), 'un nœud ou une salle');
          if (refus) {
            afficherMessage(refus, 'erreur');
            panneau();
            return;
          }
          modifier(() => {
            renommer(ch.id, v);
            etat.choisi = { genre: 'noeud', id: v };
          });
        });
        F.champNombre(z, 'x', n.x, { pas: PAS, unite: 'm' }, (v) => modifier(() => { n.x = v; }));
        F.champNombre(z, 'y', n.y, { pas: PAS, unite: 'm' }, (v) => modifier(() => { n.y = v; }));
      }
      const voisins = etat.itin.couloirs.filter((c) => c.indexOf(ch.id) >= 0).map((c) => (c[0] === ch.id ? c[1] : c[0]));
      F.valeur(z, 'Relié à', voisins.length ? voisins.join(', ') : 'rien (le guide ne pourra pas y passer)');
      F.bouton(z, 'Supprimer le nœud', () => modifier(() => {
        delete noeuds()[ch.id];
        etat.itin.couloirs = etat.itin.couloirs.filter((c) => c.indexOf(ch.id) < 0);
        etat.choisi = null;
      }), 'bouton bouton-danger');
      return;
    }
    if (ch && ch.genre === 'couloir' && etat.itin.couloirs[ch.indice]) {
      const c = etat.itin.couloirs[ch.indice];
      F.titre(z, 'Couloir ' + c[0] + ' – ' + c[1]);
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
    F.titre(z, 'Graphe de l\'étage');
    F.paragraphe(z, ids.length + ' nœuds, ' + couloirs.length + ' couloirs. Le guide va de nœud en nœud par le plus court chemin.');
    const trop = couloirs.filter((c) => longueur(c) > G.COULOIR_MAX);
    if (trop.length) {
      const p = F.paragraphe(z, trop.length + ' couloir(s) de plus de 8 m (en rouge) :', 'panneau-alerte');
      const ul = F.el('ul', 'liste-choix');
      trop.forEach((c) => {
        const li = F.el('li');
        F.bouton(li, c[0] + ' – ' + c[1] + ' : ' + G.nb(longueur(c), 1) + ' m', () => {
          etat.choisi = { genre: 'couloir', indice: etat.itin.couloirs.indexOf(c) };
          rafraichir();
        }, 'bouton-lien');
        ul.appendChild(li);
      });
      p.after(ul);
    }
    const isoles = etat.salles.filter((s) => s.etage === etage && !etat.itin.couloirs.some((c) => c.indexOf(s.id) >= 0));
    if (isoles.length) {
      F.paragraphe(z, 'Salles reliées à rien : ' + isoles.map((s) => s.id).join(', ') + '. Reliez leur nœud (vert) au reste.', 'panneau-alerte');
    }
    F.paragraphe(z, 'Les nœuds verts sont ceux des salles (ils se créent en enregistrant l\'onglet Salles).', 'panneau-note');
  }

  function majEtat() {
    $('etat').textContent = etat.modifie ? 'Modifications non enregistrées' : 'Tout est enregistré';
    $('etat').classList.toggle('non-enregistre', etat.modifie);
  }

  function rafraichir() {
    dessiner();
    panneau();
    majEtat();
  }

  function clavier(ev) {
    if (ev.key === 'Escape') {
      etat.depuis = null;
      etat.choisi = null;
      rafraichir();
    }
  }
  document.addEventListener('keydown', clavier);

  $('enregistrer').addEventListener('click', async () => {
    const b = $('enregistrer');
    b.disabled = true;
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/itineraires', etat.itin);
      etat.modifie = false;
      majEtat();
      afficherRapport(r.rapport, 'Itinéraires enregistrés.');
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.itin = await api.lire(urlLieu(lieu) + '/itineraires');
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      afficherErreur(e);
    }
    choisirOutil('choisir');
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    fermer: () => {
      document.removeEventListener('keydown', clavier);
      plan.detruire();
    },
  };
}
