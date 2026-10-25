// Écran Salles : placer les destinations du guide sur la carte. Clic pour placer, glisser pour
// orienter (le robot s'arrête tourné vers la salle). Panneau : nom, alias, phrase d'arrivée.
// Enregistrer écrit salles.yaml, et met à jour les nœuds de même id dans itineraires.yaml
// (et l'accueil de lieu.yaml pour la salle « accueil »).

import { api, urlLieu } from '../api.js';
import { contexte, rechargerLieu } from '../contexte.js';
import * as F from '../formulaire.js';
import * as G from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';
import { creerPlan, iconeOrientee, ll, suivrePointeur } from '../plan.js';

const L = window.L;
const PAS = 0.05;      // m : les salles s'accrochent aux 5 cm
const PAS_ANGLE = 15;  // degrés : l'orientation glissée s'accroche par pas de 15° (valeur exacte dans le panneau)

const OUTILS = [
  { id: 'choisir', texte: 'Choisir', aide: "Cliquez sur une salle pour la modifier. Faites glisser son rond pour la déplacer, et la petite poignée pour l'orienter." },
  { id: 'ajouter', texte: 'Ajouter une salle', aide: "Cliquez devant la porte de la salle, là où le robot doit s'arrêter, et glissez vers la salle pour l'orienter." },
];

