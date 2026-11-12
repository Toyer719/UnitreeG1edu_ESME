// Le son de la sortie « borne » (vague 6, sections 13.5 et 13.6 du plan) : chaque phrase annoncée dans l'état
// (champ son : {id, url}) est jouée une seule fois par <audio data-role=borne-son>. Un navigateur ne joue du son
// qu'après un geste de l'utilisateur : le premier appui sur l'écran le débloque (un silence très court, fabriqué
// ici). Agent Borne et orchestrateur.

// Un fichier WAV de silence (PCM 8 kHz, 16 bits, 0,05 s), en mémoire : rien n'est téléchargé
export function wavSilence() {
  const echantillons = 400;
  const tampon = new ArrayBuffer(44 + echantillons * 2);
  const v = new DataView(tampon);
  const ecrire = (pos, texte) => {
    for (let i = 0; i < texte.length; i++) v.setUint8(pos + i, texte.charCodeAt(i));
  };
  ecrire(0, 'RIFF');
  v.setUint32(4, 36 + echantillons * 2, true);
  ecrire(8, 'WAVE');
  ecrire(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true);
  v.setUint16(22, 1, true);
  v.setUint32(24, 8000, true);
  v.setUint32(28, 16000, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  ecrire(36, 'data');
  v.setUint32(40, echantillons * 2, true);
  return new Blob([tampon], { type: 'audio/wav' });
}

// audio : l'élément <audio> ; → {debloquer(), jouer(son), dejaJoue(id), ignorer(id), parle()}
export function creerSon(audio) {
  const joues = new Set();
  let debloque = false;
  let silence = null;
  return {
    debloquer: () => {
      if (debloque) return;
      debloque = true;
      try {
        if (!silence) silence = URL.createObjectURL(wavSilence());
        if (!audio.getAttribute('src')) {
          audio.src = silence;
          const p = audio.play();
          if (p && p.catch) p.catch(() => {});
        }
      } catch (e) {
        // pas de son dans ce navigateur : la borne marche sans
      }
    },
    jouer: (son) => {
      if (!son || !son.id || !son.url || joues.has(son.id)) return false;
      joues.add(son.id);
      audio.setAttribute('data-son', son.id);
      audio.src = son.url;
      try {
        const p = audio.play();
        if (p && p.catch) p.catch(() => {});
      } catch (e) {
        return true;
      }
      return true;
    },
    dejaJoue: (id) => joues.has(id),
    ignorer: (id) => {
      if (id) joues.add(id);
    },
    parle: () => !audio.paused && !audio.ended && audio.getAttribute('data-son') !== null,
  };
}
