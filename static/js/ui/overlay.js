// ui/overlay.js – spinner usado por OCR, compressão, etc.
export function showLoadingOverlay(message = 'Processando…') {
  const overlay = document.getElementById('loading-overlay');
  const txt = document.getElementById('loading-text');
  if (overlay && txt) {
    txt.textContent = message;
    overlay.style.display = 'flex';
  }
}

export function hideLoadingOverlay() {
  const overlay = document.getElementById('loading-overlay');
  if (overlay) overlay.style.display = 'none';
}

/* Modal de compressão (já existente no HTML) */
export function showCompressionModal() {
  document.getElementById('compressModal').style.display = 'block';
  const bar = document.getElementById('compressProgress');
  bar.style.width = '0%';
}
export function hideCompressionModal() {
  document.getElementById('compressModal').style.display = 'none';
  const bar = document.getElementById('compressProgress');
  bar.style.width = '0%';
}
