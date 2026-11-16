// edit/redaction.js
import { store } from '../store.js';
import { normalizeTarjaRect } from '../utils/coords.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { redrawTarjasOnCanvas } from './redactionCanvas.js';

let isDrawing = false;
let startX = 0;
let startY = 0;
let currentCanvas = null;
let undoInProgress = false;

// Serializa as operações com a sessão. Assim, uma nova tarja ou um desfazer
// nunca chega ao backend em uma ordem diferente da exibida na tela.
let redactionSessionQueue = Promise.resolve();

function enqueueSessionRequest(request) {
  const operation = redactionSessionQueue.then(request);
  redactionSessionQueue = operation.catch(() => undefined);
  return operation;
}

function serializeRedactions() {
  return store.pdfEdits.tarjas.map(tarja => ({
    page: tarja.page,
    xPercent: tarja.x,
    yPercent: tarja.y,
    widthPercent: tarja.w,
    heightPercent: tarja.h
  }));
}

async function getResponseError(response, fallbackMessage) {
  const data = await response.json().catch(() => ({}));
  return new Error(data.error || fallbackMessage);
}

/**
 * Sincroniza a lista atual de tarjas com a sessão do backend.
 */
export async function sincronizarHistoricoRedacao() {
  const redactions = serializeRedactions();

  return enqueueSessionRequest(async () => {
    const response = await fetch('/apply_redaction_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({ redactions })
    });

    if (!response.ok) {
      throw await getResponseError(response, 'Erro ao sincronizar as tarjas');
    }

    return response.json();
  });
}

/**
 * Ativa/desativa o modo de redação (tarja)
 */
export function toggleRedaction() {
  store.isRedacting = !store.isRedacting;
  const btn = document.getElementById('toggle-redaction-btn');

  if (store.isRedacting) {
    btn?.classList.add('active');
    document.body.classList.add('redaction-mode');
    showTemporaryMessage('Modo de tarja ativado - Clique e arraste para tarjar', 'info');
    document.body.style.cursor = 'crosshair';

    document.querySelectorAll('.text-layer').forEach(layer => {
      layer.style.pointerEvents = 'none';
    });
  } else {
    btn?.classList.remove('active');
    document.body.classList.remove('redaction-mode');
    showTemporaryMessage('Modo de tarja desativado', 'info');
    document.body.style.cursor = 'default';

    document.querySelectorAll('.text-layer').forEach(layer => {
      layer.style.pointerEvents = 'auto';
    });
  }
}

/**
 * Inicializa os eventos de desenho de tarja nos canvas
 */
export function initRedactionCanvas() {
  const pdfRender = document.getElementById('pdf-render');
  if (!pdfRender) {
    console.error('#pdf-render não encontrado');
    return;
  }

  // Event delegation para todos os draw-canvas
  pdfRender.addEventListener('mousedown', onMouseDown, true);
  pdfRender.addEventListener('mousemove', onMouseMove, true);
  pdfRender.addEventListener('mouseup', onMouseUp, true);
  pdfRender.addEventListener('mouseleave', onMouseLeave, true);
}

function onMouseDown(e) {
  if (!store.isRedacting) {
    return;
  }

  let canvas = e.target;

  if (canvas.classList.contains('text-layer') || canvas.classList.contains('pdf-canvas')) {
    const container = canvas.closest('.page-container');
    canvas = container?.querySelector('.draw-canvas');
  }

  if (!canvas || !canvas.classList.contains('draw-canvas')) {
    return;
  }

  isDrawing = true;
  currentCanvas = canvas;

  const rect = canvas.getBoundingClientRect();
  startX = e.clientX - rect.left;
  startY = e.clientY - rect.top;

  e.preventDefault();
  e.stopPropagation();
}

function onMouseMove(e) {
  if (!isDrawing || !currentCanvas || !store.isRedacting) return;

  const rect = currentCanvas.getBoundingClientRect();
  const currentX = e.clientX - rect.left;
  const currentY = e.clientY - rect.top;

  drawPreviewRect(currentCanvas, startX, startY, currentX, currentY);

  e.preventDefault();
}

