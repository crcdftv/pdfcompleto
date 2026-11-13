"""
Rotas de conversão PDF → Excel.
"""
import io
import os
import time
import logging
import threading

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
from flask import Blueprint, request, jsonify, send_file

from core.config import UPLOAD_FOLDER
from core.ocr_preprocess import prepare_for_ocr, run_best_config

logger = logging.getLogger(__name__)

excel_bp = Blueprint('excel', __name__)


@excel_bp.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Recurso não encontrado"}), 404

@excel_bp.errorhandler(400)
def bad_request(e):
    return jsonify({"error": "Requisição inválida"}), 400

@excel_bp.errorhandler(500)
def internal_error(e):
    logger.error(f"Erro interno: {e}")
    return jsonify({"error": "Erro interno do servidor"}), 500

# Armazena progresso das conversões Excel em andamento
excel_progress = {}


def limpar_excel():
    """Remove jobs de conversão Excel expirados (libera a memória do resultado)."""
    agora = time.time()
    for job_id in list(excel_progress.keys()):
        job = excel_progress.get(job_id)
        if not job:
            continue
        status = job.get('status', 'processing')
        ultima = job.get('_last_activity', job.get('created_at', agora))
        limite = 15 * 60 if status in ('done', 'error') else 60 * 60
        if agora - ultima > limite:
            del excel_progress[job_id]
            logger.info('[Excel] Job expirado removido: %s', job_id)


