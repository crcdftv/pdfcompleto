// signature/tokenDialog.js – abre popup, carrega tokens, devolve PIN + label
import { showTemporaryMessage } from '../ui/toast.js';

export async function openTokenDialog(onConfirm) {
  const popup    = document.getElementById('tokenPopup');
  const select   = document.getElementById('popupTokenSelect');
  const pinInp   = document.getElementById('popupPinInput');
  const confirm  = document.getElementById('popupConfirmBtn');

  popup.classList.remove('hidden');
  select.innerHTML = '<option value="">— selecione —</option>';
  pinInp.value = '';

  // carrega tokens
  try {
    const resp = await fetch('http://localhost:15002/list_tokens');
    const data = await resp.json();
    if (data.success) {
      data.tokens.forEach(t => {
        const opt = document.createElement('option');
        opt.value = t.label;
        opt.textContent = `${t.label} – ${t.serial}`;
        select.appendChild(opt);
      });
    }
  } catch (e) {
    alert('Erro ao listar tokens.');
    console.error(e);
    popup.classList.add('hidden');
    return;
  }

  const handler = async () => {
    const label = select.value.trim();
    const pin   = pinInp.value.trim();
    if (!label || !pin) {
      alert('Selecione token e informe PIN.');
      return;
    }
    popup.classList.add('hidden');
    confirm.removeEventListener('click', handler);
    onConfirm({ label, pin });
  };

  confirm.addEventListener('click', handler);
}