// edit/deletePage.js – remove página da visualização & do estado
import { store, setStore } from '../store.js';
import { generateThumbnails } from '../pdf/thumbnails.js';
import { renderPDFLocal } from '../pdf/render.js';
import { showTemporaryMessage } from '../ui/toast.js';

export async function deletePage(pageId) {
  store.pageOrder = store.pageOrder.filter(id => id !== pageId);
  delete store.pageMappings[pageId];
  store.pdfEdits.tarjas = store.pdfEdits.tarjas.filter(t => t.page !== pageId);
  store.texts = (store.texts || []).filter(t => t.page !== pageId);

  const container = document.querySelector(`.page-container[data-page-id="${pageId}"]`);
  if (container) container.remove();

  await renderPDFLocal(store.currentScale);
  await generateThumbnails();

  showTemporaryMessage(`Página ${pageId} removida.`);
}
