// edit/redaction.js
import { store, setStore } from '../store.js';
import { normalizeTarjaRect } from '../utils/coords.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { redrawTarjasOnCanvas } from './redactionCanvas.js';

let isDrawing = false;
let startX = 0;
let startY = 0;
let currentCanvas = null;

/**
 * Ativa/desativa o modo de redação (tarja)
 */
export function toggleRedaction() {
  store.isRedacting = !store.isRedacting;
  const btn = document.getElementById('toggle-redaction-btn');

  console.log('🔄 Toggle redação:', store.isRedacting);

  if (store.isRedacting) {
    btn?.classList.add('active');
    document.body.classList.add('redaction-mode'); // ⭐ ADICIONA CLASSE
    showTemporaryMessage('Modo de tarja ativado - Clique e arraste para tarjar', 'info');
    document.body.style.cursor = 'crosshair';

    // ⭐ Desabilita text-layer temporariamente
    document.querySelectorAll('.text-layer').forEach(layer => {
      layer.style.pointerEvents = 'none';
    });
  } else {
    btn?.classList.remove('active');
    document.body.classList.remove('redaction-mode'); // ⭐ REMOVE CLASSE
    showTemporaryMessage('Modo de tarja desativado', 'info');
    document.body.style.cursor = 'default';

    // ⭐ Reabilita text-layer
    document.querySelectorAll('.text-layer').forEach(layer => {
      layer.style.pointerEvents = 'auto';
    });
  }
}

/**
 * Inicializa os eventos de desenho de tarja nos canvas
 */
export function initRedactionCanvas() {
  console.log('🔧 Inicializando eventos de redação...');

  const pdfRender = document.getElementById('pdf-render');
  if (!pdfRender) {
    console.error('❌ #pdf-render NÃO encontrado!');
    return;
  }

  // Event delegation para todos os draw-canvas
  pdfRender.addEventListener('mousedown', onMouseDown, true);
  pdfRender.addEventListener('mousemove', onMouseMove, true);
  pdfRender.addEventListener('mouseup', onMouseUp, true);
  pdfRender.addEventListener('mouseleave', onMouseLeave, true);

  console.log('✅ Eventos de redação registrados em #pdf-render');
}

function onMouseDown(e) {
  console.log('🖱️ mousedown disparado', {
    target: e.target.className,
    isRedacting: store.isRedacting,
    element: e.target.tagName
  });

  if (!store.isRedacting) {
    console.log('⏸️ Modo redação desativado, ignorando');
    return;
  }

  // ⭐ ACEITA tanto draw-canvas quanto page-container
  let canvas = e.target;

  if (canvas.classList.contains('text-layer') || canvas.classList.contains('pdf-canvas')) {
    // Se clicou na text-layer ou pdf-canvas, pega o draw-canvas do mesmo container
    const container = canvas.closest('.page-container');
    canvas = container?.querySelector('.draw-canvas');
    console.log('🔄 Redirecionando clique para draw-canvas');
  }

  if (!canvas || !canvas.classList.contains('draw-canvas')) {
    console.log('⏸️ Canvas de desenho não encontrado');
    return;
  }

  isDrawing = true;
  currentCanvas = canvas;

  const rect = canvas.getBoundingClientRect();
  startX = e.clientX - rect.left;
  startY = e.clientY - rect.top;

  console.log('✅ Iniciando desenho:', {
    startX,
    startY,
    canvasSize: `${canvas.width}x${canvas.height}`
  });

  // ⭐ Previne comportamento padrão
  e.preventDefault();
  e.stopPropagation();
}

function onMouseMove(e) {
  if (!isDrawing || !currentCanvas || !store.isRedacting) return;

  const rect = currentCanvas.getBoundingClientRect();
  const currentX = e.clientX - rect.left;
  const currentY = e.clientY - rect.top;

  // Desenha preview em tempo real
  drawPreviewRect(currentCanvas, startX, startY, currentX, currentY);

  e.preventDefault();
}