def _excel_worker(job_id, pdf_bytes, mode, quality):
    """Processa PDF → Excel: cabeçalho imagem + tabela estruturada."""
    try:
        import pdfplumber, bisect
        from collections import Counter
        from openpyxl import Workbook
        from openpyxl.styles import Font as XLFont, PatternFill, Alignment, Border, Side
        from openpyxl.utils import get_column_letter
        from openpyxl.drawing.image import Image as XLImage

        def upd(pct, status='processing', msg=''):
            excel_progress[job_id].update({
                'pct': pct, 'status': status, 'msg': msg,
                '_last_activity': time.time(),
            })

        def rgb_to_hex(color):
            if color is None: return None
            try:
                if isinstance(color,(int,float)):
                    v=max(0,min(255,int(color*255))); return f'{v:02X}{v:02X}{v:02X}'
                return ''.join(f'{max(0,min(255,int(c*255))):02X}' for c in color[:3])
            except: return None

        def is_white(h): return not h or h.upper() in ('FFFFFF','FFFFFE','FEFEFE','FDFDFD')
        def dark_bg(h):
            if not h or len(h)<6: return False
            return 0.299*int(h[:2],16)+0.587*int(h[2:4],16)+0.114*int(h[4:6],16)<140
        def clean_text(s):
            """Remove caracteres ilegais para o Excel (controle, null, etc)."""
            if not s: return s
            return ''.join(c for c in str(s) if ord(c) >= 32 or c in (chr(9), chr(10), chr(13)))

        def safe_color(h, fallback='000000'):
            """Garante que a cor é um hex RRGGBB válido para openpyxl."""
            if not h: return fallback
            h = str(h).strip().lstrip('#')
            if len(h) != 6: return fallback
            try: int(h, 16)
            except ValueError: return fallback
            return h.upper()

        def get_words(page):
            try: return page.extract_words(extra_attrs=['fontname','size','non_stroking_color'])
            except: return page.extract_words()

        def word_top(w): return w.get('top', w.get('y0', 0))
        def word_bot(w): return w.get('bottom', w.get('y1', 0))

        def cluster(vals, tol):
            out=[]
            for v in sorted(set(vals)):
                if out and abs(v-out[-1])<=tol: out[-1]=(out[-1]+v)/2
                else: out.append(v)
            return out

        def detect_col_bounds(rects, pw, tol=4):
            """Detecta fronteiras de colunas via rects alinhados (com tolerância)."""
            if not rects: return None
            cx0 = cluster([r['x0'] for r in rects], tol)
            cx1 = cluster([r['x1'] for r in rects], tol)
            if len(cx0) < 2: return None
            col_starts = [round(x) for x in cx0]
            col_end    = round(max(cx1))
            return col_starts, col_end

        def ocr_words_fn(page_num, dpi=None):
            if dpi is None:
                dpi = 200 if quality == 'fast' else 300
            doc=fitz.open(stream=pdf_bytes,filetype='pdf')
            pix=doc[page_num].get_pixmap(dpi=dpi)
            img=Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            doc.close()
            img=prepare_for_ocr(img)
            sc=72.0/dpi

            def _run(config):
                return pytesseract.image_to_data(img,config=config,
                                                 output_type=pytesseract.Output.DICT)

            def _score(tsv):
                return sum(len(t.strip()) for t,c in zip(tsv['text'],tsv['conf'])
                           if t.strip() and int(c)>30)

            # psm 6 (linhas) como hoje; psm 4 e 11 só se reconhecer pouco texto
            tsv=run_best_config(
                _run,
                (r'--oem 3 --psm 6 -l por+eng',
                 r'--oem 3 --psm 4 -l por+eng',
                 r'--oem 3 --psm 11 -l por+eng'),
                _score, min_score=20, label=f'pág {page_num+1}')
            return [{'text':t.strip(),'x0':tsv['left'][i]*sc,'top':tsv['top'][i]*sc,
                     'x1':(tsv['left'][i]+tsv['width'][i])*sc,
                     'bottom':(tsv['top'][i]+tsv['height'][i])*sc,
                     'bold':False,'size':10,'non_stroking_color':None}
                    for i,t in enumerate(tsv['text'])
                    if t.strip() and int(tsv['conf'][i])>30]

        upd(2, msg='Lendo PDF…')
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            total=len(pdf.pages)

        wb=Workbook()
        wb.remove(wb.active)
        thin=Side(style='thin',color='BBBBBB')
        brd=Border(left=thin,right=thin,top=thin,bottom=thin)
        dpi_h=80 if quality=='fast' else 120

        for page_idx in range(total):
            pct_base=int(page_idx/total*88)+2
            upd(pct_base, msg=f'Processando página {page_idx+1} de {total}…')

            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                page=pdf.pages[page_idx]
                pw,ph=page.width,page.height
                words=get_words(page)
                rects=[r for r in (page.rects or [])
                       if not is_white(rgb_to_hex(r.get('non_stroking_color')))]
                tables=[]
                if quality=='quality':
                    try:
                        tables=page.extract_tables({'vertical_strategy':'lines_strict',
                                                    'horizontal_strategy':'lines_strict'}) or []
                        if not tables: tables=page.extract_tables() or []
                    except: tables=[]
                if not words and not tables:
                    upd(pct_base+1,msg=f'Pág {page_idx+1}: OCR…')
                    words=ocr_words_fn(page_idx)

            table_top=min((r['top'] for r in rects), default=ph*0.25)

            ws=wb.create_sheet(title=f'Pag{page_idx+1}'[:31])
            xl_row=1

            if table_top>20:
                try:
                    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                        _p=pdf.pages[page_idx]
                        _y0=max(_p.bbox[1] if hasattr(_p,'bbox') else 0, 0)
                        _y1=min(table_top+5, _p.bbox[3] if hasattr(_p,'bbox') else ph)
                        crop_img=_p.crop((0,_y0,pw,_y1)).to_image(resolution=dpi_h)
                    buf=io.BytesIO(); crop_img.save(buf,format='PNG'); buf.seek(0)
                    xl_img=XLImage(buf)
                    target_w=620; scale=target_w/xl_img.width
                    xl_img.width=target_w; xl_img.height=int(xl_img.height*scale)
                    xl_img.anchor='A1'; ws.add_image(xl_img)
                    img_rows=max(8,int(xl_img.height/15))
                    for r in range(1,img_rows+1): ws.row_dimensions[r].height=15
                    xl_row=img_rows+1
                except Exception as ei:
                    pass

            title_ws=[w for w in words if table_top-60<=word_top(w)<table_top+30 and word_top(w)>150]
            if title_ws:
                seen=set(); parts=[]
                for t in ' '.join(w['text'] for w in sorted(title_ws,key=lambda w:w['x0'])).split():
                    if t not in seen: seen.add(t); parts.append(t)
                ws.row_dimensions[xl_row].height=28
                cell=ws.cell(row=xl_row,column=1,value=clean_text(' '.join(parts)))
                cell.font=XLFont(bold=True,size=16,color='0B3380')
                cell.alignment=Alignment(horizontal='center',vertical='center')
                ws.merge_cells(start_row=xl_row,start_column=1,end_row=xl_row,end_column=3)
                xl_row+=1
                ws.row_dimensions[xl_row].height=10; xl_row+=1

            fixed=detect_col_bounds(rects,pw)
            n_cols=3

            if tables:
                for i,w in enumerate([15,15,50]): ws.column_dimensions[get_column_letter(i+1)].width=w
                hfont=XLFont(bold=True,color='FFFFFF')
                hfill=PatternFill('solid',fgColor='2E75B6')
                for tbl in tables:
                    for r_idx,row in enumerate(tbl):
                        for c_idx,val in enumerate(row,1):
                            cell=ws.cell(row=xl_row,column=c_idx,value=clean_text(val) or '')
                            cell.alignment=Alignment(wrap_text=True,vertical='center')
                            cell.border=brd
                            if r_idx==0: cell.font=hfont; cell.fill=hfill
                        xl_row+=1
                    xl_row+=1

            elif fixed:
                col_x0s, col_x1_max=fixed
                col_bounds=col_x0s+[col_x1_max]
                n_cols=len(col_bounds)-1

                for ci in range(n_cols):
                    w_pts=col_bounds[ci+1]-col_bounds[ci]
                    ws.column_dimensions[get_column_letter(ci+1)].width=max(4,round(w_pts/pw*90,1))

                def col_of(x):
                    for i in range(len(col_bounds)-1):
                        if col_bounds[i]-6<=x<col_bounds[i+1]+6: return i
                    return n_cols-1

                first_col_x0=col_x0s[0]
                first_col_x1=col_x0s[1] if len(col_x0s)>1 else col_x1_max
                anchors=sorted(
                    [w for w in words
                     if first_col_x0-8<=w['x0']<=first_col_x1+5
                     and word_top(w)>=table_top-5],
                    key=lambda w:word_top(w)
                )

                for ai,anchor in enumerate(anchors):
                    y_top=word_top(anchor)-10
                    y_bot=word_top(anchors[ai+1])-5 if ai+1<len(anchors) else word_top(anchor)+80

                    line_rect=next(
                        (r for r in rects if r['top']<=word_top(anchor)+5<=r['bottom']
                         or abs(r['top']-word_top(anchor))<=20),None)
                    bg_hex=rgb_to_hex(line_rect.get('non_stroking_color')) if line_rect else None
                    if is_white(bg_hex): bg_hex=None

                    row_h=max(15,(line_rect['bottom']-line_rect['top'])*0.72) if line_rect else 20
                    ws.row_dimensions[xl_row].height=row_h

                    line_words=[w for w in words if y_top<=word_top(w)<y_bot]
                    cols_text={i:[] for i in range(n_cols)}
                    cols_style={i:None for i in range(n_cols)}
                    for w in sorted(line_words,key=lambda w:(word_top(w),w['x0'])):
                        ci=col_of(w['x0'])
                        cols_text[ci].append(w)
                        if cols_style[ci] is None:
                            fn=(w.get('fontname') or '').lower()
                            cols_style[ci]={
                                'bold':any(k in fn for k in ('bold','black','heavy','demi')),
                                'size':max(8,min(14,int(w.get('size') or 10))),
                                'fg':rgb_to_hex(w.get('non_stroking_color'))
                            }

                    for ci in range(n_cols):
                        try:
                            cell=ws.cell(row=xl_row,column=ci+1)
                            if type(cell).__name__=='MergedCell': continue
                        except AttributeError:
                            continue
                        cws=cols_text[ci]
                        if cws:
                            sublines={}
                            for w in cws:
                                ly=round(word_top(w)/4)*4
                                sublines.setdefault(ly,[]).append(w['text'])
                            text=chr(10).join(' '.join(sublines[ly]) for ly in sorted(sublines))
                        else: text=''
                        cell.value=clean_text(text) or None
                        cell.alignment=Alignment(wrap_text=True,vertical='center',horizontal='center')
                        cell.border=brd
                        if bg_hex:
                            cell.fill=PatternFill('solid',fgColor=safe_color(bg_hex,'EEEEEE'))
                            fc='FFFFFF' if dark_bg(bg_hex) else '000000'
                        else:
                            st=cols_style[ci] or {'bold':False,'size':10,'fg':None}
                            fg=st['fg']
                            fc=fg if fg and not is_white(fg) else '000000'
                        st=cols_style[ci] or {'bold':False,'size':10,'fg':None}
                        cell.font=XLFont(bold=st['bold'],size=st['size'],color=safe_color(fc))
                    xl_row+=1

            else:
                tol_x=max(4.0,pw*0.005); tol_y=max(3.0,ph*0.004)
                all_x=[w['x0'] for w in words]+[w['x1'] for w in words]
                all_y=[word_top(w) for w in words]+[word_bot(w) for w in words]
                if not all_x: all_x=[0,pw]; all_y=[0,ph]
                col_breaks=[0.0]+cluster(all_x,tol_x)+[float(pw)]
                row_breaks=[0.0]+cluster(all_y,tol_y)+[float(ph)]
                col_breaks=sorted(set(round(v,1) for v in col_breaks))
                row_breaks=sorted(set(round(v,1) for v in row_breaks))
                for ci in range(len(col_breaks)-1):
                    ws.column_dimensions[get_column_letter(ci+1)].width=max(1.5,(col_breaks[ci+1]-col_breaks[ci])*0.13)
                for ri in range(len(row_breaks)-1):
                    ws.row_dimensions[ri+1].height=max(5.0,(row_breaks[ri+1]-row_breaks[ri])*0.75)
                for r in rects:
                    h=rgb_to_hex(r.get('non_stroking_color'))
                    if not h or is_white(h): continue
                    c0=max(1,bisect.bisect_right(col_breaks,r['x0']))
                    r0=max(1,bisect.bisect_right(row_breaks,r['top']))
                    c1=max(1,bisect.bisect_right(col_breaks,r['x1']))
                    r1=max(1,bisect.bisect_right(row_breaks,r['bottom']))
                    fill=PatternFill('solid',fgColor=safe_color(h,'EEEEEE'))
                    for row in range(r0,min(r1+1,len(row_breaks))):
                        for col in range(c0,min(c1+1,len(col_breaks))):
                            ws.cell(row=row,column=col).fill=fill
                placed={}
                for w in words:
                    col=max(1,min(bisect.bisect_right(col_breaks,w['x0']),len(col_breaks)-1))
                    row=max(1,min(bisect.bisect_right(row_breaks,word_top(w)),len(row_breaks)-1))
                    key=(row,col)
                    if key not in placed: placed[key]=w.copy()
                    else: placed[key]['text']+=' '+w['text']
                for (row,col),w in placed.items():
                    try:
                        cell=ws.cell(row=row,column=col,value=clean_text(w['text']))
                        if hasattr(cell,'value') and type(cell).__name__=='MergedCell':
                            continue
                    except AttributeError:
                        continue
                    sz=max(7,min(16,int(w.get('size',10))))
                    fg_h=rgb_to_hex(w.get('non_stroking_color'))
                    fc=fg_h if fg_h and not is_white(fg_h) else '000000'
                    cell.font=XLFont(bold=any(k in (w.get('fontname') or '').lower()
                                     for k in ('bold','black','heavy')),size=sz,color=safe_color(fc))
                    cell.alignment=Alignment(wrap_text=False,vertical='center')

            footer=[w for w in words if word_top(w)>ph-80]
            if footer:
                xl_row_f=xl_row+1
                ws.row_dimensions[xl_row_f].height=12
                n_merge=n_cols
                cell=ws.cell(row=xl_row_f,column=1,
                             value=clean_text(' '.join(w['text'] for w in sorted(footer,key=lambda w:w['x0']))))
                cell.font=XLFont(italic=True,size=8,color='999999')
                cell.alignment=Alignment(horizontal='left')
                try: ws.merge_cells(start_row=xl_row_f,start_column=1,end_row=xl_row_f,end_column=n_merge)
                except: pass

            upd(pct_base+int(88/total),msg=f'Página {page_idx+1} concluída')

        upd(92,msg='Salvando arquivo…')
        out_buf=io.BytesIO(); wb.save(out_buf); out_buf.seek(0)
        upd(100,status='done',msg='Concluído!')
        excel_progress[job_id]['result']=out_buf.getvalue()
        excel_progress[job_id]['filename']=excel_progress[job_id].get('filename','resultado.xlsx')

    except Exception as e:
        excel_progress[job_id].update({'status':'error','msg':str(e),'pct':0})


