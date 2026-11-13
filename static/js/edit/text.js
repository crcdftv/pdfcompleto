import { store, setStore } from '../store.js';
import { showTemporaryMessage } from '../ui/toast.js';
import { redrawTarjasOnCanvas } from './redactionCanvas.js';

let isTextMode = false;
let selectedTextId = null;
let dragType = null;
let dragStartX, dragStartY, dragStartData;
let justFinalized = false;

export function toggleTextMode() {
  isTextMode = !isTextMode;
  const btn = document.getElementById('toggle-text-btn');

  if (isTextMode) {
    btn?.classList.add('active');
    document.body.classList.add('text-mode');
    document.body.style.cursor = 'text';
    showTemporaryMessage('Modo texto ativado - Clique na página para adicionar texto', 'info');
  } else {
    btn?.classList.remove('active');
    document.body.classList.remove('text-mode');
    document.body.style.cursor = 'default';
    selectedTextId = null;
    removeToolbar();
    updateSelection();
    showTemporaryMessage('Modo texto desativado', 'info');
  }
}

export function initTextTool() {
  const pdfRender = document.getElementById('pdf-render');
  if (!pdfRender) return;

  pdfRender.addEventListener('click', onCanvasClick);
  pdfRender.addEventListener('mousedown', onMouseDown);
  document.addEventListener('mousemove', onMouseMove);
  document.addEventListener('mouseup', onMouseUp);
}

function onCanvasClick(e) {
  if (!isTextMode || selectedTextId || justFinalized) return;

  const container = e.target.closest('.page-container');
  if (!container) return;

  const pageId = parseInt(container.dataset.pageId);
  if (!pageId) return;

  const drawCanvas = container.querySelector('.draw-canvas');
  if (!drawCanvas) return;

  const rect = drawCanvas.getBoundingClientRect();
  const x = (e.clientX - rect.left) / drawCanvas.width;
  const y = (e.clientY - rect.top) / drawCanvas.height;

  const id = 'txt_' + Date.now() + '_' + Math.random().toString(36).slice(2, 6);

  store.texts.push({ id, page: pageId, x, y, content: '', fontSize: 16, bold: false, italic: false, color: '#000000', width: 0, height: 0 });
  setStore('texts', store.texts);

  selectedTextId = id;
  showTextInput(container, drawCanvas, id);
}

function showTextInput(container, drawCanvas, id) {
  removeTextInput();

  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;

  const input = document.createElement('div');
  input.className = 'text-editor';
  input.contentEditable = true;
  input.dataset.textId = id;
  input.textContent = textData.content;
  input.style.fontSize = textData.fontSize + 'px';
  input.style.fontWeight = textData.bold ? 'bold' : 'normal';
  input.style.fontStyle = textData.italic ? 'italic' : 'normal';
  input.style.color = textData.color;
  input.style.minWidth = '60px';
  input.style.minHeight = '24px';

  const containerRect = drawCanvas.getBoundingClientRect();

  input.style.position = 'absolute';
  input.style.left = (textData.x * containerRect.width) + 'px';
  input.style.top = (textData.y * containerRect.height) + 'px';

  container.appendChild(input);
  input.focus();

  input.addEventListener('blur', () => finalizeText(id));
  input.addEventListener('keydown', e => {
    if (e.key === 'Escape') cancelText(id);
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); input.blur(); }
  });
}

function removeTextInput() {
  document.querySelectorAll('.text-editor').forEach(el => el.remove());
}

function finalizeText(id) {
  const input = document.querySelector(`.text-editor[data-text-id="${id}"]`);
  if (!input) return;

  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;

  const content = input.textContent.trim();
  if (!content) {
    store.texts = store.texts.filter(t => t.id !== id);
    setStore('texts', store.texts);
    removeTextInput();
    selectedTextId = null;
    removeToolbar();
    updateSelection();
    redrawAllTexts();
    return;
  }

  textData.content = content;
  textData.width = input.offsetWidth;
  textData.height = input.offsetHeight;

  setStore('texts', store.texts);
  removeTextInput();
  redrawAllTexts();
  justFinalized = true;
  setTimeout(() => { justFinalized = false; }, 300);
}

function cancelText(id) {
  store.texts = store.texts.filter(t => t.id !== id);
  setStore('texts', store.texts);
  removeTextInput();
  selectedTextId = null;
  removeToolbar();
  updateSelection();
  redrawAllTexts();
}

function hitTestText(pageId, x, y) {
  const candidates = store.texts.filter(t => t.page === pageId);
  for (let i = candidates.length - 1; i >= 0; i--) {
    const t = candidates[i];
    const margin = 10 / 100;
    if (x >= t.x - margin && x <= t.x + margin &&
        y >= t.y - margin && y <= t.y + margin) {
      return t.id;
    }
  }
  return null;
}

