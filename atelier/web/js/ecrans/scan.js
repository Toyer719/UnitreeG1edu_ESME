// Écran Scan : démarrer et terminer le scan 3D d'un vrai bâtiment avec la cartographie
// intégrée du robot (commande g1-slam). Sans robot, « faux service » essaie tout sur le PC.

import { api } from '../api.js';
import { contexte } from '../contexte.js';
import * as F from '../formulaire.js';
import { afficherErreur, afficherMessage } from '../messages.js';

export function ouvrir(racine) {
  const etage = contexte.etage || 'rdc';
  const lieu = contexte.lieu || 'LIEU';
  racine.innerHTML = `
    <div class="colonnes">
      <section class="carte-section">
        <h2>Scanner un bâtiment</h2>
        <p class="aide-section">Avec le vrai robot : posez-le à l'accueil, cliquez sur « Démarrer le scan », promenez-le
          lentement dans tous les couloirs (télécommande), revenez au point de départ, puis « Terminer le scan ».
          Le robot enregistre alors la carte 3D sous le nom choisi.</p>
        <div class="formulaire" data-role="formulaire"></div>
        <div class="boutons-scan">
          <button type="button" class="bouton bouton-principal bouton-grand" data-role="debut">Démarrer le scan</button>
          <button type="button" class="bouton bouton-grand" data-role="fin">Terminer le scan</button>
        </div>
        <p class="etat-action" data-role="etat"></p>
        <pre class="sortie-commande" data-role="sortie" hidden></pre>
        <div class="faux-service" data-role="faux-service"></div>
      </section>
      <section class="carte-section">
        <h2>Ensuite</h2>
        <p class="aide-section">Pour remplacer la carte de l'étage par celle du scan, dans un terminal :</p>
        <pre class="sortie-commande" data-role="suite"></pre>
        <p class="aide-section">Puis, dans l'onglet Lieux, choisissez « le scan du robot » comme source de la carte de l'étage.
          Les salles, les itinéraires et les zones restent les mêmes.</p>
      </section>
    </div>`;
  const $ = (r) => racine.querySelector('[data-role="' + r + '"]');
  const reglages = { faux: true, nom: etage };
  F.caseACocher($('formulaire'), 'Faux service (essai sans robot, sur cet ordinateur)', reglages.faux, (v) => { reglages.faux = v; });
  F.champTexte($('formulaire'), 'Nom de la carte sur le robot', reglages.nom, (v) => { reglages.nom = v.trim(); }, { indice: 'ex. rdc' });
  $('suite').textContent = 'g1-carte-3d --lieu ' + lieu + ' --etage ' + etage + ' --enregistrement DOSSIER\n'
    + 'g1-carte-2d --lieu ' + lieu + ' --etage ' + etage;

  // État du faux service lancé par l'Atelier (il tourne tant qu'on ne l'arrête pas)
  async function majFauxService() {
    const z = $('faux-service');
    z.innerHTML = '';
    let e;
    try {
      e = await api.lire('/api/scan/etat');
    } catch (err) {
      return;
    }
    if (!e.g1_slam) {
      $('etat').textContent = 'La commande g1-slam n\'est pas encore installée sur cet ordinateur : les boutons ne marcheront pas encore.';
    }
    if (e.faux_service && e.faux_service.en_cours) {
      z.appendChild(F.el('p', 'panneau-note', 'Le faux service du scan tourne sur cet ordinateur (lancé par l\'Atelier).'));
      F.bouton(z, 'Arrêter le faux service', async () => {
        try {
          await api.envoyer('/api/scan/faux-service/arreter');
          afficherMessage('Faux service arrêté.', 'info');
        } catch (err) {
          afficherErreur(err);
        }
        majFauxService();
      });
    }
  }
  majFauxService();

  async function lancer(bouton, url, corps, reussite) {
    if (!reglages.faux && !window.confirm('Le faux service est décoché : la commande va parler au vrai robot '
      + '(câble Ethernet, interface eno2). Le robot est-il branché et prêt ?')) return;
    bouton.disabled = true;
    $('etat').textContent = 'Commande en cours…';
    try {
      const r = await api.envoyer(url, corps);
      $('etat').textContent = reussite;
      $('sortie').hidden = false;
      $('sortie').textContent = r.commande + '\n' + r.sortie;
      afficherMessage(reussite, 'succes');
      if (r.faux_service_lance) afficherMessage('Le faux service du scan a été lancé sur cet ordinateur.', 'info');
    } catch (e) {
      $('etat').textContent = 'La commande a échoué.';
      if (e.sortie) {
        $('sortie').hidden = false;
        $('sortie').textContent = e.sortie;
      }
      afficherErreur(e);
    } finally {
      bouton.disabled = false;
      majFauxService();
    }
  }

  $('debut').addEventListener('click', () => lancer($('debut'), '/api/scan/debut',
    { faux: reglages.faux, lieu: contexte.lieu, etage: contexte.etage },
    'Scan démarré : promenez le robot dans tout l\'étage, puis « Terminer le scan ».'));
  $('fin').addEventListener('click', () => {
    if (!reglages.nom) {
      afficherMessage('Donnez un nom à la carte (ex. rdc).', 'erreur');
      return;
    }
    lancer($('fin'), '/api/scan/fin', { nom: reglages.nom, faux: reglages.faux, lieu: contexte.lieu },
      'Scan terminé : carte « ' + reglages.nom + ' » enregistrée sur le robot'
      + (contexte.lieu ? ', et notée dans le lieu (carte_unitree).' : '.'));
  });

  return { modifie: () => false, fermer: () => {} };
}
