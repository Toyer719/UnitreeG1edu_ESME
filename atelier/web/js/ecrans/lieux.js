// Écran Lieux : liste des lieux, création d'un lieu, étages du lieu choisi, vérification.

import { api, urlLieu } from '../api.js';
import { choisirLieu, contexte, emettre, rechargerLieu } from '../contexte.js';
import * as F from '../formulaire.js';
import { idDepuisNom, verifierId } from '../geometrie.js';
import { afficherErreur, afficherMessage, afficherRapport } from '../messages.js';

export function ouvrir(racine) {
  racine.innerHTML = `
    <div class="colonnes">
      <section class="carte-section">
        <h2>Les lieux</h2>
        <p class="aide-section">Un lieu est un bâtiment (un lycée, un hall...), avec un ou plusieurs étages. Choisissez celui sur lequel travailler.</p>
        <div data-role="liste" class="liste-lieux">Chargement…</div>
      </section>
      <section class="carte-section">
        <h2>Créer un lieu</h2>
        <form data-role="creer" class="formulaire"></form>
      </section>
    </div>
    <div class="colonnes" data-role="lieu-courant"></div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');

  // ---------------------------------------------------------------- liste
  async function afficherListe() {
    const zone = $('liste');
    let lieux;
    try {
      lieux = await api.lire('/api/lieux');
    } catch (e) {
      zone.textContent = 'La liste des lieux n\'a pas pu être lue.';
      afficherErreur(e);
      return;
    }
    zone.innerHTML = '';
    if (!lieux.length) {
      zone.appendChild(F.el('p', 'vide', 'Aucun lieu pour l\'instant : créez-en un à droite.'));
      return;
    }
    lieux.forEach((l) => {
      const carte = F.el('div', 'lieu' + (l.id === contexte.lieu ? ' lieu-courant' : ''));
      const texte = F.el('div', 'lieu-texte');
      texte.appendChild(F.el('strong', '', l.nom));
      texte.appendChild(F.el('span', 'lieu-id', ' (' + l.id + ')'));
      const etages = l.etages.map((e) => e.nom).join(', ');
      texte.appendChild(F.el('div', 'lieu-etages', l.erreur ? 'Fichier invalide : ' + l.erreur : (l.etages.length + ' étage' + (l.etages.length > 1 ? 's' : '') + ' : ' + etages)));
      carte.appendChild(texte);
      if (l.id === contexte.lieu) carte.appendChild(F.el('span', 'pastille', 'Ouvert'));
      else F.bouton(carte, 'Ouvrir ce lieu', async () => {
        try {
          await choisirLieu(l.id);
          afficherMessage('Lieu « ' + l.nom + ' » ouvert.', 'succes');
        } catch (e) {
          afficherErreur(e);
        }
      }, 'bouton bouton-principal');
      zone.appendChild(carte);
    });
  }

  // ---------------------------------------------------------------- création
  function formulaireCreation() {
    const f = $('creer');
    const donnees = { nom: '', id: '', largeur: 20, profondeur: 15, idManuel: false };
    let champId;
    F.champTexte(f, 'Nom du lieu', '', (v) => {
      donnees.nom = v;
      if (!donnees.idManuel) {
        donnees.id = idDepuisNom(v);
        champId.value = donnees.id;
      }
    }, { indice: 'ex. Lycée Victor Hugo' }).addEventListener('input', (e) => {
      if (!donnees.idManuel) {
        donnees.id = idDepuisNom(e.target.value);
        champId.value = donnees.id;
      }
    });
    champId = F.champTexte(f, 'Identifiant (nom du dossier)', '', (v) => {
      donnees.id = v.trim();
      donnees.idManuel = true;
    }, { indice: 'ex. lycee_victor_hugo' });
    F.champNombre(f, 'Largeur (est-ouest)', 20, { pas: 1, min: 3, unite: 'm' }, (v) => { donnees.largeur = v; });
    F.champNombre(f, 'Profondeur (sud-nord)', 15, { pas: 1, min: 3, unite: 'm' }, (v) => { donnees.profondeur = v; });
    F.paragraphe(f, 'Le lieu commence avec un étage « Rez-de-chaussée », un accueil en (1 ; 1) et quatre murs autour.', 'panneau-note');
    const b = F.bouton(f, 'Créer le lieu', async () => {
      donnees.nom = f.querySelector('input').value.trim();
      donnees.id = champId.value.trim();
      if (!donnees.nom) {
        afficherMessage('Donnez un nom au lieu.', 'erreur');
        return;
      }
      const refus = verifierId(donnees.id);
      if (refus) {
        afficherMessage(refus, 'erreur');
        return;
      }
      b.disabled = true;
      try {
        await api.envoyer('/api/lieux', { id: donnees.id, nom: donnees.nom, largeur: donnees.largeur, profondeur: donnees.profondeur });
        await choisirLieu(donnees.id);
        afficherMessage('Lieu « ' + donnees.nom + ' » créé. Dessinez maintenant son monde : onglet Monde.', 'succes');
        emettre('aller-ecran', 'monde');
      } catch (e) {
        afficherErreur(e);
      } finally {
        b.disabled = false;
      }
    }, 'bouton bouton-principal');
    f.addEventListener('submit', (e) => e.preventDefault());
  }

  // ---------------------------------------------------------------- lieu courant
  function afficherLieuCourant() {
    const zone = $('lieu-courant');
    zone.innerHTML = '';
    const info = contexte.infoLieu;
    if (!info) return;
    const s1 = F.el('section', 'carte-section');
    s1.appendChild(F.el('h2', '', 'Étages de « ' + info.nom + ' »'));
    const table = F.el('table', 'tableau');
    const entete = F.el('tr');
    ['Étage', 'Id', 'Carte faite depuis', 'Monde', 'Carte', 'Monde Gazebo'].forEach((t) => entete.appendChild(F.el('th', '', t)));
    table.appendChild(entete);
    const fiche = JSON.parse(JSON.stringify({
      version: info.version, nom: info.nom, langue: info.langue, etages: info.etages.map((e) => ({ id: e.id, nom: e.nom, source_carte: e.source_carte })),
      accueil: info.accueil, carte_unitree: info.carte_unitree,
    }));
    info.etages.forEach((e, i) => {
      const tr = F.el('tr');
      tr.appendChild(F.el('td', '', e.nom));
      tr.appendChild(F.el('td', 'code', e.id));
      const td = F.el('td');
      const s = F.el('select');
      [['monde', 'le monde inventé'], ['scan', 'le scan du robot']].forEach((c) => {
        const o = F.el('option', '', c[1]);
        o.value = c[0];
        s.appendChild(o);
      });
      s.value = e.source_carte;
      s.addEventListener('change', () => { fiche.etages[i].source_carte = s.value; enregistrerFiche(fiche, 'Source de la carte enregistrée.'); });
      td.appendChild(s);
      tr.appendChild(td);
      [e.a_monde, e.a_carte, e.a_sdf].forEach((ok) => tr.appendChild(F.el('td', ok ? 'oui' : 'non', ok ? 'oui' : 'pas encore')));
      table.appendChild(tr);
    });
    s1.appendChild(table);
    const ajout = F.el('div', 'formulaire formulaire-ligne');
    const nouvel = { nom: '', id: '' };
    let champId;
    F.champTexte(ajout, 'Nouvel étage', '', () => {}, { indice: 'ex. Premier étage' }).addEventListener('input', (ev) => {
      nouvel.nom = ev.target.value;
      champId.value = idDepuisNom(ev.target.value);
    });
    champId = F.champTexte(ajout, 'Id', '', () => {}, { indice: 'ex. etage1' });
    F.bouton(ajout, 'Ajouter l\'étage', () => {
      const id = champId.value.trim();
      const nom = nouvel.nom.trim() || id;
      const refus = verifierId(id, fiche.etages.map((x) => x.id), 'un étage');
      if (refus) {
        afficherMessage(refus, 'erreur');
        return;
      }
      fiche.etages.push({ id: id, nom: nom, source_carte: 'monde' });
      enregistrerFiche(fiche, 'Étage « ' + nom + ' » ajouté. Choisissez-le en haut, puis dessinez son monde.');
    });
    s1.appendChild(ajout);
    zone.appendChild(s1);

    const s2 = F.el('section', 'carte-section');
    s2.appendChild(F.el('h2', '', 'Vérifier le lieu'));
    s2.appendChild(F.el('p', 'aide-section', 'Contrôle tout le lieu, comme « g1-lieu valider » : salles et nœuds, couloirs, zones, carte.'));
    const resultat = F.el('div', 'rapport');
    F.bouton(s2, 'Vérifier le lieu', async () => {
      resultat.textContent = 'Vérification…';
      try {
        afficherRapportDetaille(resultat, await api.lire(urlLieu(contexte.lieu) + '/verification'));
      } catch (e) {
        resultat.textContent = '';
        afficherErreur(e);
      }
    }, 'bouton bouton-principal');
    s2.appendChild(resultat);
    const c = info.compte || {};
    s2.appendChild(F.el('p', 'panneau-note', 'Contenu : ' + (c.salles === null ? '?' : c.salles) + ' salles, '
      + (c.noeuds === null ? '?' : c.noeuds) + ' nœuds, ' + (c.zones === null ? '?' : c.zones) + ' zones. Dossier : ' + info.dossier));
    zone.appendChild(s2);
  }

  async function enregistrerFiche(fiche, reussite) {
    try {
      const r = await api.ecrire(urlLieu(contexte.lieu), fiche);
      await rechargerLieu();
      emettre('lieu');
      afficherRapport(r.rapport, reussite);
    } catch (e) {
      afficherErreur(e);
      afficherLieuCourant();
    }
  }

  function afficherRapportDetaille(zone, r) {
    zone.innerHTML = '';
    if (r.ok && !r.avertissements.length) {
      zone.appendChild(F.el('p', 'rapport-ok', 'Aucun problème : le lieu est prêt.'));
      return;
    }
    if (r.erreurs.length) {
      zone.appendChild(F.el('p', 'rapport-titre-erreur', 'À corriger (' + r.erreurs.length + ') :'));
      const ul = F.el('ul', 'rapport-erreurs');
      r.erreurs.forEach((m) => ul.appendChild(F.el('li', '', m)));
      zone.appendChild(ul);
    } else {
      zone.appendChild(F.el('p', 'rapport-ok', 'Aucune erreur.'));
    }
    if (r.avertissements.length) {
      zone.appendChild(F.el('p', 'rapport-titre-avertissement', 'À regarder (' + r.avertissements.length + ') :'));
      const ul = F.el('ul', 'rapport-avertissements');
      r.avertissements.forEach((m) => ul.appendChild(F.el('li', '', m)));
      zone.appendChild(ul);
    }
  }

  afficherListe();
  formulaireCreation();
  afficherLieuCourant();

  return {
    modifie: () => false,
    fermer: () => {},
  };
}