function onMouseDown(e) {
  const selBox = e.target.closest('.text-selection-box');
  if (selBox) {
    const id = selBox.dataset.textId;
    const handle = e.target.closest('.text-handle');
    if (handle) {
      dragType = handle.dataset.handle;
      selectedTextId = id;
      dragStartX = e.clientX;
      dragStartY = e.clientY;
      const textData = store.texts.find(t => t.id === id);
      if (textData) dragStartData = { ...textData };
      updateSelection();
      e.preventDefault();
      return;
    }

    selectedTextId = id;
    dragType = 'move';
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    const textData = store.texts.find(t => t.id === id);
    if (textData) dragStartData = { ...textData };
    updateSelection();
    e.preventDefault();
    return;
  }

  if (e.target.closest('.text-editor') || e.target.closest('.text-toolbar')) return;

  const container = e.target.closest('.page-container');
  if (!container) {
    selectedTextId = null;
    removeToolbar();
    updateSelection();
    return;
  }

  const pageId = parseInt(container.dataset.pageId);
  const drawCanvas = container.querySelector('.draw-canvas');
  if (!drawCanvas) return;

  const rect = drawCanvas.getBoundingClientRect();
  const cx = (e.clientX - rect.left) / rect.width;
  const cy = (e.clientY - rect.top) / rect.height;

  const hitId = hitTestText(pageId, cx, cy);
  if (hitId) {
    selectedTextId = hitId;
    dragType = 'move';
    dragStartX = e.clientX;
    dragStartY = e.clientY;
    const textData = store.texts.find(t => t.id === hitId);
    if (textData) dragStartData = { ...textData };
    updateSelection();
    e.preventDefault();
  } else {
    selectedTextId = null;
    removeToolbar();
    updateSelection();
  }
}

function onMouseMove(e) {
  if (!dragType || !selectedTextId) return;

  const textData = store.texts.find(t => t.id === selectedTextId);
  if (!textData) return;

  const container = document.querySelector(`.page-container[data-page-id="${textData.page}"]`);
  const drawCanvas = container?.querySelector('.draw-canvas');
  if (!drawCanvas) return;

  const rect = drawCanvas.getBoundingClientRect();
  const dx = (e.clientX - dragStartX) / rect.width;
  const dy = (e.clientY - dragStartY) / rect.height;

  if (dragType === 'move') {
    textData.x = Math.max(0, Math.min(1, dragStartData.x + dx));
    textData.y = Math.max(0, Math.min(1, dragStartData.y + dy));
  } else if (dragType === 'se' || dragType === 'e') {
    textData.fontSize = Math.max(8, Math.min(120, dragStartData.fontSize + dx * 50));
  } else if (dragType === 's' || dragType === 'sw') {
    textData.fontSize = Math.max(8, Math.min(120, dragStartData.fontSize + dy * 50));
  }

  redrawAllTexts();
  updateSelection();
}

function onMouseUp() {
  if (dragType && selectedTextId) {
    const textData = store.texts.find(t => t.id === selectedTextId);
    if (textData) setStore('texts', store.texts);
  }
  dragType = null;
  dragStartData = null;
}

function getFontString(t) {
  const style = t.italic ? 'italic ' : '';
  const weight = t.bold ? 'bold ' : '';
  return `${style}${weight}${t.fontSize}px sans-serif`;
}

function redrawAllTexts() {
  document.querySelectorAll('.draw-canvas').forEach(canvas => {
    const ctx = canvas.getContext('2d');
    const container = canvas.closest('.page-container');
    const pageId = parseInt(container.dataset.pageId);

    ctx.clearRect(0, 0, canvas.width, canvas.height);
    redrawTarjasOnCanvas(canvas);

    (store.texts || []).filter(t => t.page === pageId).forEach(t => {
      const x = t.x * canvas.width;
      const y = t.y * canvas.height;
      ctx.font = getFontString(t);
      ctx.fillStyle = t.color || '#000';
      ctx.textBaseline = 'top';
      const lines = t.content.split('\n');
      lines.forEach((line, i) => {
        ctx.fillText(line, x, y + i * (t.fontSize * 1.3));
      });
    });
  });
}

export function redrawTextsOnCanvas(canvas) {
  if (!store.texts?.length) return;

  const ctx = canvas.getContext('2d');
  const container = canvas.closest('.page-container');
  const pageId = parseInt(container.dataset.pageId);

  (store.texts || []).filter(t => t.page === pageId).forEach(t => {
    const x = t.x * canvas.width;
    const y = t.y * canvas.height;
    ctx.font = getFontString(t);
    ctx.fillStyle = t.color || '#000';
    ctx.textBaseline = 'top';
    const lines = t.content.split('\n');
    lines.forEach((line, i) => {
      ctx.fillText(line, x, y + i * (t.fontSize * 1.3));
    });
  });
}

