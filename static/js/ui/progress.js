// ui/progress.js – barra de progresso única (OCR, compressão, upload, etc.)
import { store } from '../store.js';

export function showProgress(containerId = 'progress-container') {
  const cont = document.getElementById(containerId);
  if (cont) cont.style.display = 'flex';
}

export function hideProgress(containerId = 'progress-container') {
  const cont = document.getElementById(containerId);
  if (cont) cont.style.display = 'none';
}

/**
 * Atualiza a barra (percentual) e textos auxiliares.
 * `status` e `pages` são strings opcionalmente exibidas abaixo da barra.
 */
export function setProgress(percent, status = '', pages = '',
                         containerId = 'progress-container') {
  const bar = document.getElementById('progress-bar');
  if (bar) {
    bar.style.width = `${percent}%`;
    bar.textContent = `${percent}%`;
  }

  if (status) {
    let el = document.getElementById('progressText');
    if (!el) {
      el = document.createElement('div');
      el.id = 'progressText';
      el.style.marginTop = '5px';
      document.getElementById(containerId).appendChild(el);
    }
    el.textContent = status;
  }

  if (pages) {
    let el = document.getElementById('progressPages');
    if (!el) {
      el = document.createElement('div');
      el.id = 'progressPages';
      el.style.fontSize = '12px';
      el.style.color = '#555';
      document.getElementById(containerId).appendChild(el);
    }
    el.textContent = pages;
  }
}
