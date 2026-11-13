"""
Rotas de compressão de PDF.
Ghostscript + PyMuPDF + rasterização como fallback.
"""
import os
import io
import glob
import time
import shutil
import tempfile
import logging
import subprocess
import threading

import fitz  # PyMuPDF
from PIL import Image
from werkzeug.utils import secure_filename

try:
    import img2pdf
except Exception:
    img2pdf = None

from flask import Blueprint, request, jsonify, send_file, send_from_directory, abort

from core.config import UPLOAD_FOLDER, COMPRESSED_FOLDER

logger = logging.getLogger(__name__)

compress_bp = Blueprint('compress', __name__)


@compress_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@compress_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@compress_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500


# Dicionário global de jobs
compress_progress = {}


def _ghostscript_path():
    """Localiza o executável do Ghostscript."""
    GS_NETWORK = r"\\srvsql\gs\gs10.03.1\bin"
    for exe in ("gswin64c.exe", "gswin32c.exe"):
        full = os.path.join(GS_NETWORK, exe)
        if os.path.isfile(full):
            return full

    for candidate in ("gswin64c", "gswin32c", "gs"):
        if shutil.which(candidate):
            return candidate

    for pattern in (
        r"C:\Program Files\gs\gs*\bin\gswin64c.exe",
        r"C:\Program Files (x86)\gs\gs*\bin\gswin32c.exe",
    ):
        matches = glob.glob(pattern)
        if matches:
            return sorted(matches)[-1]

    return None


