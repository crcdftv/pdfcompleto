// Configuração local do worker do PDF.js.
// Mantém o carregamento no mesmo domínio, evitando o fallback "fake worker".
window.pdfjsLib.GlobalWorkerOptions.workerSrc = "/static/pdf.worker.min.js";