export function ouvrir(racine) {
  const lieu = contexte.lieu;
  const etage = contexte.etage;
  const etat = { salles: [], choisi: null, outil: 'choisir', modifie: false, trace: null, idsAuto: new Set() };

  racine.innerHTML = `
    <div class="barre">
      <div class="barre-gauche" data-role="outils"></div>
      <div class="barre-droite">
        <button type="button" class="bouton bouton-principal" data-role="enregistrer">Enregistrer les salles</button>
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
  const calque = L.layerGroup().addTo(carte);
  const calqueTrace = L.layerGroup().addTo(carte);
  const outils = F.barreOutils($('outils'), OUTILS, etat.outil, choisirOutil);

  function sallesEtage() {
    return etat.salles.filter((s) => s.etage === etage);
  }

  function salle(id) {
    return etat.salles.find((s) => s.id === id) || null;
  }

  function modifier(f) {
    f();
    etat.modifie = true;
    rafraichir();
  }

  function dessiner() {
    calque.clearLayers();
    sallesEtage().forEach((s) => {
      const choisie = s.id === etat.choisi;
      const m = L.marker(ll(s.pose.x, s.pose.y), {
        icon: iconeOrientee('salle' + (s.id === 'accueil' ? ' accueil' : '') + (choisie ? ' choisi' : ''), s.pose.theta),
        draggable: etat.outil === 'choisir', keyboard: false, title: s.nom,
      });
      m.bindTooltip(s.nom, { permanent: true, direction: 'right', offset: [12, 0], className: 'etiquette' });
      m.on('click', () => { etat.choisi = s.id; rafraichir(); });
      m.on('dragstart', () => { etat.choisi = s.id; });
      m.on('dragend', () => {
        const p = m.getLatLng();
        modifier(() => {
          s.pose.x = G.accrocher(p.lng, PAS);
          s.pose.y = G.accrocher(p.lat, PAS);
        });
      });
      m.addTo(calque);
      if (choisie && etat.outil === 'choisir') {
        // poignée d'orientation, à 1 m devant la salle
        const poignee = L.marker(ll(s.pose.x + Math.cos(s.pose.theta), s.pose.y + Math.sin(s.pose.theta)), {
          icon: L.divIcon({ className: 'poignee', iconSize: [18, 18], iconAnchor: [9, 9] }),
          draggable: true, keyboard: false, title: 'Glisser pour orienter',
        });
        const ligne = L.polyline([ll(s.pose.x, s.pose.y), poignee.getLatLng()], { className: 'ligne-poignee', interactive: false });
        poignee.on('drag', () => {
          const q = poignee.getLatLng();
          ligne.setLatLngs([ll(s.pose.x, s.pose.y), q]);
          m.setIcon(iconeOrientee('salle choisi', G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE)));
        });
        poignee.on('dragend', () => {
          const q = poignee.getLatLng();
          modifier(() => { s.pose.theta = G.accrocherAngle(Math.atan2(q.lat - s.pose.y, q.lng - s.pose.x), PAS_ANGLE); });
        });
        ligne.addTo(calque);
        poignee.addTo(calque);
      }
    });
  }

  function dessinerTrace() {
    calqueTrace.clearLayers();
    const t = etat.trace;
    if (!t) return;
    L.marker(ll(t.x, t.y), { icon: iconeOrientee('salle trace', t.theta), interactive: false }).addTo(calqueTrace);
  }

  const arreterPointeur = suivrePointeur(plan, {
    debut: (p) => {
      if (etat.outil !== 'ajouter') return false;
      const q = G.accrocherPoint(p, PAS);
      etat.trace = { x: q[0], y: q[1], theta: 0 };
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
      const id = G.idLibre('salle', etat.salles.map((s) => s.id));
      etat.idsAuto.add(id);
      modifier(() => {
        etat.salles.push({ id: id, nom: 'Nouvelle salle', alias: [], etage: etage, pose: { x: t.x, y: t.y, theta: t.theta }, phrase_arrivee: '' });
        etat.choisi = id;
      });
      choisirOutil('choisir');
      const champ = $('panneau').querySelector('[data-champ="nom"] input');
      if (champ) {
        champ.focus();
        champ.select();
      }
    },
    annuler: () => { etat.trace = null; dessinerTrace(); },
  });

  function choisirOutil(id) {
    etat.outil = id;
    outils.choisir(id);
    plan.cadre.classList.toggle('dessin', id !== 'choisir');
    if (id === 'choisir') carte.dragging.enable();
    else carte.dragging.disable();
    $('aide').textContent = OUTILS.find((o) => o.id === id).aide;
    dessiner();
  }

  function panneau() {
    const z = $('panneau');
    z.innerHTML = '';
    const s = salle(etat.choisi);
    if (s) {
      F.titre(z, 'Salle « ' + s.nom + ' »');
      const champNom = F.champTexte(z, 'Nom affiché et annoncé', s.nom, (v) => modifier(() => {
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
      const champId = F.champTexte(z, 'Identifiant', s.id, (v) => {
        v = v.trim();
        const refus = G.verifierId(v, etat.salles.filter((x) => x !== s).map((x) => x.id), 'une salle');
        if (refus) {
          afficherMessage(refus, 'erreur');
          panneau();
          return;
        }
        modifier(() => {
          etat.idsAuto.delete(s.id);
          s.id = v;
          etat.choisi = v;
        });
      }, { lectureSeule: s.id === 'accueil' });
      if (s.id === 'accueil') champId.title = 'L\'accueil garde toujours l\'identifiant « accueil ».';
      F.champTexte(z, 'Autres noms (séparés par des virgules)', s.alias.join(', '), (v) => modifier(() => {
        s.alias = v.split(',').map((a) => a.trim()).filter((a) => a);
      }), { indice: 'ex. labo de physique, b204' });
      F.champTexte(z, 'Phrase à l\'arrivée', s.phrase_arrivee, (v) => modifier(() => { s.phrase_arrivee = v.trim(); }),
        { lignes: 3, indice: 'Vide : le robot annonce le nom de la salle.' });
      F.champNombre(z, 'x', s.pose.x, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.x = v; }));
      F.champNombre(z, 'y', s.pose.y, { pas: PAS, unite: 'm' }, (v) => modifier(() => { s.pose.y = v; }));
      F.champNombre(z, 'Orientation', G.degres(s.pose.theta), { pas: 15, unite: '°', decimales: 1 },
        (v) => modifier(() => { s.pose.theta = G.arrondir(G.normaliserAngle(G.radians(v)), 4); }));
      F.paragraphe(z, '0° : vers l\'est (la droite de la carte), 90° : vers le nord (le haut). En glissant la poignée, '
        + 'l\'orientation va par pas de 15°.', 'panneau-note');
      if (s.id === 'accueil') {
        F.paragraphe(z, 'L\'accueil ne peut pas être supprimé : c\'est là que le robot attend les visiteurs.', 'panneau-note');
      } else {
        F.bouton(z, 'Supprimer la salle', () => modifier(() => {
          etat.salles = etat.salles.filter((x) => x !== s);
          etat.choisi = null;
        }), 'bouton bouton-danger');
      }
      F.bouton(z, 'Retour à la liste', () => { etat.choisi = null; rafraichir(); });
      return;
    }
    F.titre(z, 'Salles de l\'étage (' + sallesEtage().length + ')');
    if (!sallesEtage().length) F.paragraphe(z, 'Aucune salle : choisissez « Ajouter une salle » en haut.');
    const ul = F.el('ul', 'liste-choix');
    sallesEtage().forEach((x) => {
      const li = F.el('li');
      F.bouton(li, x.nom + ' (' + x.id + ')', () => {
        etat.choisi = x.id;
        carte.panTo(ll(x.pose.x, x.pose.y));
        rafraichir();
      }, 'bouton-lien');
      ul.appendChild(li);
    });
    z.appendChild(ul);
    F.paragraphe(z, 'En enregistrant, chaque salle reçoit aussi un nœud de même nom dans les itinéraires. Reliez-le ensuite au reste dans l\'onglet Itinéraires.', 'panneau-note');
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

  $('enregistrer').addEventListener('click', async () => {
    const b = $('enregistrer');
    b.disabled = true;
    try {
      const r = await api.ecrire(urlLieu(lieu) + '/salles?synchroniser=true', etat.salles);
      etat.modifie = false;
      majEtat();
      const autres = r.enregistre.filter((f) => f !== 'salles.yaml');
      afficherRapport(r.rapport, 'Salles enregistrées' + (autres.length ? ' (mis à jour aussi : ' + autres.join(', ') + ')' : '') + '.');
      rechargerLieu().catch(() => {});
    } catch (e) {
      afficherErreur(e);
    } finally {
      b.disabled = false;
    }
  });

  async function charger() {
    try {
      await plan.afficherFond(lieu, etage);
      etat.salles = await api.lire(urlLieu(lieu) + '/salles');
    } catch (e) {
      afficherErreur(e);
    }
    choisirOutil('choisir');
    rafraichir();
  }
  racine.classList.add('chargement');     // rien n'est modifiable avant la fin du chargement
  charger().finally(() => racine.classList.remove('chargement'));

  return {
    modifie: () => etat.modifie,
    fermer: () => {
      arreterPointeur();
      plan.detruire();
    },
  };
}