def _compress_with_ghostscript(input_path, output_path, quality_level, custom_profile=None):
    """Comprime PDF usando Ghostscript."""
    gs_profiles = {
        "baixa":   {"jpeg_q": 40,  "color_dpi": 100, "gray_dpi": 100, "mono_dpi": 300},
        "medio":   {"jpeg_q": 65,  "color_dpi": 120, "gray_dpi": 120, "mono_dpi": 300},
        "alta":    {"jpeg_q": 80,  "color_dpi": 200, "gray_dpi": 200, "mono_dpi": 600},
        "extrema": {"jpeg_q": 10,  "color_dpi": 100, "gray_dpi": 100, "mono_dpi": 300},
    }
    cfg = custom_profile if custom_profile else gs_profiles.get(quality_level, gs_profiles["medio"])
    gs = _ghostscript_path()
    if not gs:
        raise FileNotFoundError("Ghostscript nao encontrado")

    cmd = [
        gs, "-dNOPAUSE", "-dBATCH", "-dQUIET", "-dSAFER",
        "-sDEVICE=pdfwrite", "-dPDFSETTINGS=/default", "-dCompatibilityLevel=1.5",
        "-dCompressPages=true", "-dCompressFonts=true", "-dEmbedAllFonts=true",
        "-dSubsetFonts=true", "-dDetectDuplicateImages=true",
        "-dDownsampleColorImages=true", "-dColorImageDownsampleType=/Bicubic",
        f"-dColorImageResolution={cfg['color_dpi']}",
        "-dColorImageDownsampleThreshold=1.0", "-dAutoFilterColorImages=false",
        "-dColorImageFilter=/DCTEncode", f"-dJPEGQ={cfg['jpeg_q']}",
        "-dDownsampleGrayImages=true", "-dGrayImageDownsampleType=/Bicubic",
        f"-dGrayImageResolution={cfg['gray_dpi']}",
        "-dGrayImageDownsampleThreshold=1.0", "-dAutoFilterGrayImages=false",
        "-dGrayImageFilter=/DCTEncode",
        "-dDownsampleMonoImages=true", "-dMonoImageDownsampleType=/Subsample",
        f"-dMonoImageResolution={cfg['mono_dpi']}",
        "-dMonoImageDownsampleThreshold=1.0",
        f"-sOutputFile={output_path}", input_path,
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode != 0:
        raise RuntimeError(f"Ghostscript erro {result.returncode}: {result.stderr[:500]}")


def _compress_with_pymupdf(input_path, output_path, quality_level):
    """Compressão multi-etapas com PyMuPDF."""
    profiles = {
        "baixa":   {"jpeg_quality": 75},
        "medio":   {"jpeg_quality": 55},
        "alta":    {"jpeg_quality": 85},
        "extrema": {"jpeg_quality": 30},
    }
    cfg = profiles.get(quality_level, profiles["medio"])

    doc = fitz.open(input_path)
    temp_clean = output_path + '.clean.tmp'
    doc.save(temp_clean, garbage=4, clean=True)
    doc.close()

    doc = fitz.open(temp_clean)
    for page in doc:
        for img_info in page.get_images(full=True):
            xref = img_info[0]
            try:
                doc.compress_image(xref, quality=cfg['jpeg_quality'])
            except Exception:
                pass

    doc.save(output_path, garbage=4, deflate=True, deflate_images=True,
             deflate_fonts=True, clean=True)
    doc.close()

    try:
        os.unlink(temp_clean)
    except Exception:
        pass


def _finalizar_job(job_id, input_path, output_path, original_size, original_name, engine):
    """Calcula redução e marca o job como done."""
    compressed_size = os.path.getsize(output_path)
    reduction_percent = round((1 - compressed_size / original_size) * 100, 1)

    if compressed_size >= original_size:
        shutil.copy2(input_path, output_path)
        compressed_size = original_size
        reduction_percent = 0.0

    logger.info(
        f'[Compressao] {original_name} | '
        f'{round(original_size/1024/1024,2)} MB -> '
        f'{round(compressed_size/1024/1024,2)} MB '
        f'({reduction_percent}% reducao) | engine={engine}'
    )

    compress_progress[job_id].update({
        'pct': 100, 'status': 'done', 'msg': 'Concluido!',
        'original_size_mb': round(original_size / (1024 * 1024), 2),
        'compressed_size_mb': round(compressed_size / (1024 * 1024), 2),
        'reduction_percent': reduction_percent,
        'engine': engine, 'original_name': original_name,
    })


def _compress_worker_pymupdf(job_id, input_path, output_path, quality_level, original_name):
    """Worker PyMuPDF com progresso."""
    def upd(pct, msg='', status='processing'):
        compress_progress[job_id].update({'pct': pct, 'status': status, 'msg': msg})

    try:
        upd(3, 'Abrindo PDF...')
        original_size = os.path.getsize(input_path)

        try:
            doc_tmp = fitz.open(input_path)
            total = doc_tmp.page_count
            doc_tmp.close()
        except Exception:
            total = 10

        if quality_level == "extrema":
            is_small = original_size <= 30 * 1024 * 1024
            alvo = 2 * 1024 * 1024

            gs = _ghostscript_path()
            if gs:
                tentativas = [
                    {"jpeg_q": 10, "color_dpi": 150, "gray_dpi": 150, "mono_dpi": 300},
                    {"jpeg_q":  8, "color_dpi": 120, "gray_dpi": 120, "mono_dpi": 300},
                    {"jpeg_q":  5, "color_dpi": 100, "gray_dpi": 100, "mono_dpi": 300},
                    {"jpeg_q":  5, "color_dpi":  72, "gray_dpi":  72, "mono_dpi": 200},
                ]
                if not is_small:
                    tentativas = [tentativas[-1]]

                for i, perfil in enumerate(tentativas):
                    upd(10 + i * 15, f'GS {perfil["color_dpi"]} DPI Q{perfil["jpeg_q"]}...')
                    tmp = output_path + f'.gs{i}.tmp'
                    try:
                        _compress_with_ghostscript(input_path, tmp, "extrema", perfil)
                        size = os.path.getsize(tmp)
                        if not is_small or size <= alvo:
                            upd(50, 'Finalizando...')
                            shutil.move(tmp, output_path)
                            upd(100, 'Concluido!')
                            _finalizar_job(job_id, input_path, output_path,
                                           original_size, original_name,
                                           'ghostscript-target' if is_small else 'ghostscript')
                            return
                    except Exception:
                        continue
                    finally:
                        try:
                            os.unlink(tmp)
                        except Exception:
                            pass

            upd(60, 'GS indisponivel - rasterizando paginas...')
            doc = fitz.open(input_path)
            total = doc.page_count

            if is_small:
                dpi, quality = 120, 15
            else:
                dpi, quality = 100, 10
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            jpegs = []

            for i in range(total):
                pix = doc[i].get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=quality, optimize=True, progressive=False)
                buf.seek(0)
                jpegs.append(buf.read())
                pct = 60 + int(((i + 1) / total) * 35)
                upd(pct, f'Renderizando pagina {i+1}/{total}...')

            doc.close()
            upd(97, 'Gerando PDF...')
            with open(output_path, "wb") as f:
                f.write(img2pdf.convert(jpegs))
            upd(100, 'Concluido!')
            _finalizar_job(job_id, input_path, output_path,
                           original_size, original_name, 'raster-target')
            return

        upd(8, 'Otimizando estrutura...')
        temp_pymupdf = output_path + '.pymupdf.tmp'

        doc_clean = fitz.open(input_path)
        temp_clean_n = output_path + '.pymupdf_clean.tmp'
        doc_clean.save(temp_clean_n, garbage=4, clean=True)
        doc_clean.close()

        upd(15, 'Analisando imagens...')
        doc = fitz.open(temp_clean_n)
        total_imgs = 0
        for page in doc:
            total_imgs += len(page.get_images(full=True))

        if total_imgs == 0:
            upd(60, 'Compactando streams...')
            shutil.move(temp_clean_n, temp_pymupdf)
        else:
            q_map = {"baixa": 75, "medio": 55, "alta": 85}
            q = q_map.get(quality_level, 55)
            comp_idx = 0
            for page in doc:
                for img_info in page.get_images(full=True):
                    xref = img_info[0]
                    try:
                        doc.compress_image(xref, quality=q)
                    except Exception:
                        pass
                    comp_idx += 1
                    pct = 15 + int((comp_idx / total_imgs) * 75)
                    upd(pct, f'Imagem {comp_idx}/{total_imgs}...')

            doc.save(temp_pymupdf, garbage=4, deflate=True, deflate_images=True,
                     deflate_fonts=True, clean=True)
            try:
                os.unlink(temp_clean_n)
            except Exception:
                pass
        doc.close()

        upd(97, 'Finalizando...')
        shutil.move(temp_pymupdf, output_path)
        upd(100, 'Concluido!')
        _finalizar_job(job_id, input_path, output_path,
                       original_size, original_name, 'pymupdf')

    except Exception as e:
        logger.exception('[Compress-PyMuPDF] Falha no worker')
        compress_progress[job_id].update({'status': 'error', 'msg': str(e), 'pct': 0})


