// ui/toast.js – mensagens temporárias (ex.: “Zoom aumentado”)
export function showTemporaryMessage(message, timeout = 5000) {
  const note = document.createElement('div');
  note.textContent = message;
  note.style.cssText = `
    position:fixed; top:20px; left:50%; transform:translateX(-50%);
    background:#333; color:#fff; padding:10px 20px; border-radius:6px;
    font-size:16px; z-index:9999; box-shadow:0 4px 10px rgba(0,0,0,.3);
    opacity:0; transition:opacity .3s ease;
  `;
  document.body.appendChild(note);
  requestAnimationFrame(() => note.style.opacity = '1');

  setTimeout(() => {
    note.style.opacity = '0';
    setTimeout(() => note.remove(), 300);
  }, timeout);
}
