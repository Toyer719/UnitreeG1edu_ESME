// Écran « Le lieu » (arbre › le lieu, ⚙ › Vérifier le lieu) : la fiche du lieu ouvert, ses étages et sa
// vérification. Vague 5 (section 12.2 du plan) : la liste des lieux et leur création sont sur l'écran
// d'accueil ; ici, on renomme le lieu, on ajoute un étage, et « Vérifier le lieu » contrôle tout le lieu
// comme « g1-lieu valider » (salles et nœuds, couloirs, zones, carte).

import { api, urlLieu } from '../api.js';
import { choisirEtage, contexte, rechargerLieu } from '../contexte.js';
import { blocAvance, preparerEcran, section } from '../coque/ecran.js';
import { ouvrirPanneau } from '../coque/panneau.js';
import * as F from '../formulaire.js';
import { idDepuisNom, verifierId } from '../geometrie.js';
import { afficherErreur, afficherRapport } from '../messages.js';

export function ouvrir(racine, options) {
  const ecran = preparerEcran(racine, options);
  const coque = ecran.coque;
  const lieu = contexte.lieu;
  let rapport = null;
  let verification = false;

  ecran.vue.innerHTML = '<div class="page-ecran"><div class="page-contenu fiche-lieu" data-role="fiche"></div></div>';
  const fiche = ecran.vue.querySelector('[data-role=fiche]');

  function copieFiche(info) {
    return JSON.parse(JSON.stringify({
      version: info.version, nom: info.nom, langue: info.langue,
      etages: info.etages.map((e) => ({ id: e.id, nom: e.nom, source_carte: e.source_carte })),
      accueil: info.accueil, carte_unitree: info.carte_unitree, guide: info.guide,
    }));
  }

  async function enregistrerFiche(nouvelle, reussite) {
    if (!nouvelle.guide) delete nouvelle.guide;
    try {
      const r = await api.ecrire(urlLieu(lieu), nouvelle);
      await rechargerLieu();
      afficherRapport(r.rapport, reussite);
      coque.lieuModifie('lieu');
      dessiner();
    } catch (e) {
      afficherErreur(e);
      dessiner();
    }
  }

  function dessiner() {
    const info = contexte.infoLieu;
    fiche.textContent = '';
    if (!info) return;
    const entete = F.el('div', 'fiche-entete');
    entete.appendChild(F.el('h1', 'fiche-titre', info.nom));
    entete.appendChild(F.el('span', 'puce', lieu));
    fiche.appendChild(entete);
    const c = info.compte || {};
    const chiffres = F.el('div', 'fiche-chiffres');
    [['Étages', info.etages.length], ['Salles', c.salles], ['Nœuds', c.noeuds], ['Zones', c.zones]].forEach((x) => {
      const b = F.el('div', 'fiche-chiffre');
      b.appendChild(F.el('span', 'fiche-chiffre-valeur', x[1] === null || x[1] === undefined ? '?' : String(x[1])));
      b.appendChild(F.el('span', 'fiche-chiffre-libelle', x[0]));
      chiffres.appendChild(b);
    });
    fiche.appendChild(chiffres);
    // étages
    const etages = F.el('section', 'carte-section');
    etages.appendChild(F.el('h2', '', 'Étages'));
    const liste = F.el('div', 'fiche-etages');
    info.etages.forEach((e) => {
      const ligne = F.el('button', 'fiche-etage' + (e.id === contexte.etage ? ' courant' : ''));
      ligne.type = 'button';
      ligne.setAttribute('data-etage', e.id);
      ligne.appendChild(F.el('strong', '', e.nom));
      const etatsFichiers = [e.source_carte === 'scan' ? 'carte du scan' : 'monde dessiné',
        e.a_carte ? 'carte prête' : 'pas encore de carte'];
      ligne.appendChild(F.el('span', 'fiche-etage-detail', etatsFichiers.join(' · ')));
      ligne.title = e.id === contexte.etage ? 'Étage ouvert' : 'Ouvrir cet étage';
      ligne.addEventListener('click', () => {
        if (e.id !== contexte.etage) choisirEtage(e.id);
      });
      liste.appendChild(ligne);
    });
    etages.appendChild(liste);
    fiche.appendChild(etages);
    // vérification
    const blocVerif = F.el('section', 'carte-section');
    blocVerif.setAttribute('data-role', 'verification');
    blocVerif.appendChild(F.el('h2', '', 'Vérification'));
    const resultat = F.el('div', 'rapport');
    if (verification) resultat.appendChild(F.el('p', 'panneau-note', 'Vérification…'));
    else if (rapport) afficherRapportDetaille(resultat, rapport);
    else resultat.appendChild(F.el('p', 'panneau-note', 'Cliquez sur « Vérifier le lieu » (panneau de droite).'));
    blocVerif.appendChild(resultat);
    fiche.appendChild(blocVerif);
    panneau(info);
  }

  function panneau(info) {
    const p = ouvrirPanneau(ecran.panneau, { titre: 'Le lieu' });
    const z = p.corps;
    const nom = F.champTexte(z, 'Nom', info.nom, (v) => {
      v = v.trim();
      if (!v || v === info.nom) return;
      const nouvelle = copieFiche(info);
      nouvelle.nom = v;
      enregistrerFiche(nouvelle, 'Lieu renommé.');
    });
    nom.parentNode.setAttribute('data-champ', 'nom');
    const b = F.bouton(z, 'Vérifier le lieu', verifier, 'bouton bouton-principal');
    b.setAttribute('data-role', 'verifier');
    const s = section(z, 'Ajouter un étage', 'ajouter-etage');
    const nouvel = { nom: '' };
    let champId = null;
    F.champTexte(s, 'Nom', '', () => {}, { indice: 'ex. Premier étage' }).addEventListener('input', (ev) => {
      nouvel.nom = ev.target.value;
      if (champId) champId.value = idDepuisNom(ev.target.value);
    });
    const avance = blocAvance(s, 'Avancé');
    champId = F.champTexte(avance, 'Identifiant', '', () => {}, { indice: 'ex. etage1' });
    F.bouton(s, 'Ajouter l\'étage', () => {
      const id = (champId.value || idDepuisNom(nouvel.nom)).trim();
      const nomEtage = nouvel.nom.trim() || id;
      const refus = verifierId(id, info.etages.map((x) => x.id), 'un étage');
      if (refus) {
        coque.message(refus, 'erreur');
        return;
      }
      const nouvelle = copieFiche(info);
      nouvelle.etages.push({ id: id, nom: nomEtage, source_carte: 'monde' });
      enregistrerFiche(nouvelle, 'Étage « ' + nomEtage + ' » ajouté : choisissez-le dans la barre d\'outils.');
    });
    const plus = blocAvance(z, 'Avancé');
    F.valeur(plus, 'Dossier', info.dossier);
    info.etages.forEach((e, i) => {
      F.listeDeroulante(plus, 'Carte de « ' + e.nom + ' »', e.source_carte,
        [{ id: 'monde', texte: 'le monde dessiné' }, { id: 'scan', texte: 'le scan du robot' }], (v) => {
          const nouvelle = copieFiche(info);
          nouvelle.etages[i].source_carte = v;
          enregistrerFiche(nouvelle, 'Source de la carte enregistrée.');
        });
    });
  }

  function afficherRapportDetaille(zone, r) {
    zone.textContent = '';
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

  async function verifier() {
    verification = true;
    dessiner();
    try {
      rapport = await api.lire(urlLieu(lieu) + '/verification');
      coque.message(rapport.ok ? 'Lieu vérifié : aucune erreur.' : 'Lieu vérifié : ' + rapport.erreurs.length
        + ' point(s) à corriger.', rapport.ok ? 'succes' : 'avertissement');
    } catch (e) {
      afficherErreur(e);
    }
    verification = false;
    dessiner();
  }

  rechargerLieu().then(dessiner).catch((e) => {
    afficherErreur(e);
    dessiner();
  });
  if (ecran.commande === 'verifier') verifier();
  return {
    modifie: () => false,
    commande: (nom) => { if (nom === 'verifier') verifier(); },
    fermer: () => {},
  };
}
