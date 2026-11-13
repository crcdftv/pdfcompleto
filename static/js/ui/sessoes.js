// ui/sessoes.js – indicador de sessões ativas no rodapé do menu
//
// Sem login no sistema, a contagem vem de heartbeat: o servidor considera
// "ativa" uma sessão que consultou /sessoes nos últimos 2 minutos, então
// este módulo pergunta de 30 em 30 segundos (e assim também se mantém vivo).

const INTERVALO_MS = 30 * 1000;

export function initSessoesIndicator() {
  const box = document.getElementById('sessoes-indicator');
  const texto = document.getElementById('sessoes-texto');
  if (!box || !texto) return;

  async function atualizar() {
    try {
      const resp = await fetch('/sessoes', { credentials: 'same-origin' });
      if (!resp.ok) return;
      const { ativos } = await resp.json();
      const n = Number(ativos) || 0;
      texto.textContent = n === 1 ? '1 sessão ativa' : `${n} sessões ativas`;
      box.title = `Sessões ativas no momento: ${n}`;
    } catch (err) {
      // servidor indisponível: mantém o último valor e tenta de novo depois
    }
  }

  atualizar();
  setInterval(atualizar, INTERVALO_MS);

  // quem voltou para a aba já renova na hora
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState === 'visible') atualizar();
  });
}
