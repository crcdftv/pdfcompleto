// ui/searchBar.js – abre/fecha a barra de busca e delega a busca ao módulo search/
import { store, setStore } from '../store.js';
import { searchInPDF, goToHighlight, clearSearch } from '../search/textSearch.js';

export function initSearchBar() {
  const toggleBtn  = document.getElementById('toggle-search');
  const bar        = document.getElementById('search-bar');
  const closeBtn   = document.getElementById('close-search');
  const searchBtn  = document.getElementById('search-button');
  const input      = document.getElementById('search-input');
  const prevBtn    = document.getElementById('prev-result');
  const nextBtn    = document.getElementById('next-result');
  const counter    = document.getElementById('search-counter');

  // Atualiza o contador "X / Y" após cada busca ou navegação
  function updateCounter() {
    const { highlights, currentIdx } = store.search;
    if (counter) {
      counter.textContent = highlights.length
        ? `${currentIdx + 1} / ${highlights.length}`
        : '0 / 0';
    }
  }

  // Executa a busca e atualiza o contador
  async function runSearch() {
    const term = input ? input.value.trim() : '';
    if (!term) return;
    await searchInPDF(term);
    updateCounter();
  }

  // Abre / fecha a barra
  toggleBtn.addEventListener('click', () => {
    if (!store.pdfDoc && !store.pdfUrl) {
      alert('Nenhum PDF carregado.');
      return;
    }
    bar.style.display = bar.style.display === 'flex' ? 'none' : 'flex';
    if (bar.style.display === 'flex' && input) input.focus();
  });

  // Fechar barra
  closeBtn.addEventListener('click', () => {
    bar.style.display = 'none';
    if (input) input.value = '';
    clearSearch();
    updateCounter();
  });

  // Botão de busca
  if (searchBtn) {
    searchBtn.addEventListener('click', runSearch);
  }

  // Enter no campo de texto
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') runSearch();
    });
  }

  // Navegar para o resultado anterior
  if (prevBtn) {
    prevBtn.addEventListener('click', () => {
      goToHighlight(store.search.currentIdx - 1);
      updateCounter();
    });
  }

  // Navegar para o próximo resultado
  if (nextBtn) {
    nextBtn.addEventListener('click', () => {
      goToHighlight(store.search.currentIdx + 1);
      updateCounter();
    });
  }
}

/* Exporta a função de "buscar" (pode ser chamada externamente se necessário) */
export { searchInPDF };