async function onMouseUp(e) {
  if (!isDrawing || !currentCanvas) return;

  const rect = currentCanvas.getBoundingClientRect();
  const endX = e.clientX - rect.left;
  const endY = e.clientY - rect.top;

  const x = Math.min(startX, endX);
  const y = Math.min(startY, endY);
  const w = Math.abs(endX - startX);
  const h = Math.abs(endY - startY);

  // Ignora cliques muito pequenos
  if (w < 5 || h < 5) {
    const ctx = currentCanvas.getContext('2d');
    ctx.clearRect(0, 0, currentCanvas.width, currentCanvas.height);
    redrawTarjasOnCanvas(currentCanvas);
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  const container = currentCanvas.closest('.page-container');
  const pageId = container?.dataset.pageId;

  if (!pageId) {
    console.error('ID da página não encontrado');
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  const map = store.pageMappings[pageId];
  if (!map) {
    console.error('Mapeamento da página não encontrado:', pageId);
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  const normalized = normalizeTarjaRect(
    x, y, w, h,
    currentCanvas.width,
    currentCanvas.height
  );

  if (!normalized) {
    console.error('Erro ao normalizar as coordenadas da tarja');
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  const tarja = {
    page: parseInt(pageId, 10),
    x: normalized.x,
    y: normalized.y,
    w: normalized.w,
    h: normalized.h
  };

  store.pdfEdits.tarjas.push(tarja);
  redrawTarjasOnCanvas(currentCanvas);

  isDrawing = false;
  currentCanvas = null;

  e.preventDefault();

  try {
    await sincronizarHistoricoRedacao();
    showTemporaryMessage('Tarja aplicada com sucesso!', 'success');
  } catch (error) {
    console.error('Erro ao sincronizar a tarja com o backend:', error);
    showTemporaryMessage('A tarja foi criada, mas não foi possível sincronizá-la. Tente salvar novamente.', 'error');
  }
}

function onMouseLeave() {
  if (isDrawing && currentCanvas) {
    isDrawing = false;

    const ctx = currentCanvas.getContext('2d');
    ctx.clearRect(0, 0, currentCanvas.width, currentCanvas.height);
    redrawTarjasOnCanvas(currentCanvas);

    currentCanvas = null;
  }
}

/**
 * Desenha retângulo de preview em tempo real
 */
function drawPreviewRect(canvas, x1, y1, x2, y2) {
  const ctx = canvas.getContext('2d');

  ctx.clearRect(0, 0, canvas.width, canvas.height);
  redrawTarjasOnCanvas(canvas, false);

  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const w = Math.abs(x2 - x1);
  const h = Math.abs(y2 - y1);

  ctx.fillStyle = 'rgba(255, 0, 0, 0.5)';
  ctx.fillRect(x, y, w, h);

  ctx.strokeStyle = 'rgba(255, 0, 0, 0.9)';
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
}

/**
 * Desfaz a última tarja, inclusive depois de o PDF já ter sido salvo.
 */
export async function desfazerUltimaTarja() {
  if (undoInProgress) {
    return;
  }

  if (store.pdfEdits.tarjas.length === 0) {
    showTemporaryMessage('Nenhuma tarja para desfazer', 'warning');
    return;
  }

  undoInProgress = true;
  const undoButton = document.getElementById('undo-redaction-btn');
  if (undoButton) undoButton.disabled = true;

  const removedIndex = store.pdfEdits.tarjas.length - 1;
  const removed = store.pdfEdits.tarjas.pop();

  try {
    const redactions = serializeRedactions();

    await enqueueSessionRequest(async () => {
      const response = await fetch('/undo_last_redaction', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ redactions })
      });

      if (!response.ok) {
        throw await getResponseError(response, 'Erro ao desfazer tarja');
      }

      // Consome o PDF de pré-visualização retornado pelo endpoint.
      await response.blob();
    });

    showTemporaryMessage('Tarja desfeita com sucesso!', 'success');

    document.querySelectorAll('.draw-canvas').forEach(canvas => {
      redrawTarjasOnCanvas(canvas);
    });
  } catch (error) {
    console.error('Erro ao desfazer tarja:', error);
    store.pdfEdits.tarjas.splice(removedIndex, 0, removed);
    showTemporaryMessage(error.message || 'Erro ao desfazer tarja', 'error');
  } finally {
    undoInProgress = false;
    if (undoButton) undoButton.disabled = false;
  }
}