def _compress_worker_target_size(job_id, input_path, output_path, target_size_mb, original_name):
    """Worker que tenta atingir um tamanho alvo."""
    def upd(pct, msg='', status='processing'):
        compress_progress[job_id].update({'pct': pct, 'status': status, 'msg': msg})

    try:
        upd(2, 'Analisando PDF...')
        original_size = os.path.getsize(input_path)
        target_bytes = target_size_mb * 1024 * 1024

        if original_size <= target_bytes:
            shutil.copy2(input_path, output_path)
            upd(100, 'PDF ja esta dentro do tamanho alvo!')
            _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'none')
            return

        gs_path = _ghostscript_path()
        melhor_tamanho = original_size
        melhor_caminho = None

        # Fase 1: Limpeza PyMuPDF
        upd(3, 'Limpando estrutura do PDF...')
        temp_clean = output_path + '.clean.tmp'
        temp_clean_ok = False
        try:
            doc_clean = fitz.open(input_path)
            doc_clean.save(temp_clean, garbage=4, clean=True)
            doc_clean.close()
            clean_size = os.path.getsize(temp_clean)
            if clean_size <= target_bytes:
                shutil.move(temp_clean, output_path)
                upd(100, f'Limpeza ja atingiu alvo ({round(clean_size/1024/1024,1)}MB)!')
                _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'clean-target')
                return
            temp_clean_ok = True
            melhor_tamanho = clean_size
            melhor_caminho = temp_clean
        except Exception:
            try:
                os.unlink(temp_clean)
            except Exception:
                pass
            temp_clean_ok = False

        # Fase 2: Ghostscript
        if gs_path:
            perfis_gs = [
                {"jpeg_q": 85, "color_dpi": 200, "gray_dpi": 200, "mono_dpi": 600},
                {"jpeg_q": 75, "color_dpi": 170, "gray_dpi": 170, "mono_dpi": 500},
                {"jpeg_q": 65, "color_dpi": 140, "gray_dpi": 140, "mono_dpi": 400},
                {"jpeg_q": 55, "color_dpi": 120, "gray_dpi": 120, "mono_dpi": 300},
                {"jpeg_q": 45, "color_dpi": 100, "gray_dpi": 100, "mono_dpi": 300},
                {"jpeg_q": 35, "color_dpi": 85,  "gray_dpi": 85,  "mono_dpi": 200},
                {"jpeg_q": 25, "color_dpi": 72,  "gray_dpi": 72,  "mono_dpi": 200},
                {"jpeg_q": 15, "color_dpi": 60,  "gray_dpi": 60,  "mono_dpi": 150},
                {"jpeg_q": 10, "color_dpi": 50,  "gray_dpi": 50,  "mono_dpi": 120},
                {"jpeg_q": 5,  "color_dpi": 40,  "gray_dpi": 40,  "mono_dpi": 100},
                {"jpeg_q": 3,  "color_dpi": 30,  "gray_dpi": 30,  "mono_dpi": 72},
                {"jpeg_q": 1,  "color_dpi": 24,  "gray_dpi": 24,  "mono_dpi": 60},
            ]

            for i, perfil in enumerate(perfis_gs):
                pct_base = 5 + int((i / len(perfis_gs)) * 40)
                upd(pct_base, f'GS Q{perfil["jpeg_q"]} {perfil["color_dpi"]}DPI...')
                tmp = output_path + f'.gs_{i}.tmp'
                try:
                    _compress_with_ghostscript(temp_clean if temp_clean_ok else input_path, tmp, "extrema", perfil)
                    size = os.path.getsize(tmp)
                    if size <= target_bytes:
                        shutil.move(tmp, output_path)
                        upd(95, f'Atingiu alvo! (Q{perfil["jpeg_q"]})')
                        _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'gs-target')
                        return
                    if size < melhor_tamanho:
                        melhor_tamanho = size
                        if melhor_caminho and melhor_caminho != tmp and melhor_caminho != temp_clean and os.path.isfile(melhor_caminho):
                            try:
                                os.unlink(melhor_caminho)
                            except Exception:
                                pass
                        melhor_caminho = tmp
                    else:
                        try:
                            os.unlink(tmp)
                        except Exception:
                            pass
                except Exception:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass

        # Fase 3: PyMuPDF
        upd(50, 'GS insuficiente - compactando imagens com PyMuPDF...')
        perfis_pymupdf = [40, 25, 15, 8, 3]
        for quality in perfis_pymupdf:
            tmp = output_path + f'.pymupdf_{quality}.tmp'
            try:
                doc = fitz.open(temp_clean if temp_clean_ok else input_path)
                for page in doc:
                    for img_info in page.get_images(full=True):
                        xref = img_info[0]
                        try:
                            doc.compress_image(xref, quality=quality)
                        except Exception:
                            pass
                doc.save(tmp, garbage=4, deflate=True, deflate_images=True,
                         deflate_fonts=True, clean=True)
                doc.close()
                size = os.path.getsize(tmp)
                if size <= target_bytes:
                    shutil.move(tmp, output_path)
                    upd(95, f'Atingiu alvo! (PyMuPDF Q{quality})')
                    if temp_clean_ok:
                        try:
                            os.unlink(temp_clean)
                        except Exception:
                            pass
                    _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'pymupdf-target')
                    return
                if size < melhor_tamanho:
                    if melhor_caminho and melhor_caminho != tmp and melhor_caminho != temp_clean and os.path.isfile(melhor_caminho):
                        try:
                            os.unlink(melhor_caminho)
                        except Exception:
                            pass
                    melhor_caminho = tmp
                    melhor_tamanho = size
                else:
                    try:
                        os.unlink(tmp)
                    except Exception:
                        pass
            except Exception:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

        # Fase 4: Rasterizacao
        upd(65, 'PyMuPDF insuficiente - rasterizando paginas...')
        doc = fitz.open(input_path)
        total = doc.page_count

        raster_profiles = [(120, 70), (100, 50), (80, 35), (60, 20), (50, 10), (40, 5)]

        for idx, (dpi, q) in enumerate(raster_profiles):
            pct_base = 55 + int((idx / len(raster_profiles)) * 35)
            upd(pct_base, f'Raster {dpi}DPI Q{q} - pagina 1/{total}...')
            zoom = dpi / 72.0
            mat = fitz.Matrix(zoom, zoom)
            jpegs = []
            for i in range(total):
                pix = doc[i].get_pixmap(matrix=mat, alpha=False)
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                buf = io.BytesIO()
                img.save(buf, format="JPEG", quality=q, optimize=True, progressive=False)
                buf.seek(0)
                jpegs.append(buf.read())
                sub_pct = pct_base + int(((i + 1) / total) * (35 / len(raster_profiles)))
                upd(sub_pct, f'Raster {dpi}DPI Q{q} - pagina {i+1}/{total}...')

            tmp = output_path + f'.raster_{idx}.tmp'
            with open(tmp, "wb") as f:
                f.write(img2pdf.convert(jpegs))

            size = os.path.getsize(tmp)
            if size <= target_bytes:
                if idx > 0:
                    prev_dpi, prev_q = raster_profiles[idx - 1]
                    mid_dpi = (prev_dpi + dpi) // 2
                    mid_q = (prev_q + q) // 2
                    upd(92, f'Ajustando qualidade... (testando {mid_dpi}DPI Q{mid_q})')
                    zoom_mid = mid_dpi / 72.0
                    mat_mid = fitz.Matrix(zoom_mid, zoom_mid)
                    mid_jpegs = []
                    for i in range(total):
                        pix = doc[i].get_pixmap(matrix=mat_mid, alpha=False)
                        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                        buf = io.BytesIO()
                        img.save(buf, format="JPEG", quality=mid_q, optimize=True, progressive=False)
                        buf.seek(0)
                        mid_jpegs.append(buf.read())
                    mid_tmp = output_path + '.raster_mid.tmp'
                    with open(mid_tmp, "wb") as f:
                        f.write(img2pdf.convert(mid_jpegs))
                    mid_size = os.path.getsize(mid_tmp)
                    if mid_size <= target_bytes:
                        higher_dpi = (prev_dpi + mid_dpi) // 2
                        higher_q = (prev_q + mid_q) // 2
                        if higher_dpi != mid_dpi or higher_q != mid_q:
                            upd(93, f'Refinando mais... ({higher_dpi}DPI Q{higher_q})')
                            zoom_h = higher_dpi / 72.0
                            mat_h = fitz.Matrix(zoom_h, zoom_h)
                            h_jpegs = []
                            for i in range(total):
                                pix = doc[i].get_pixmap(matrix=mat_h, alpha=False)
                                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
                                buf = io.BytesIO()
                                img.save(buf, format="JPEG", quality=higher_q, optimize=True, progressive=False)
                                buf.seek(0)
                                h_jpegs.append(buf.read())
                            h_tmp = output_path + '.raster_high.tmp'
                            with open(h_tmp, "wb") as f:
                                f.write(img2pdf.convert(h_jpegs))
                            h_size = os.path.getsize(h_tmp)
                            if h_size <= target_bytes:
                                os.replace(h_tmp, output_path)
                                try:
                                    os.unlink(mid_tmp)
                                except Exception:
                                    pass
                                upd(95, f'Atingiu alvo! (raster {higher_dpi}DPI Q{higher_q})')
                                doc.close()
                                _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'raster-target')
                                return
                            else:
                                os.replace(mid_tmp, output_path)
                                try:
                                    os.unlink(h_tmp)
                                except Exception:
                                    pass
                                upd(95, f'Atingiu alvo! (raster {mid_dpi}DPI Q{mid_q})')
                                doc.close()
                                _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'raster-target')
                                return
                        else:
                            os.replace(mid_tmp, output_path)
                            upd(95, f'Atingiu alvo! (raster {mid_dpi}DPI Q{mid_q})')
                            doc.close()
                            _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'raster-target')
                            return
                    else:
                        os.replace(tmp, output_path)
                        try:
                            os.unlink(mid_tmp)
                        except Exception:
                            pass
                        upd(95, f'Atingiu alvo! (raster {dpi}DPI Q{q})')
                        doc.close()
                        _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'raster-target')
                        return
                else:
                    shutil.move(tmp, output_path)
                    doc.close()
                    upd(95, f'Atingiu alvo! (raster {dpi}DPI Q{q})')
                    _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'raster-target')
                    return

            if size < melhor_tamanho:
                melhor_tamanho = size
                if melhor_caminho != temp_clean:
                    try:
                        os.unlink(melhor_caminho)
                    except Exception:
                        pass
                melhor_caminho = tmp
            else:
                try:
                    os.unlink(tmp)
                except Exception:
                    pass

        doc.close()

        if temp_clean_ok:
            try:
                os.unlink(temp_clean)
            except Exception:
                pass

        if melhor_caminho and os.path.isfile(melhor_caminho):
            shutil.move(melhor_caminho, output_path)
            upd(100, f'Melhor possivel: {round(melhor_tamanho/1024/1024,1)}MB')
            _finalizar_job(job_id, input_path, output_path, original_size, original_name, 'best-effort')
        else:
            raise RuntimeError('Nenhuma tentativa de compressao funcionou')

    except Exception as e:
        if temp_clean_ok:
            try:
                os.unlink(temp_clean)
            except Exception:
                pass
        logger.exception('[Compress-Target] Falha no worker')
        compress_progress[job_id].update({'status': 'error', 'msg': str(e), 'pct': 0})


