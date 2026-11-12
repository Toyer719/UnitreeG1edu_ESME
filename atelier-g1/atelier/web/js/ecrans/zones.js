// Écran Zones (Placer › Zone interdite, Placer › Zone lente) : polygones interdits (rouge : le robot n'y
// va jamais) et lents (orange : le robot y roule doucement), sur le plan 2D. Clic pour chaque coin, puis
// « Terminer la zone » (ou Entrée, ou clic sur le premier coin). ✓ Enregistrer écrit zones.yaml puis refait
// le masque des zones interdites que le robot respecte (POST …/monde/generer) ; Annuler et Rétablir par
// historique.js ; la vue 3D de la coque suit les changements.

import { api, urlEtage, urlLieu } from '../api.js';
import { contexte } from '../contexte.js';
import { panneauEdition, preparerEcran } from '../coque/ecran.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { Historique } from '../historique.js';
import { afficherErreur, afficherRapport } from '../messages.js';
import { creerPlan, ll, lls, suivrePointeur } from '../plan.js';

const L = window.L;
const PAS = 0.25;

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez dans une zone pour la modifier ; glissez ses coins pour changer sa forme." },
  { id: 'interdite', texte: 'Zone interdite', aide: "Cliquez chaque coin de la zone où le robot ne va jamais (escalier, local technique…), puis « Terminer la zone »." },
  { id: 'lente', texte: 'Zone lente', aide: "Cliquez chaque coin de la zone où le robot ralentit (hall, sortie de classe…), puis « Terminer la zone »." },
];

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const carte3d = ecran.carte3d;
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { zones: { interdites: [], lentes: [] }, outil: 'choisir', choisi: null, trace: null, vitesse: 0.25,
    modifie: false, charge: false, outilDemande: null };
  const hist = new Historique();

  ecran.vue.innerHTML = '<div class="plan" data-role="plan"></div>';
  const plan = creerPlan(ecran.vue.querySelector('[data-role=plan]'));
  const carte = plan.carte;
  const calque = L.layerGroup().addTo(carte);
  const calqueTrace = L.layerGroup().addTo(carte);
  let zoneOutil = null;

  const liste = (genre) => (genre === 'interdite' ? etat.zones.interdites : etat.zones.lentes);
  const zoneChoisie = () => (etat.choisi ? liste(etat.choisi.genre)[etat.choisi.indice] || null : null);

  function modifier(f) {
    hist.noter(etat.zones);
    f();
    etat.modifie = true;
    rafraichir();
  }

  function dessiner() {
    calque.clearLayers();
    ['interdite', 'lente'].forEach((genre) => {
      liste(genre).forEach((z, i) => {
        if (z.etage !== etage) return;
        const choisie = etat.choisi && etat.choisi.genre === genre && etat.choisi.indice === i;
        const poly = L.polygon(lls(z.polygone), { className: 'zone zone-' + genre + (choisie ? ' choisi' : '') });
        const titre = (genre === 'interdite' ? 'Interdite' : 'Lente, ' + G.nb(z.vitesse_max, 2) + ' m/s') + (z.nom ? ' : ' + z.nom : '');
        poly.bindTooltip(titre, { sticky: true });
        poly.on('click', (e) => {
          if (etat.outil !== 'choisir') return;
          L.DomEvent.stopPropagation(e);
          etat.choisi = { genre: genre, indice: i };
          rafraichir();
        });
        poly.addTo(calque);
        if (choisie) {
          z.polygone.forEach((p, k) => {
            const sommet = L.marker(ll(p[0], p[1]), {
              icon: L.divIcon({ className: 'sommet', iconSize: [14, 14], iconAnchor: [7, 7] }), draggable: true, keyboard: false,
            });
            sommet.on('drag', () => {
              const q = sommet.getLatLng();
              const pts = z.polygone.slice();
              pts[k] = [q.lng, q.lat];
              poly.setLatLngs(lls(pts));
            });
            sommet.on('dragend', () => {
              const q = sommet.getLatLng();
              modifier(() => { z.polygone[k] = G.accrocherPoint([q.lng, q.lat], PAS); });
            });
            sommet.addTo(calque);
          });
        }
      });
    });
  }

  function dessinerTrace(p) {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (p && etat.outil !== 'choisir') L.circleMarker(ll(p[0], p[1]), { radius: 4, className: 'curseur-grille', interactive: false }).addTo(calqueTrace);
    if (!t) return;
    const pts = t.points.concat(p ? [p] : []);
    if (pts.length > 1) L.polygon(lls(pts), { className: 'zone zone-' + t.genre + ' trace', interactive: false }).addTo(calqueTrace);
    t.points.forEach((q) => L.circleMarker(ll(q[0], q[1]), { radius: 5, className: 'point-trace', interactive: false }).addTo(calqueTrace));
  }

  function terminerZone() {
    const t = etat.trace;
    if (!t) return;
    if (t.points.length < 3) {
      coque.message('Une zone a besoin d\'au moins trois coins : cliquez encore.', 'avertissement');
      return;
    }
    const z = { etage: etage, polygone: t.points, nom: '' };
    if (t.genre === 'lente') z.vitesse_max = etat.vitesse;
    modifier(() => {
      liste(t.genre).push(z);
      etat.choisi = { genre: t.genre, indice: liste(t.genre).length - 1 };
    });
    etat.trace = null;
    dessinerTrace(null);
    choisirOutil('choisir');
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: () => etat.outil !== 'choisir',
    survol: (p) => { if (etat.outil !== 'choisir') dessinerTrace(G.accrocherPoint(p, PAS)); },
    deplacer: (p) => dessinerTrace(G.accrocherPoint(p, PAS)),
    fin: (p) => {
      const q = G.accrocherPoint(p, PAS);
      if (!etat.trace) etat.trace = { genre: etat.outil, points: [] };
      const pts = etat.trace.points;
      if (pts.length >= 3 && G.distance(pts[0], q) < 1e-6) {
        terminerZone();         // clic sur le premier coin : la zone se ferme
        return;
      }
      if (pts.length && G.distance(pts[pts.length - 1], q) < 1e-6) return;
      pts.push(q);
      dessinerTrace(q);
      majOptions();
    },
    annuler: () => dessinerTrace(null),
  });

  carte.on('click', () => {
    if (etat.outil === 'choisir' && etat.choisi) {
      etat.choisi = null;
      rafraichir();
    }
  });

  function choisirOutil(id) {
    if (!OUTILS.some((o) => o.id === id)) id = 'choisir';
    etat.outil = id;
    etat.trace = null;
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    coque.activer(id === 'choisir' ? null : id);
    coque.aide(OUTILS.find((o) => o.id === id).aide);
    dessinerTrace(null);
    rafraichir();
  }

  // Réglages de l'outil en cours, en tête du panneau
  function majOptions() {
    if (!zoneOutil) return;
    const z = zoneOutil;
    z.textContent = '';
    z.hidden = etat.outil === 'choisir';
    if (etat.outil === 'choisir') return;
    z.appendChild(F.el('h3', 'panneau-titre', etat.outil === 'interdite' ? 'Nouvelle zone interdite' : 'Nouvelle zone lente'));
    if (etat.outil === 'lente') {
      F.champNombre(z, 'Vitesse maximale', etat.vitesse, { pas: 0.05, min: 0.05, max: 1, unite: 'm/s' }, (v) => { etat.vitesse = v; });
    }
    const n = etat.trace ? etat.trace.points.length : 0;
    const ligne = F.el('div', 'formulaire-ligne');
    F.bouton(ligne, 'Terminer la zone (' + n + ' coin' + (n > 1 ? 's' : '') + ')', terminerZone, 'bouton bouton-principal').disabled = n < 3;
    F.bouton(ligne, 'Abandonner', () => { etat.trace = null; dessinerTrace(null); majOptions(); }).disabled = n === 0;
    z.appendChild(ligne);
  }

  function panneau() {
    const z = zoneChoisie();
    const genre = z ? etat.choisi.genre : null;
    const titre = z ? (genre === 'interdite' ? 'Zone interdite' : 'Zone lente') : 'Zones';
    const p = panneauEdition(ecran.panneau, titre, null,
      { modifie: () => etat.modifie, enregistrer: enregistrer, annuler: abandonner }).corps;
    zoneOutil = F.el('div', 'section-panneau section-outil');
    zoneOutil.setAttribute('data-section', 'outil');
    p.appendChild(zoneOutil);
    majOptions();
    if (z) {
      F.champTexte(p, 'Nom', z.nom || '', (v) => modifier(() => { z.nom = v.trim(); }), { indice: 'ex. Escalier' });
      if (genre === 'lente') {
        F.champNombre(p, 'Vitesse maximale', z.vitesse_max, { pas: 0.05, min: 0.05, max: 1, unite: 'm/s' }, (v) => modifier(() => { z.vitesse_max = v; }));
      }
      F.valeur(p, 'Coins', String(z.polygone.length));
      const actions = F.el('div', 'formulaire-ligne');
      F.bouton(actions, 'Supprimer', () => modifier(() => {
        liste(genre).splice(etat.choisi.indice, 1);
        etat.choisi = null;
      }), 'bouton bouton-danger');
      F.bouton(actions, 'Fermer', () => { etat.choisi = null; rafraichir(); }, 'bouton bouton-discret');
      p.appendChild(actions);
      return;
    }
    const nI = etat.zones.interdites.filter((x) => x.etage === etage).length;
    const nL = etat.zones.lentes.filter((x) => x.etage === etage).length;
    F.paragraphe(p, nI + ' zone(s) interdite(s) en rouge, ' + nL + ' zone(s) lente(s) en orange.');
    F.paragraphe(p, 'Cliquez dans une zone pour la modifier. À l\'enregistrement, le masque que le robot respecte '
      + 'se refait seul.', 'panneau-note');
  }

  function afficher3D() {
    if (carte3d) carte3d.afficherZones(etat.zones);
  }

  function rafraichir() {
    dessiner();
    afficher3D();
    panneau();
  }

  function clavier(ev) {
    const c = ev.target;
    if (c && (c.tagName === 'INPUT' || c.tagName === 'TEXTAREA' || c.tagName === 'SELECT')) return;
    if (ev.key === 'Enter') terminerZone();
    if (ev.key === 'Escape') { etat.trace = null; dessinerTrace(null); choisirOutil('choisir'); }
  }
  document.addEventListener('keydown', clavier);

  async function enregistrer() {
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/zones', etat.zones);
      etat.modifie = false;
      afficherRapport(r.rapport, 'Zones enregistrées. Le masque du robot se met à jour…');
      panneau();
      coque.lieuModifie('zones');
      try {
        await api.envoyer(urlEtage(lieu, etage) + '/monde/generer');
        coque.message('Zones enregistrées, masque du robot à jour.', 'succes');
      } catch (e) {
        coque.message('Zones enregistrées, mais le masque du robot n\'a pas pu être refait : ' + e.message,
          'avertissement', e.erreurs, e.sortie);
      }
      return true;
    } catch (e) {
      afficherErreur(e);
      return false;
    }
  }

  async function abandonner() {
    if (!etat.modifie) return;
    if (!(await coque.confirmer('Abandonner les changements des zones et revenir à la version enregistrée ?',
      { titre: 'Annuler les modifications', ok: 'Abandonner', annuler: 'Garder', danger: true }))) return;
    await charger();
  }

  function deplacerHistorique(sens) {
    const autre = sens < 0 ? hist.annuler(etat.zones) : hist.refaire(etat.zones);
    if (!autre) return;
    etat.zones = autre;
    etat.modifie = true;
    if (etat.choisi && !zoneChoisie()) etat.choisi = null;
    rafraichir();
  }

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.zones = await api.lire(urlLieu(lieu) + '/zones');
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
    choisirOutil(nom);
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
      if (genre !== 'zone') return;
      const morceaux = String(id).split(':');
      const g = morceaux[0];
      const i = Number(morceaux[1]);
      if ((g === 'interdite' || g === 'lente') && liste(g)[i]) {
        etat.choisi = { genre: g, indice: i };
        const z = liste(g)[i];
        const xs = z.polygone.map((q) => q[0]);
        const ys = z.polygone.map((q) => q[1]);
        plan.cadrer(Math.min.apply(null, xs) - 2, Math.min.apply(null, ys) - 2, Math.max.apply(null, xs) + 2, Math.max.apply(null, ys) + 2);
        rafraichir();
      }
    },
    vue: () => {
      plan.carte.invalidateSize();
      if (plan.cadrageEnAttente) plan.recadrer();
    },
    recadrer: () => plan.recadrer(),
    fermer: () => {
      document.removeEventListener('keydown', clavier);
      arreterPointeur();
      plan.detruire();
    },
  };
}
