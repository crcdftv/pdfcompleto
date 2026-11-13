// ui/menu.js – abre/fecha o menu lateral
import { setStore } from '../store.js';

export function initMenu() {
  const toggleBtn = document.getElementById('menu-toggle');
  const menu = document.getElementById('menu');

  if (window.innerWidth > 768) {
    menu.classList.add('open');
    toggleBtn.style.display = 'none';
  }

  toggleBtn.addEventListener('click', () => {
    menu.classList.add('open');
    toggleBtn.style.display = 'none';
  });
}