def _start_compress_job(input_path, output_path, quality_level, original_name, target_size_mb=None):
    """Escolhe o engine, registra o job e dispara a thread."""
    job_id = f'compress_{int(time.time() * 1000)}'
    compress_progress[job_id] = {
        'pct': 0, 'status': 'processing', 'msg': 'Iniciando...',
        'output_path': output_path,
    }

    if target_size_mb:
        worker = _compress_worker_target_size
        args = (job_id, input_path, output_path, target_size_mb, original_name)
    else:
        worker = _compress_worker_pymupdf
        args = (job_id, input_path, output_path, quality_level, original_name)

    threading.Thread(target=worker, args=args, daemon=True).start()
    return job_id


# ── Rotas ──────────────────────────────────────────────────────────────────

@compress_bp.route('/comprimir_pdf', methods=['POST'])
def comprimir_pdf():
    """Inicia compressão a partir de arquivo já no servidor."""
    data = request.get_json(force=True, silent=True) or {}

    input_pdf_relative = (data.get('input_pdf_path') or '').replace('\\', '/').strip()
    output_pdf_relative = (data.get('output_pdf_path') or '').replace('\\', '/').strip()
    quality_level = data.get('quality', 'medio')

    if not input_pdf_relative or not output_pdf_relative:
        return jsonify({'success': False, 'message': 'Caminhos nao fornecidos'}), 400

    if quality_level not in ('baixa', 'medio', 'alta', 'extrema'):
        quality_level = 'medio'

    input_filename = secure_filename(input_pdf_relative.split('/')[-1])
    output_filename = secure_filename(output_pdf_relative.split('/')[-1])

    os.makedirs(COMPRESSED_FOLDER, exist_ok=True)
    input_pdf_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, input_filename))
    output_pdf_path = os.path.abspath(os.path.join(COMPRESSED_FOLDER, output_filename))

    if not os.path.isfile(input_pdf_path):
        return jsonify({'success': False, 'message': 'Arquivo nao encontrado'}), 400

    job_id = _start_compress_job(input_pdf_path, output_pdf_path, quality_level, input_filename)
    return jsonify({'job_id': job_id}), 202