function showToolbar(textData, container, rect) {
  removeToolbar();

  const bar = document.createElement('div');
  bar.className = 'text-toolbar';

  const boldBtn = document.createElement('button');
  boldBtn.className = 'tb-btn' + (textData.bold ? ' active' : '');
  boldBtn.innerHTML = '<b>B</b>';
  boldBtn.title = 'Negrito';
  boldBtn.addEventListener('click', e => { e.stopPropagation(); toggleBold(textData.id); });

  const italicBtn = document.createElement('button');
  italicBtn.className = 'tb-btn' + (textData.italic ? ' active' : '');
  italicBtn.innerHTML = '<i>I</i>';
  italicBtn.title = 'Itálico';
  italicBtn.addEventListener('click', e => { e.stopPropagation(); toggleItalic(textData.id); });

  const sizeInput = document.createElement('input');
  sizeInput.type = 'number';
  sizeInput.className = 'tb-size';
  sizeInput.value = textData.fontSize;
  sizeInput.min = 8;
  sizeInput.max = 120;
  sizeInput.title = 'Tamanho da fonte';
  sizeInput.addEventListener('change', e => { e.stopPropagation(); changeFontSize(textData.id, parseInt(e.target.value) || 16); });
  sizeInput.addEventListener('click', e => e.stopPropagation());

  const colorInput = document.createElement('input');
  colorInput.type = 'color';
  colorInput.className = 'tb-color';
  colorInput.value = textData.color;
  colorInput.title = 'Cor do texto';
  colorInput.addEventListener('input', e => { e.stopPropagation(); changeColor(textData.id, e.target.value); });
  colorInput.addEventListener('click', e => e.stopPropagation());

  bar.appendChild(boldBtn);
  bar.appendChild(italicBtn);
  bar.appendChild(sizeInput);
  bar.appendChild(colorInput);
  document.body.appendChild(bar);

  const barRect = bar.getBoundingClientRect();
  let left = rect.left + rect.width / 2 - barRect.width / 2;
  let top = rect.top - barRect.height - 8;
  if (top < 0) top = rect.bottom + 8;
  if (left < 4) left = 4;
  if (left + barRect.width > window.innerWidth - 4) left = window.innerWidth - barRect.width - 4;
  bar.style.left = left + 'px';
  bar.style.top = top + 'px';
}

function removeToolbar() {
  document.querySelectorAll('.text-toolbar').forEach(el => el.remove());
}

function toggleBold(id) {
  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;
  textData.bold = !textData.bold;
  setStore('texts', store.texts);
  redrawAllTexts();
  const rect = updateSelection();
  if (rect) showToolbar(textData, null, rect);
}

function toggleItalic(id) {
  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;
  textData.italic = !textData.italic;
  setStore('texts', store.texts);
  redrawAllTexts();
  const rect = updateSelection();
  if (rect) showToolbar(textData, null, rect);
}

function changeFontSize(id, size) {
  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;
  textData.fontSize = Math.max(8, Math.min(120, size));
  setStore('texts', store.texts);
  redrawAllTexts();
}

function changeColor(id, color) {
  const textData = store.texts.find(t => t.id === id);
  if (!textData) return;
  textData.color = color;
  setStore('texts', store.texts);
  redrawAllTexts();
}

function updateSelection() {
  document.querySelectorAll('.text-selection-box').forEach(el => el.remove());
  removeToolbar();

  if (!selectedTextId) return null;

  const textData = store.texts.find(t => t.id === selectedTextId);
  if (!textData) return null;

  const container = document.querySelector(`.page-container[data-page-id="${textData.page}"]`);
  if (!container) return null;

  const drawCanvas = container.querySelector('.draw-canvas');
  if (!drawCanvas) return null;

  const rect = drawCanvas.getBoundingClientRect();
  const box = document.createElement('div');
  box.className = 'text-selection-box';
  box.dataset.textId = selectedTextId;

  const x = textData.x * rect.width;
  const y = textData.y * rect.height;
  const w = Math.max(60, textData.width || 100);
  const h = Math.max(24, textData.height || textData.fontSize * 1.3);

  box.style.left = x + 'px';
  box.style.top = y + 'px';
  box.style.width = w + 'px';
  box.style.height = h + 'px';

  const handles = ['se', 'e', 's', 'sw'];
  handles.forEach(dir => {
    const hEl = document.createElement('div');
    hEl.className = 'text-handle';
    hEl.dataset.handle = dir;
    box.appendChild(hEl);
  });

  container.appendChild(box);

  box.addEventListener('dblclick', () => {
    showTextInput(container, drawCanvas, selectedTextId);
  });

  const boxRect = box.getBoundingClientRect();
  showToolbar(textData, container, boxRect);
  return boxRect;
}