@excel_bp.route('/convert/pdf-to-excel', methods=['POST'])
def pdf_to_excel():
    try:
        import pdfplumber
        from openpyxl import Workbook
    except ImportError as e:
        return jsonify({'error': f'Biblioteca não instalada: {e}'}), 500

    if request.is_json:
        data     = request.get_json()
        filename = (data.get('filename') or '').replace('/uploads/','').strip('/')
        quality  = data.get('quality', 'fast')
    else:
        filename = (request.form.get('filename') or '').replace('/uploads/','').strip('/')
        quality  = request.form.get('quality', 'fast')

    file_path = os.path.join(UPLOAD_FOLDER, os.path.basename(filename))
    if not os.path.isfile(file_path):
        return jsonify({'error': f'Arquivo não encontrado: {filename}'}), 404

    with open(file_path, 'rb') as f:
        pdf_bytes = f.read()

    job_id = f'excel_{int(time.time()*1000)}'
    excel_progress[job_id] = {
        'pct': 0, 'status': 'processing', 'msg': 'Iniciando…',
        'created_at': time.time(), '_last_activity': time.time(),
    }

    t = threading.Thread(
        target=_excel_worker,
        args=(job_id, pdf_bytes, 'auto', quality),
        daemon=True
    )
    t.start()

    original_name = os.path.splitext(os.path.basename(filename))[0]
    import re
    clean_name = re.sub(r'^\d+_', '', original_name)

    return jsonify({'job_id': job_id, 'filename': f'{clean_name}.xlsx'}), 202


@excel_bp.route('/convert/pdf-to-excel/progress/<job_id>', methods=['GET'])
def excel_conversion_progress(job_id):
    if job_id not in excel_progress:
        return jsonify({'error': 'Job não encontrado'}), 404
    p = excel_progress[job_id]
    return jsonify({
        'pct':    p.get('pct', 0),
        'status': p.get('status', 'processing'),
        'msg':    p.get('msg', '')
    })


@excel_bp.route('/convert/pdf-to-excel/download/<job_id>', methods=['GET'])
def excel_conversion_download(job_id):
    if job_id not in excel_progress:
        return jsonify({'error': 'Job não encontrado'}), 404
    p = excel_progress[job_id]
    if p.get('status') != 'done':
        return jsonify({'error': 'Conversão ainda não concluída'}), 425
    result = p.get('result')
    if not result:
        return jsonify({'error': 'Resultado não disponível'}), 500
    fname = p.get('filename', 'resultado.xlsx')
    del excel_progress[job_id]
    return send_file(
        io.BytesIO(result),
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=fname
    )