@compress_bp.route('/comprimir_pdf_target', methods=['POST'])
def comprimir_pdf_target():
    """Compressão com tamanho alvo a partir de arquivo no servidor."""
    data = request.get_json(force=True, silent=True) or {}
    input_pdf_relative = (data.get('input_pdf_path') or '').replace('\\', '/').strip()
    output_pdf_relative = (data.get('output_pdf_path') or '').replace('\\', '/').strip()
    target_size_mb = float(data.get('target_size_mb', 2))

    if not input_pdf_relative or not output_pdf_relative:
        return jsonify({'success': False, 'message': 'Caminhos nao fornecidos'}), 400

    input_filename = secure_filename(input_pdf_relative.split('/')[-1])
    output_filename = secure_filename(output_pdf_relative.split('/')[-1])

    os.makedirs(COMPRESSED_FOLDER, exist_ok=True)
    input_pdf_path = os.path.abspath(os.path.join(UPLOAD_FOLDER, input_filename))
    output_pdf_path = os.path.abspath(os.path.join(COMPRESSED_FOLDER, output_filename))

    if not os.path.isfile(input_pdf_path):
        return jsonify({'success': False, 'message': 'Arquivo nao encontrado'}), 400

    job_id = _start_compress_job(input_pdf_path, output_pdf_path, 'medio', input_filename, target_size_mb=target_size_mb)
    return jsonify({'job_id': job_id}), 202