function onMouseUp(e) {
  console.log('🖱️ mouseup disparado', { isDrawing });

  if (!isDrawing || !currentCanvas) return;

  const rect = currentCanvas.getBoundingClientRect();
  const endX = e.clientX - rect.left;
  const endY = e.clientY - rect.top;

  const x = Math.min(startX, endX);
  const y = Math.min(startY, endY);
  const w = Math.abs(endX - startX);
  const h = Math.abs(endY - startY);

  console.log('📐 Coordenadas finais:', { x, y, w, h });

  // Ignora cliques muito pequenos
  if (w < 5 || h < 5) {
    console.log('⚠️ Tarja muito pequena, ignorando');
    const ctx = currentCanvas.getContext('2d');
    ctx.clearRect(0, 0, currentCanvas.width, currentCanvas.height);
    redrawTarjasOnCanvas(currentCanvas);
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  // Pega o ID da página
  const container = currentCanvas.closest('.page-container');
  const pageId = container?.dataset.pageId;

  console.log('📄 Container encontrado:', { pageId, container: !!container });

  if (!pageId) {
    console.error('❌ Page ID não encontrado');
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  const map = store.pageMappings[pageId];
  if (!map) {
    console.error('❌ Mapeamento não encontrado para:', pageId);
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  // Normaliza coordenadas (0..1)
  const normalized = normalizeTarjaRect(
    x, y, w, h,
    currentCanvas.width,
    currentCanvas.height
  );

  console.log('📊 Coordenadas normalizadas:', normalized);

  if (!normalized) {
    console.error('❌ Erro ao normalizar coordenadas');
    isDrawing = false;
    currentCanvas = null;
    return;
  }

  // Salva a tarja no store
  const tarja = {
    page: parseInt(pageId),
    x: normalized.x,
    y: normalized.y,
    w: normalized.w,
    h: normalized.h
  };

  store.pdfEdits.tarjas.push(tarja);
  console.log('✅ Tarja adicionada ao store:', tarja);
  console.log('📊 Total de tarjas no store:', store.pdfEdits.tarjas.length);

  // Envia para o backend (sessão)
  saveTarjaToBackend(tarja);

  // Redesenha o canvas com a tarja permanente
  redrawTarjasOnCanvas(currentCanvas);

  isDrawing = false;
  currentCanvas = null;

  showTemporaryMessage('Tarja aplicada com sucesso!', 'success');

  e.preventDefault();
}

function onMouseLeave(e) {
  if (isDrawing && currentCanvas) {
    console.log('🚪 Mouse saiu durante desenho');
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

  // Limpa o canvas
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  // Redesenha tarjas permanentes
  redrawTarjasOnCanvas(canvas, false);

  // Desenha o preview da tarja atual
  const x = Math.min(x1, x2);
  const y = Math.min(y1, y2);
  const w = Math.abs(x2 - x1);
  const h = Math.abs(y2 - y1);

  ctx.fillStyle = 'rgba(255, 0, 0, 0.5)'; // Vermelho semi-transparente para preview
  ctx.fillRect(x, y, w, h);

  ctx.strokeStyle = 'rgba(255, 0, 0, 0.9)';
  ctx.lineWidth = 2;
  ctx.strokeRect(x, y, w, h);
}

/**
 * Salva a tarja no backend (sessão)
 */
async function saveTarjaToBackend(tarja) {
  try {
    console.log('📤 Enviando tarja para backend:', tarja);

    const response = await fetch('/apply_redaction_session', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      credentials: 'include',
      body: JSON.stringify({
        page: tarja.page,
        xPercent: tarja.x,
        yPercent: tarja.y,
        widthPercent: tarja.w,
        heightPercent: tarja.h
      })
    });

    if (!response.ok) {
      console.error('❌ Erro ao salvar tarja no backend:', response.status);
    } else {
      console.log('✅ Tarja salva no backend');
    }
  } catch (error) {
    console.error('❌ Erro ao enviar tarja:', error);
  }
}

/**
 * Desfaz a última tarja
 */
export async function desfazerUltimaTarja() {
  console.log('↩️ Desfazendo tarja...');

  if (store.pdfEdits.tarjas.length === 0) {
    showTemporaryMessage('Nenhuma tarja para desfazer', 'warning');
    return;
  }

  const removida = store.pdfEdits.tarjas.pop();
  console.log('🗑️ Tarja removida:', removida);

  try {
    const response = await fetch('/undo_last_redaction', {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json' }
    });

    if (response.ok) {
      showTemporaryMessage('Tarja desfeita com sucesso!', 'success');

      const allDrawCanvas = document.querySelectorAll('.draw-canvas');
      allDrawCanvas.forEach(canvas => redrawTarjasOnCanvas(canvas));
    } else {
      store.pdfEdits.tarjas.push(removida);
      showTemporaryMessage('Erro ao desfazer tarja', 'error');
    }
  } catch (error) {
    console.error('❌ Erro ao desfazer:', error);
    store.pdfEdits.tarjas.push(removida);
    showTemporaryMessage('Erro ao desfazer tarja', 'error');
  }
}