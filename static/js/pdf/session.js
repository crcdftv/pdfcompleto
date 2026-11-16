// pdf/session.js – inicia a sessão de redação no Flask (necessário para undo/redo)
import { store } from '../store.js';
import { showTemporaryMessage } from '../ui/toast.js';

export async function iniciarSessaoRedacao(webPath) {
  const resp = await fetch('/init_redaction', {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ web_path: webPath })
  });

  if (!resp.ok) {
    const txt = await resp.text();
    throw new Error(`Erro ao iniciar sessão: ${txt}`);
  }
  await resp.json();
  showTemporaryMessage('Sessão de edição pronta.');
}