@compress_bp.route('/comprimir_pdf_upload', methods=['POST'])
def comprimir_pdf_upload():
    """Compressão a partir de upload direto."""
    pdf_file = request.files.get('pdf')
    quality_level = request.form.get('quality', 'medio')

    if pdf_file is None or not pdf_file.filename:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado'}), 400

    if quality_level not in ('baixa', 'medio', 'alta', 'extrema'):
        quality_level = 'medio'

    original_name = secure_filename(
        os.path.basename(pdf_file.filename).replace('\\', '/').split('/')[-1]
    ) or 'arquivo.pdf'

    tmp_in = tempfile.NamedTemporaryFile(suffix='_in.pdf', delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix='_out.pdf', delete=False)
    tmp_in.close()
    tmp_out.close()
    pdf_file.save(tmp_in.name)

    job_id = _start_compress_job(tmp_in.name, tmp_out.name, quality_level, original_name)

    compress_progress[job_id]['_tmp_in'] = tmp_in.name
    compress_progress[job_id]['_tmp_out'] = tmp_out.name
    compress_progress[job_id]['_is_tmp'] = True

    return jsonify({'job_id': job_id}), 202


@compress_bp.route('/comprimir_pdf_upload_target', methods=['POST'])
def comprimir_pdf_upload_target():
    """Compressão com alvo a partir de upload direto."""
    pdf_file = request.files.get('pdf')
    target_size_mb = float(request.form.get('target_size_mb', 2))

    if pdf_file is None or not pdf_file.filename:
        return jsonify({'success': False, 'message': 'Nenhum arquivo enviado'}), 400

    original_name = secure_filename(
        os.path.basename(pdf_file.filename).replace('\\', '/').split('/')[-1]
    ) or 'arquivo.pdf'

    tmp_in = tempfile.NamedTemporaryFile(suffix='_in.pdf', delete=False)
    tmp_out = tempfile.NamedTemporaryFile(suffix='_out.pdf', delete=False)
    tmp_in.close()
    tmp_out.close()
    pdf_file.save(tmp_in.name)

    job_id = _start_compress_job(tmp_in.name, tmp_out.name, 'medio', original_name, target_size_mb=target_size_mb)

    compress_progress[job_id]['_tmp_in'] = tmp_in.name
    compress_progress[job_id]['_tmp_out'] = tmp_out.name
    compress_progress[job_id]['_is_tmp'] = True

    return jsonify({'job_id': job_id}), 202


