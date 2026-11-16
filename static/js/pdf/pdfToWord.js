// --- PDF para Word ---
  const pdfToWordBtn = document.getElementById('pdf-to-word-btn');
  if (pdfToWordBtn) {
    pdfToWordBtn.addEventListener('click', async () => {
      try {
        if (!store.currentPDF) {
          alert('Nenhum PDF carregado!');
          return;
        }

        const response = await fetch('/convert-to-word', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ filename: store.currentPDF })
        });

        if (!response.ok) {
          const errorData = await response.json().catch(() => ({}));
          throw new Error(errorData.error || 'Erro ao converter para Word');
        }

        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'documento.docx';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
      } catch (error) {
        console.error('❌ Erro ao converter para Word:', error);
        alert('Erro ao converter para Word: ' + error.message);
      }
    });
  }