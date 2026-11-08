// La borne visiteur (vague 6, section 13.5 du plan) : page /borne, pour une tablette ou un téléphone du même
// réseau. Module de l'agent Borne et orchestrateur ; squelette livré par l'agent Contrats.
//
// Contrat : demarrerBorne(racine) lit l'état (WebSocket /ws/borne, sinon GET /api/borne/etat toutes les 0,5 s ;
// schéma etat_borne) et montre l'écran demandé (data-ecran sur [data-role=borne] : hors_service, salles,
// suivez_moi, arrivee, retour, occupe, pause) ; une salle touchée ([data-salle=<id>]) demande confirmation dans la
// page ([data-role=confirmer-salle]), puis POST /api/borne/choisir ; anti-rebond de 0,6 s ; le son de la sortie
// borne (champ son : <audio data-role=borne-son>) ; le mode opérateur (code, puis pause, reprendre, ramener).
// Ce module ne charge que des fichiers de js/borne/ (les seuls permis depuis la tablette). Aucune donnée insérée
// en HTML (textContent) ; textes simples, sans jargon.

export const ECRANS_BORNE = ['hors_service', 'salles', 'suivez_moi', 'arrivee', 'retour', 'occupe', 'pause'];

export function demarrerBorne(racine) {
  racine.textContent = '';
  racine.setAttribute('data-ecran', 'hors_service');
  const titre = document.createElement('h1');
  titre.className = 'borne-titre';
  titre.textContent = 'Le robot se prépare. Revenez dans un instant !';
  racine.appendChild(titre);
  return { arreter: () => {} };
}

const racine = document.getElementById('borne');
if (racine) demarrerBorne(racine);