@compress_bp.route('/comprimir_pdf/progress/<job_id>', methods=['GET'])
def compress_job_progress(job_id):
    """Polling de progresso da compressão."""
    if job_id not in compress_progress:
        return jsonify({'error': 'Job nao encontrado'}), 404
    p = compress_progress[job_id]
    return jsonify({
        'pct': p.get('pct', 0),
        'status': p.get('status', 'processing'),
        'msg': p.get('msg', ''),
        'reduction_percent': p.get('reduction_percent'),
        'original_size_mb': p.get('original_size_mb'),
        'compressed_size_mb': p.get('compressed_size_mb'),
        'engine': p.get('engine'),
    })


@compress_bp.route('/comprimir_pdf/download/<job_id>', methods=['GET'])
def compress_job_download(job_id):
    """Download do PDF comprimido."""
    if job_id not in compress_progress:
        return jsonify({'error': 'Job nao encontrado'}), 404

    p = compress_progress[job_id]
    if p.get('status') != 'done':
        return jsonify({'error': 'Compressao ainda nao concluida'}), 425

    output_path = p.get('output_path') or p.get('_tmp_out')
    original_name = p.get('original_name', 'documento.pdf')

    if not output_path or not os.path.isfile(output_path):
        return jsonify({'error': 'Arquivo comprimido nao encontrado'}), 500

    reduction_percent = p.get('reduction_percent', 0)
    original_size_mb = p.get('original_size_mb', 0)
    compressed_size_mb = p.get('compressed_size_mb', 0)
    engine = p.get('engine', '')
    is_tmp = p.get('_is_tmp', False)
    tmp_in = p.get('_tmp_in')
    tmp_out = p.get('_tmp_out')

    del compress_progress[job_id]

    nome_comprimido = original_name.replace('.pdf', '_comprimido.pdf') \
                      if not original_name.endswith('_comprimido.pdf') else original_name

    def _cleanup_tmp():
        if is_tmp:
            for path in (tmp_in, tmp_out):
                try:
                    if path and os.path.exists(path):
                        os.unlink(path)
                except Exception:
                    pass

    response = send_file(
        output_path, mimetype='application/pdf', as_attachment=True,
        download_name=nome_comprimido, conditional=False,
    )
    response.headers['X-Reduction-Percent'] = str(reduction_percent)
    response.headers['X-Original-Size-MB'] = str(original_size_mb)
    response.headers['X-Compressed-Size-MB'] = str(compressed_size_mb)
    response.headers['X-Engine-Used'] = engine
    response.headers['Access-Control-Expose-Headers'] = (
        'X-Reduction-Percent, X-Original-Size-MB, X-Compressed-Size-MB, X-Engine-Used'
    )
    response.call_on_close(_cleanup_tmp)
    return response


@compress_bp.route('/compressed/<path:filename>')
def serve_compressed(filename):
    """Serve arquivos comprimidos."""
    folder = COMPRESSED_FOLDER
    full = os.path.abspath(os.path.join(folder, filename))
    if not full.startswith(os.path.abspath(folder)) or not os.path.isfile(full):
        abort(404)
    return send_from_directory(folder, filename, as_attachment=True,
                               download_name=filename, mimetype='application/pdf')
