// edit/reorder.js – troca duas páginas de lugar (drag‑and‑drop nas thumbnails)
import { store, setStore } from '../store.js';
import { renderPDFLocal } from '../pdf/render.js';
import { generateThumbnails } from '../pdf/thumbnails.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { highlightActiveThumbnail } from '../ui/thumbnailHighlight.js';

export async function reorderPages(fromId, toId) {
  const fromIdx = store.pageOrder.indexOf(fromId);
  const toIdx   = store.pageOrder.indexOf(toId);
  if (fromIdx === -1 || toIdx === -1) return;

  // se mover de antes para depois, ajusta índice (mesmo algoritmo original)
  const [moved] = store.pageOrder.splice(fromIdx, 1);
  const targetIdx = fromIdx < toIdx ? toIdx - 1 : toIdx;
  store.pageOrder.splice(targetIdx, 0, moved);

  // re‑renderiza documento e thumbnails
  await renderPDFLocal(store.currentScale);
  await generateThumbnails();

  highlightActiveThumbnail(store.focusedPage);
  showTemporaryMessage('Páginas reordenadas.');
}
