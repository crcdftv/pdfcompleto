// pdf/textLayer.js – text layer com seleção nativa corrigida
import { store } from '../store.js';

export async function renderTextLayer(page, container, viewport) {
  container.innerHTML = '';

  container.style.position   = 'absolute';
  container.style.left       = '0';
  container.style.top        = '0';
  container.style.width      = `${viewport.width}px`;
  container.style.height     = `${viewport.height}px`;
  container.style.overflow   = 'hidden';
  container.style.lineHeight = '1';
  container.style.userSelect = 'text';

  const textContent = await page.getTextContent();
  const textDivs = [];

  await pdfjsLib.renderTextLayer({
    textContent,
    container,
    viewport,
    textDivs,
  }).promise;

  // Estiliza spans principais (com scaleX) e spans filhos de letra
  textDivs.forEach(span => {
    span.style.color            = 'transparent';
    span.style.cursor           = 'text';
    span.style.userSelect       = 'text';
    span.style.webkitUserSelect = 'text';
    span.style.pointerEvents    = 'auto';
    span.style.transformOrigin  = '0% 0%';

    // Spans filhos (letras individuais) precisam ser inline
    // e herdar o contexto de transform do pai para seleção precisa
    span.querySelectorAll('span').forEach(child => {
      child.style.color            = 'transparent';
      child.style.display          = 'inline';
      child.style.userSelect       = 'text';
      child.style.webkitUserSelect = 'text';
    });
  });

  // Bloqueia seleção apenas no modo tarja
  container.addEventListener('mousedown', (e) => {
    if (store.isRedacting) e.preventDefault();
  });

  // Copia automaticamente ao soltar o mouse
  container.addEventListener('mouseup', async () => {
    if (store.isRedacting) return;
    const txt = window.getSelection()?.toString().trim();
    if (!txt) return;
    try {
      await navigator.clipboard.writeText(txt);
      const { showTemporaryMessage } = await import('../ui/toast.js');
      showTemporaryMessage('Texto copiado!');
    } catch { /* silencioso */ }
  });
}