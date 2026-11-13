// edit/redactionCanvas.js – desenha todas as tarjas e textos num draw‑canvas
import { store } from '../store.js';

function getFontString(t) {
  const style = t.italic ? 'italic ' : '';
  const weight = t.bold ? 'bold ' : '';
  return `${style}${weight}${t.fontSize}px sans-serif`;
}

export function redrawTarjasOnCanvas(canvas) {
  const ctx = canvas.getContext('2d');
  ctx.clearRect(0, 0, canvas.width, canvas.height);

  const pageId = parseInt(canvas.parentNode.dataset.pageId, 10);

  store.pdfEdits.tarjas
       .filter(t => t.page === pageId)
       .forEach(t => {
         ctx.fillStyle = 'black';
         ctx.fillRect(
           t.x * canvas.width,
           t.y * canvas.height,
           t.w * canvas.width,
           t.h * canvas.height
         );
       });

  (store.texts || [])
       .filter(t => t.page === pageId)
       .forEach(t => {
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
