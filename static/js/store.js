// store.js – estado central da aplicação (não há mais “global”)
export const store = {
  // PDF.js
  pdfDoc: null,
  pdfUrl: '',
  currentPdfPath: '',
  addedPdfPaths: [],

  // visualização
  currentScale: 1,
  pageOrder: [],               // ids originais (1‑based)
  pageMappings: {},            // {id: {pdfDoc, pageInDoc, canvasWidth, …}}
  pageRotations: {},          // {id: 0|90|180|270}
  focusedPage: null,          // id da página que tem foco

  // edição
  pdfEdits: { tarjas: [] },
  texts: [],

  // renderização
  isRendering: false,
  pendingRenderRequest: null,
  renderAbortController: null,
  zoomTimeout: null,

  // UI
  isRedacting: false,
  isTextSelecting: false,
  textSelection: {
    start: null,
    end: null,
    overlay: null,
    content: ''
  },

  // progresso
  conversionId: null,
  progressInterval: null,
  compressInterval: null,

  // busca
  search: {
    highlights: [],
    term: '',
    timeoutId: null,
    currentIdx: 0
  }
};

/* -------------- Event bus – permite que outros módulos observem mudanças ---------------- */
export const storeEvents = new EventTarget();

/**
 * Atualiza uma propriedade do store e dispara o evento `change`.
 * Exemplo:  setStore('focusedPage', 3);
 */
export function setStore(key, value) {
  store[key] = value;
  storeEvents.dispatchEvent(new CustomEvent('change', { detail: { key, value } }));
}
