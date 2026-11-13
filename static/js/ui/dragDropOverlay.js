// ui/dragDropOverlay.js – mostra um overlay ao arrastar arquivos sobre o PDF
export function initDragDropOverlay() {
  const overlay = document.getElementById('drop-overlay');

  if (!overlay) return;

  let timer = null;

  document.body.addEventListener('dragenter', e => {
    e.preventDefault();
    clearTimeout(timer);
    overlay.style.display = 'flex';
  });

  document.body.addEventListener('dragleave', e => {
    if (e.clientX <= 0 || e.clientY <= 0 || e.clientX >= window.innerWidth || e.clientY >= window.innerHeight) {
      timer = setTimeout(() => { overlay.style.display = 'none'; }, 100);
    }
  });

  document.body.addEventListener('dragover', e => e.preventDefault());

  overlay.addEventListener('drop', async e => {
    e.preventDefault();
    overlay.style.display = 'none';
    const files = e.dataTransfer.files;
    if (files.length) {
      const { uploadPDF } = await import('../pdf/upload.js');
      await uploadPDF(files[0]);
    }
  });
}
