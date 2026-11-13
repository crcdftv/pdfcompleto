// edit/rotation.js – gira a página focada (90º à esquerda ou à direita)
import { store, setStore } from '../store.js';
import { renderSinglePage } from '../pdf/render.js';
import { showTemporaryMessage } from '../ui/toast.js';

export async function rotatePageLeft() {
  const pg = store.focusedPage;
  if (!pg) { alert('Selecione uma página.'); return; }

  const cur = (store.pageRotations[pg] || 0) - 90;
  const nxt = cur < 0 ? cur + 360 : cur;
  setStore('pageRotations', { ...store.pageRotations, [pg]: nxt });

  await renderSinglePage(pg, store.currentScale, new AbortController().signal);
  showTemporaryMessage(`Página ${pg} girada 90° à esquerda`);
}

export async function rotatePageRight() {
  const pg = store.focusedPage;
  if (!pg) { alert('Selecione uma página.'); return; }

  const cur = (store.pageRotations[pg] || 0) + 90;
  const nxt = cur >= 360 ? cur - 360 : cur;
  setStore('pageRotations', { ...store.pageRotations, [pg]: nxt });

  await renderSinglePage(pg, store.currentScale, new AbortController().signal);
  showTemporaryMessage(`Página ${pg} girada 90° à direita`);
}
