import os
import sys
import io
import re
import time
import json
import base64
import hashlib
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple, Union



import fitz  # PyMuPDF
from rich.console import Console



# Windows konsol desteği
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass



console = Console(legacy_windows=False)



from utils.config import (
    GOOGLE_API_KEY,
    GOOGLE_MODEL_NAME,
)
from utils.text_tr import tr_lower



SUPPORTED_IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".tiff", ".tif", ".bmp", ".webp"}
SUPPORTED_DOC_EXTENSIONS = {".pdf", ".md", ".txt", ".html"} | SUPPORTED_IMAGE_EXTENSIONS



# ==============================================================================
# Bütünlük Doğrulayıcıları ve Hataları
# ==============================================================================
class DocumentIntegrityError(Exception):
    """Doküman sayfa sayısı veya içerik bütünlüğü doğrulanamadığında fırlatılır."""
    pass





def get_expected_page_count_from_name(filename: str):
    """
    Dosya adından sayfa sayısı iddiasını çıkarır.
    Örn: '...-604 SAYFA.pdf' -> 604, 'foo SAYFA 10.pdf' -> 10, '...-236 SAYFA-1-130' -> 130.
    İhale kayıt numaralarını ('2015-78345') veya parça kodlarını sayfa aralığı sanmaz.
    """
    # 1. Açık sayfa aralığı (Range): SAYFA-1-130, Sayfa_1_330, 1-130 SAYFA
    range_m = re.search(r"(?:sayfa|sf)[_\s-]*(\d+)\s*[-_]\s*(\d+)", filename, re.IGNORECASE)
    if not range_m:
        range_m = re.search(r"(\d+)\s*[-_]\s*(\d+)\s*(?:sayfa|sf)", filename, re.IGNORECASE)
    if range_m:
        start_p, end_p = int(range_m.group(1)), int(range_m.group(2))
        if 0 < start_p < end_p and (end_p - start_p + 1) <= 2000 and end_p <= 3000:
            return end_p - start_p + 1
    # 2. Sayı ÖNDE: '10 SAYFA', 'foo-10 SAYFA.pdf', '91_sf'
    m1 = re.search(r"(?<!\d)(\d+)\s*[-_]?(?:sayfa|sf)\b", filename, re.IGNORECASE)
    if m1:
        val = int(m1.group(1))
        if 0 < val <= 3000:
            return val
    # 3. Sayı ARKADA: 'foo SAYFA 10.pdf', 'foo SAYFA_10.pdf', 'foo sf 10.pdf'
    m2 = re.search(r"\b(?:sayfa|sf)[_\s-]+(\d+)(?!\d)", filename, re.IGNORECASE)
    if m2:
        val = int(m2.group(1))
        if 0 < val <= 3000:
            return val
    return None


# ==============================================================================
# Model Singletonları (Her sayfa için yeniden yüklemeyi engeller - Ö3 Düzeltmesi)
# ==============================================================================
_RAPID_OCR_INSTANCE = None
_RAPID_TABLE_INSTANCE = None





def get_rapid_ocr():
    global _RAPID_OCR_INSTANCE
    if _RAPID_OCR_INSTANCE is None:
        try:
            # PyTorch CUDA kütüphanelerini ONNX Runtime için DLL arama yoluna ekle
            torch_lib = Path(sys.prefix) / "Lib" / "site-packages" / "torch" / "lib"
            if torch_lib.exists():
                try:
                    os.add_dll_directory(str(torch_lib))
                    os.environ["PATH"] = str(torch_lib) + os.pathsep + os.environ.get("PATH", "")
                except Exception:
                    pass
            from rapidocr import RapidOCR
            # ONNXRuntime-GPU CUDA execution provider aktif et
            params = {"EngineConfig.onnxruntime.use_cuda": True}
            _RAPID_OCR_INSTANCE = RapidOCR(params=params)
        except Exception as e:
            console.print(f"[yellow]RapidOCR yüklenemedi: {e}[/yellow]")
    return _RAPID_OCR_INSTANCE



def get_rapid_table():
    global _RAPID_TABLE_INSTANCE
    if _RAPID_TABLE_INSTANCE is None:
        try:
            from rapid_table import RapidTable
            _RAPID_TABLE_INSTANCE = RapidTable()
        except Exception as e:
            console.print(f"[yellow]RapidTable yüklenemedi: {e}[/yellow]")
    return _RAPID_TABLE_INSTANCE





_DOCLING_CONVERTER_INSTANCE = None





def get_docling_converter():
    """Docling v2 singleton converter nesnesi döndürür (CUDA veya CPU)."""
    global _DOCLING_CONVERTER_INSTANCE
    if _DOCLING_CONVERTER_INSTANCE is None:
        try:
            import torch
            from docling.document_converter import DocumentConverter, PdfFormatOption
            from docling.datamodel.pipeline_options import (
                PdfPipelineOptions,
                AcceleratorOptions,
                AcceleratorDevice,
            )



            opts = PdfPipelineOptions()
            device_choice = AcceleratorDevice.CUDA if torch.cuda.is_available() else AcceleratorDevice.CPU
            opts.accelerator_options = AcceleratorOptions(num_threads=4, device=device_choice)
            opts.do_table_structure = True
            _DOCLING_CONVERTER_INSTANCE = DocumentConverter(
                format_options={"pdf": PdfFormatOption(pipeline_options=opts)}
            )
            console.print(f"[bold green]✔[/bold green] IBM Docling v2 motoru hazır (Aygıt: [yellow]{device_choice.name}[/yellow])")
        except Exception as e:
            console.print(f"[dim yellow]Docling v2 başlatılamadı ({e}), standart hibrit OCR kullanılacak.[/dim yellow]")
            _DOCLING_CONVERTER_INSTANCE = False
    return _DOCLING_CONVERTER_INSTANCE if _DOCLING_CONVERTER_INSTANCE else None





def parse_pdf_with_docling(pdf_path: Path) -> Optional[str]:
    """IBM Docling v2 ile PDF'i gelişmiş tablo ve başlık yapısını koruyarak sayfa bazlı Markdown'a dönüştürür."""
    conv = get_docling_converter()
    if not conv:
        return None
    try:
        console.print(f"  [cyan]• Docling v2 (CUDA) ile ayrıştırılıyor: [bold]{pdf_path.name}[/bold]...[/cyan]")
        res = conv.convert(str(pdf_path), raises_on_error=False)
        if res and res.document:
            num_pages = res.document.num_pages()
            page_outputs = []
            for p in range(1, num_pages + 1):
                p_md = res.document.export_to_markdown(page_no=p)
                if p_md and len(p_md.strip()) > 0:
                    page_outputs.append(f"\n## --- Sayfa {p} (Docling v2 CUDA) ---\n{p_md}")



            if page_outputs:
                full_md = "\n".join(page_outputs)
                console.print(f"  [green]✔ Docling v2 başarıyla ayrıştırdı ({len(page_outputs)}/{num_pages} sayfa, {len(full_md)} karakter)[/green]")
                return full_md
    except Exception as e:
        console.print(f"  [dim yellow]Docling v2 ayrıştırma uyarısı ({e}), sayfa bazlı ayrıştırıcıya geçiliyor...[/dim yellow]")
    return None





# ==============================================================================
# Türkçe Kalite & Bozulma (Garbage) Skoru (Ö4 Düzeltmesi)
# ==============================================================================
COMMON_TR_STEMS = {
    "ve", "ile", "bir", "bu", "şu", "o", "icin", "için", "göre", "kadar",
    "olarak", "olan", "olur", "madde", "sözlesme", "sözleşme", "sartname", "şartname",
    "teknik", "idari", "idare", "yüklenici", "yuklenici", "tarih", "ek",
    "is", "iş", "isler", "işler", "yapim", "yapım", "insaatt", "inşaat",
    "bedel", "fiyat", "hakedis", "hakediş", "fark", "farki", "farkı",
    "süre", "sure", "kabul", "teslim", "rapor", "tutanak", "kontrol",
    "belediye", "belediyesi", "istanbul", "baskanlik", "başkanlık",
    "onay", "uygun", "karar", "hüküm", "hukum", "kanun", "kanunu",
    "yonetmelik", "yönetmelik", "teblig", "tebliğ", "kamu", "ihale", "sayili", "sayılı"
}





def detect_garbage_score(text: str) -> float:
    """
    OCR çıktısındaki bozulma ve harf çorbası oranını ölçer (0.0: Mükemmel, 1.0: Tamamen Bozuk).
    1. Yetersiz metin uzunluğu
    2. Aşırı tek harfli kelime / anlamsız sembol yoğunluğu
    3. Hukuki ve resmi Türkçe kök kelimelere isabet oranı
    """
    if not text or len(text.strip()) < 30:
        return 1.0



    lines = [line.strip() for line in text.splitlines() if len(line.strip()) > 3]
    if not lines:
        return 1.0



    words = re.findall(r"\b[a-zA-ZğüşıöçĞÜŞİÖÇ]+\b", text)
    if not words or len(words) < 5:
        return 1.0



    # 1. Tek harf oranı
    single_letters = [w for w in words if len(w) == 1]
    single_ratio = len(single_letters) / len(words)



    # 2. Özel karakter oranı
    special_chars = re.findall(r"[^a-zA-Z0-9ğüşıöçĞÜŞİÖÇ\s\.,;:–\-\(\)/%]", text)
    special_ratio = len(special_chars) / max(len(text), 1)



    # 3. Tanınan Türkçe kök oranı
    lower_words = [tr_lower(w) for w in words]
    known_count = sum(1 for w in lower_words if w in COMMON_TR_STEMS or any(w.startswith(stem) for stem in COMMON_TR_STEMS if len(stem) >= 4))
    match_ratio = known_count / len(words)



    # Temel ceza puanı
    penalty = 0.0
    if single_ratio > 0.25:
        penalty += 0.4
    if special_ratio > 0.15:
        penalty += 0.3
    if match_ratio < 0.05 and len(words) > 15:
        penalty += 0.5
    elif match_ratio < 0.10 and len(words) > 20:
        penalty += 0.25



    return min(1.0, max(0.0, penalty))





# ==============================================================================
# HTML Tablo -> Markdown Tablo Dönüştürücü
# ==============================================================================
def html_table_to_markdown(html_str: str) -> str:
    """HTML tablo stringini temiz Markdown tablosuna dönüştürür."""
    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html_str, "html.parser")
        tables = soup.find_all("table")
        if not tables:
            return ""
        md_tables = []
        for table in tables:
            rows = []
            for tr in table.find_all("tr"):
                cells = [td.get_text(" ", strip=True).replace("|", "/") for td in tr.find_all(["td", "th"])]
                if any(cells):
                    rows.append(cells)
            if not rows:
                continue
            max_cols = max(len(r) for r in rows)
            if max_cols <= 1:
                # Tek sütunlu sözde tabloları tablo formatına çevirme, düz metin yap
                flat_text = "\n".join([" ".join(r) for r in rows if any(r)])
                if flat_text:
                    md_tables.append(flat_text)
                continue



            for r in rows:
                while len(r) < max_cols:
                    r.append("")
            header = rows[0]
            md_table = ["| " + " | ".join(header) + " |"]
            md_table.append("| " + " | ".join(["---"] * max_cols) + " |")
            for row in rows[1:]:
                md_table.append("| " + " | ".join(row) + " |")
            md_tables.append("\n".join(md_table))
        return "\n\n".join(md_tables)
    except Exception:
        return ""





# ==============================================================================
# Sayfa Bazlı Ayrıştırıcılar (Ö3 & Ö5 Düzeltmesi)
# ==============================================================================
def parse_image_with_rapid_local(img_input: Any) -> str:
    """
    Yerel OCR & Tablo Motoru (RapidTable + RapidOCR).
    Modelleri singleton olarak kullanır. Tek sütunlu tekrarları önler.
    """
    import numpy as np
    import cv2



    if isinstance(img_input, bytes):
        nparr = np.frombuffer(img_input, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    elif isinstance(img_input, str):
        img = cv2.imread(img_input)
    elif isinstance(img_input, np.ndarray):
        img = img_input
    else:
        return ""



    if img is None:
        return ""



    output_blocks = []
    has_real_table = False



    # 1. Tablo Çıkarımı (RapidTable / SLANet)
    table_engine = get_rapid_table()
    if table_engine is not None:
        try:
            res = table_engine(img)
            if hasattr(res, "pred_htmls") and res.pred_htmls:
                for h in res.pred_htmls:
                    md_t = html_table_to_markdown(h)
                    if md_t.strip() and "|" in md_t:
                        output_blocks.append(f"\n[Tablo]:\n{md_t}\n")
                        has_real_table = True
        except Exception:
            pass



    # 2. Metin Blokları (RapidOCR / PP-OCRv6)
    # Eğer gerçek bir tablo başarıyla çıkarılmışsa, aynı metinleri tekrar alt alta dizmeyi engelle
    ocr_engine = get_rapid_ocr()
    if ocr_engine is not None:
        try:
            res = ocr_engine(img)
            ocr_lines = []
            if hasattr(res, "txts") and res.txts:
                ocr_lines = [t for t in res.txts if t and isinstance(t, str)]
            elif isinstance(res, (tuple, list)) and res and res[0]:
                ocr_lines = [item[1] for item in res[0] if item and len(item) > 1 and isinstance(item[1], str)]



            if ocr_lines and not has_real_table:
                output_blocks.append("\n".join(ocr_lines))
            elif ocr_lines and has_real_table:
                # Tablo haricinde kalan başlık vb. satırları ekle
                extra_lines = [l for l in ocr_lines if len(l) > 20 and l not in "\n".join(output_blocks)]
                if extra_lines:
                    output_blocks.append("\n".join(extra_lines))
        except Exception:
            pass



    return "\n".join(output_blocks).strip()





def parse_page_with_gemini_vision(image_bytes: bytes, page_num: int = 1) -> str:
    """
    3. Kademe: Gemini Multimodal Vision.
    Ö5 Düzeltmesi: Gevezelik etmeyen, doğrudan yapısal Markdown döndüren sıkı sistem talimatı.
    """
    if not GOOGLE_API_KEY:
        console.print("[red]GOOGLE_API_KEY tanımlı olmadığı için Gemini Vision kullanılamıyor![/red]")
        return ""



    from google import genai
    from google.genai import types



    try:
        client = genai.Client(api_key=GOOGLE_API_KEY, http_options={"timeout": 60})
    except Exception:
        client = genai.Client(api_key=GOOGLE_API_KEY)
    model_name = GOOGLE_MODEL_NAME or "gemini-2.5-flash"



    system_instruction = (
        "Sen teknik şartname, ihale mevzuatı ve resmi sözleşmeler için OCR motorusun.\n"
        "TALİMATLAR:\n"
        "1. Yalnızca görselde yer alan metni ve tabloları Markdown formatında döndür.\n"
        "2. Asla selamlama, özet, giriş veya 'Ben bir yapay zekayım / denetçiyim' gibi açıklamalar YAPMA.\n"
        "3. Tabloları temiz Markdown tablosu olarak oluştur (| Sütun 1 | Sütun 2 |).\n"
        "4. Resmi kaşe ve mühürleri '[KAŞE: ...]', imzaları '[İMZA]', el yazılarını '[EL YAZISI: ...]' olarak belirt.\n"
        "5. Metni harf atlamadan birebir orijinal dilde (Türkçe) aktar."
    )



    contents = [
        types.Part.from_bytes(data=image_bytes, mime_type="image/png"),
        system_instruction
    ]



    for m in [model_name, "gemini-3.8-flash", "gemini-3.5-flash-lite", "gemini-flash-lite-latest", "gemini-2.5-flash"]:
        try:
            resp = client.models.generate_content(model=m, contents=contents)
            text = (resp.text or "").strip()
            if text:
                return text
        except Exception as e:
            continue



    return ""





# ==============================================================================
# Çok Katmanlı Sayfa Bazlı Ayrıştırıcı & Önbellekleme (Akıllı Hibrit Triage)
# ==============================================================================
def extract_page_with_tables(page: fitz.Page) -> str:
    """Sayfadaki dijital metni ve PyMuPDF find_tables() ile tespit edilen dijital tabloları birleştirir."""
    try:
        tabs = page.find_tables()
        if not tabs.tables:
            return page.get_text("text").strip()



        table_mds = []
        for t in tabs.tables:
            df_rows = t.extract()
            if not df_rows or len(df_rows) < 2:
                continue
            header = df_rows[0]
            col_count = len(header)
            hdr_line = "| " + " | ".join(str(c or "").replace("\n", " ").strip() for c in header) + " |"
            sep_line = "| " + " | ".join(["---"] * col_count) + " |"
            body_lines = []
            for r in df_rows[1:]:
                r_padded = (r + [""] * col_count)[:col_count]
                body_lines.append("| " + " | ".join(str(c or "").replace("\n", " ").strip() for c in r_padded) + " |")
            table_mds.append("\n" + hdr_line + "\n" + sep_line + "\n" + "\n".join(body_lines) + "\n")



        if table_mds:
            table_rects = [fitz.Rect(t.bbox) for t in tabs.tables]
            blocks = page.get_text("blocks")
            non_table_text = []
            for b in blocks:
                if b[6] == 0:  # metin bloğu
                    b_rect = fitz.Rect(b[:4])
                    if not any(b_rect.intersects(tr) for tr in table_rects):
                        b_txt = b[4].strip()
                        if b_txt:
                            non_table_text.append(b_txt)
            clean_text = "\n\n".join(non_table_text).strip()
            if clean_text:
                return clean_text + "\n\n### [Sayfa Tabloları]:\n" + "\n".join(table_mds)
            return "\n".join(table_mds)
        return page.get_text("text").strip()
    except Exception:
        return page.get_text("text").strip()





def parse_any_document(file_path: Union[str, Path], use_cache: bool = True, max_gemini_calls: int = 5) -> str:
    """
    Akıllı Hibrit Triage ve Bütünlük Muhafızı Destekli Doküman Ayrıştırıcı:
    1. .pdf.html tuzağına karşı koruma: Varsa orijinal .pdf dosyasını otomatik devreye alır.
    2. Önbellek (.cache_ocr/<hash>.md) kontrolü.
    3. Düz metin / MD ise doğrudan okuma.
    4. PDF Dosyaları İçin Akıllı Hibrit Triage:
       - Rota 1 (Docling v2 CUDA): Yalnızca <= 30 sayfa küçük formlar/tutanaklar.
       - Rota 2 (Akıllı Hızlı Yol): >= %70 Dijital Metin (Şartnameler) -> PyMuPDF metin + dijital tablo.
       - Rota 3 (Yerel OCR Akışı): < %70 Dijital Metin (Taranmış Sözleşmeler/Şartnameler) ->
         150 DPI sayfa akışı + RapidOCR/RapidTable + Yalnızca aşırı bozuk sayfalarda cerrahi Gemini Vision.
    5. Doküman Bütünlüğü Doğrulaması: Beklenen sayfa sayısı ile çıkarılan sayfa sayısı uyuşmazsa hata fırlatır.
    """
    path = Path(file_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Dosya bulunamadı: {path}")



    # =========================================================================
    # 0. .pdf.html ve .docx.html Tuzağını Kırma (Orijinal Dosyayı Otomatik Bulma)
    # =========================================================================
    if path.name.lower().endswith((".pdf.html", ".docx.html")):
        base_name = path.name[:-5]
        search_dirs = [
            path.parent,
            path.parent / "hamdosyalar",
            path.parent / "ham_dosyalar",
            path.parent.parent / "hamdosyalar",
            path.parent.parent / "ham_dosyalar",
            Path(r"D:\mevzuatinceleme\data\2_proje_evraklari\kirazli_halkali_metro\hamdosyalar"),
            Path(r"D:\mevzuatinceleme\data\2_proje_evraklari\ikitelli_atakoy_metro\ham_dosyalar"),
            Path(r"D:\setuplar")
        ]
        
        real_doc = None
        for sdir in search_dirs:
            if not sdir.exists():
                continue
            cand = sdir / base_name
            if cand.exists():
                real_doc = cand
                break
            for f in sdir.glob("*.pdf"):
                if f.stem in path.stem or path.stem in f.stem:
                    real_doc = f
                    break
            if real_doc:
                break
                
        if real_doc and real_doc.exists():
            console.print(f"  [bold green]✔ Sahte .pdf.html tuzağı aşıldı! Orijinal dosya devreye alınıyor:[/bold green] [yellow]{real_doc.name}[/yellow]")
            return parse_any_document(real_doc, use_cache=use_cache, max_gemini_calls=max_gemini_calls)



    # Düz Metin
    if path.suffix.lower() in [".txt", ".md"]:
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()



    # Önbellek dizini
    cache_dir = path.parent / ".cache_ocr"
    cache_file = None
    if use_cache:
        try:
            cache_dir.mkdir(exist_ok=True)
            stat = path.stat()
            h_str = f"{path.name}_{stat.st_size}_{stat.st_mtime}"
            f_hash = hashlib.md5(h_str.encode()).hexdigest()
            cache_file = cache_dir / f"{path.stem}_{f_hash}.md"
            if cache_file.exists() and cache_file.stat().st_size > 50:
                console.print(f"  [dim green]✔ Önbellek kullanıldı: {cache_file.name}[/dim green]")
                return cache_file.read_text(encoding="utf-8")
        except Exception:
            pass



    console.print(f"[bold cyan]🔍 Evrak Ayrıştırılıyor:[/bold cyan] [yellow]{path.name}[/yellow]")
    parsed_pages = []



    # =========================================================================
    # 1. PDF Dosyaları (Akıllı Hibrit Triage & Bütünlük Muhafızı)
    # =========================================================================
    if path.suffix.lower() == ".pdf":
        doc = fitz.open(str(path))
        total_pages = len(doc)
        expected_pages = get_expected_page_count_from_name(path.name)
        
        if expected_pages and not ("-" in path.name and any(p in path.name for p in ["1-130", "131-236"])):
            if total_pages < int(expected_pages * 0.90):
                raise DocumentIntegrityError(
                    f"Eksik Evrak / Kesik Belge Hatası: '{path.name}' başlığında ~{expected_pages} sayfa belirtilmiş, ancak PDF içinde yalnızca {total_pages} sayfa bulundu (< %90)!"
                )
            elif abs(total_pages - expected_pages) > 5:
                console.print(f"  [yellow]⚠ Sayfa Sayısı Uyarısı: Başlıkta '{expected_pages}' belirtilmiş, PDF içinde {total_pages} sayfa var.[/yellow]")



        # Dijital metin yoğunluğu (8 örnek sayfa)
        sample_indices = [int(i * (total_pages - 1) / 7) for i in range(8)] if total_pages > 8 else list(range(total_pages))
        digital_sample_count = 0
        for s_idx in sample_indices:
            if len(doc[s_idx].get_text("text").strip()) > 100:
                digital_sample_count += 1
        digital_ratio = digital_sample_count / len(sample_indices) if sample_indices else 0.0



        # ROTA 1: Docling v2 CUDA (Yalnızca <= 30 sayfa)
        if total_pages <= 30 and digital_ratio < 0.70:
            console.print(f"  [dim cyan]• Triage Rotası: [bold]Docling v2 CUDA[/bold] ({total_pages} sayfa, Kısa Form & Tablo)[/dim cyan]")
            docling_md = parse_pdf_with_docling(path)
            if docling_md:
                full_output = f"# Kaynak: {path.name}\n\n{docling_md}"
                if cache_file is not None and len(full_output.strip()) > 100:
                    try:
                        cache_file.write_text(full_output, encoding="utf-8")
                    except Exception:
                        pass
                return full_output
            console.print("  [dim yellow]Docling v2 yetersiz kaldı, sayfa bazlı ayrıştırıcıya geçiliyor...[/dim yellow]")



        # ROTA 2: Dijital Metin Hızlı Yol (>= %70 Dijital Metin - Şartnameler)
        if digital_ratio >= 0.70:
            console.print(f"  [dim yellow]• Triage Rotası: [bold]Dijital Metin & Tablo Yolu (PyMuPDF)[/bold] ({total_pages} sayfa)[/dim yellow]")
            for page_idx in range(total_pages):
                try:
                    page = doc[page_idx]
                    page_text = page.get_text("text").strip()

                    if len(page_text) > 100:
                        p_content = extract_page_with_tables(page)
                        parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Dijital Metin & Tablo) ---\n{p_content}")
                    else:
                        pix = page.get_pixmap(dpi=150)
                        img_bytes = pix.tobytes("png")
                        local_res = parse_image_with_rapid_local(img_bytes)
                        parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Yerel OCR) ---\n{local_res}")
                except Exception as p_err:
                    console.print(f"    [yellow]⚠ Sayfa {page_idx + 1} ayrıştırma hatası ({p_err}), atlanıyor...[/yellow]")
                    parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Ayrıştırma Hatası) ---\n[Sayfa okunamadı: {p_err}]")



        # ROTA 3: Yerel OCR Akışı (< %70 Dijital Metin - Taranmış Büyük Şartnameler & Sözleşmeler)
        else:
            console.print(f"  [dim cyan]• Triage Rotası: [bold]Yerel Hızlı OCR Akışı (RapidOCR)[/bold] ({total_pages} sayfa, 150 DPI)[/dim cyan]")
            gemini_calls = 0
            for page_idx in range(total_pages):
                if (page_idx + 1) % 15 == 0 or page_idx == 0 or page_idx == total_pages - 1:
                    console.print(f"    [dim cyan]• İlerleme: Sayfa {page_idx + 1}/{total_pages} (%{((page_idx+1)/total_pages)*100:.1f})...[/dim cyan]")
                
                try:
                    page = doc[page_idx]
                    page_text = page.get_text("text").strip()
                
                    if len(page_text) > 150:
                        p_content = extract_page_with_tables(page)
                        parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Dijital Metin & Tablo) ---\n{p_content}")
                        continue



                    pix = page.get_pixmap(dpi=150)
                    img_bytes = pix.tobytes("png")



                    local_res = parse_image_with_rapid_local(img_bytes)
                    g_score = detect_garbage_score(local_res)



                    # Yerel OCR yeterli metin bulduysa veya bozulma skoru kabul edilebilir ise doğrudan al
                    if local_res and g_score <= 0.35 and len(local_res.strip()) >= 15:
                        parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Yerel OCR) ---\n{local_res}")
                    else:
                        if gemini_calls < max_gemini_calls:
                            console.print(f"    [dim magenta]• Sayfa {page_idx + 1} bozuk (%{g_score*100:.1f}) -> Gemini Vision ({gemini_calls + 1}/{max_gemini_calls})...[/dim magenta]")
                            v_res = parse_page_with_gemini_vision(img_bytes, page_idx + 1)
                            if v_res:
                                parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Gemini Vision) ---\n{v_res}")
                                gemini_calls += 1
                                time.sleep(0.5)
                            elif local_res:
                                parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Yerel OCR - Kısmi) ---\n{local_res}")
                            else:
                                parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Görsel / Çizim / Boş Sayfa) ---\n[Metin bulunamadı / Çizim sayfası]")
                        elif local_res:
                            parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Yerel OCR - Kısmi) ---\n{local_res}")
                        else:
                            parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Görsel / Çizim / Boş Sayfa) ---\n[Metin bulunamadı / Çizim sayfası]")



                except Exception as p_err:
                    console.print(f"    [yellow]⚠ Sayfa {page_idx + 1} OCR hatası ({p_err}), atlanıyor...[/yellow]")
                    parsed_pages.append(f"\n## --- Sayfa {page_idx + 1} (Ayrıştırma Hatası) ---\n[Sayfa okunamadı: {p_err}]")

        # BÜTÜNLÜK DOĞRULAMASI: Boş sayfa veya çizim sayfaları harici gerçek metin bütünlüğü kontrolü
        meaningful_pages = [
            p for p in parsed_pages
            if p and not any(err in p for err in ["[Metin bulunamadı", "[Tarama Hatası", "[Boş Sayfa"])
            and len(p.split("\n", 2)[-1].strip()) >= 30
        ]
        if total_pages > 5 and len(meaningful_pages) < max(1, int(total_pages * 0.20)):
            raise DocumentIntegrityError(
                f"Kritik Bütünlük Hatası: '{path.name}' toplam {total_pages} sayfa olmasına rağmen yalnızca {len(meaningful_pages)} sayfadan okunabilir metin elde edilebildi (< %20 anlamlı içerik)!"
            )
        console.print(f"  [bold green]✔ Bütünlük Doğrulandı:[/bold green] {len(meaningful_pages)}/{total_pages} sayfa metin içeriyor ({len(parsed_pages)} sayfa işlendi).")



    # =========================================================================
    # 2. HTML (.docx.html veya .pdf.html)
    # =========================================================================
    elif path.suffix.lower() == ".html":
        from bs4 import BeautifulSoup
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            soup = BeautifulSoup(f.read(), "html.parser")



        # Tablolar
        for t in soup.find_all("table"):
            md_t = html_table_to_markdown(str(t))
            if md_t:
                t.replace_with("\n\n" + md_t + "\n\n")



        # Dijital Metin Katmanı
        direct_text = soup.get_text("\n", strip=True)
        if len(direct_text) > 150:
            parsed_pages.append(f"\n## --- Dijital İçerik ---\n{direct_text}")



        # Gömülü Görseller
        images = soup.find_all("img")
        expected_pages = get_expected_page_count_from_name(path.name)
        if expected_pages and expected_pages > 15 and len(images) < (expected_pages / 2):
            raise DocumentIntegrityError(
                f"Kritik Bütünlük Hatası: '{path.name}' dosyasında beklenen sayfa sayısı ~{expected_pages}, "
                f"ancak HTML içinde yalnızca {len(images)} sayfa görseli bulundu! Bu dosya kesilmiş bir ara çıktıdır."
            )



        for idx, img in enumerate(images, 1):
            src = img.get("src", "")
            if "base64," in src:
                b64 = src.split("base64,")[1]
                img_bytes = base64.b64decode(b64)
                
                local_res = parse_image_with_rapid_local(img_bytes)
                g_score = detect_garbage_score(local_res)



                if local_res and g_score <= 0.20:
                    parsed_pages.append(f"\n## --- Sayfa {idx} (HTML Sayfa Görseli - Yerel OCR) ---\n{local_res}")
                else:
                    v_res = parse_page_with_gemini_vision(img_bytes, idx)
                    if v_res:
                        parsed_pages.append(f"\n## --- Sayfa {idx} (HTML Sayfa Görseli - Gemini Vision) ---\n{v_res}")
                    elif local_res:
                        parsed_pages.append(f"\n## --- Sayfa {idx} (HTML Sayfa Görseli - Kısmi OCR) ---\n{local_res}")



    # =========================================================================
    # 3. Word (.docx ve EKAP HTML tabanlı .doc) Dosyaları
    # =========================================================================
    elif path.suffix.lower() in [".doc", ".docx"]:
        raw_bytes = path.read_bytes()
        if b"<html" in raw_bytes[:1000].lower():
            from bs4 import BeautifulSoup
            try:
                text_decoded = raw_bytes.decode("utf-8")
                if "\ufffd" in text_decoded[:500]:
                    text_decoded = raw_bytes.decode("cp1254", errors="replace")
            except UnicodeDecodeError:
                text_decoded = raw_bytes.decode("cp1254", errors="replace")
            soup = BeautifulSoup(text_decoded, "html.parser")
            for t in soup.find_all("table"):
                md_t = html_table_to_markdown(str(t))
                if md_t:
                    t.replace_with("\n\n" + md_t + "\n\n")
            direct_text = soup.get_text("\n", strip=True)
            if direct_text:
                parsed_pages.append(f"\n## --- Dijital Sözleşme / EKAP Belgesi ---\n{direct_text}")
        else:
            try:
                import docx as py_docx
                d_obj = py_docx.Document(str(path))
                paras = [p.text.strip() for p in d_obj.paragraphs if p.text.strip()]
                if paras:
                    parsed_pages.append("\n## --- Dijital Word Belgesi ---\n" + "\n\n".join(paras))
            except Exception as e:
                console.print(f"  [yellow]⚠ Word ayrıştırma uyarısı ({path.name}): {e}[/yellow]")

    # =========================================================================
    # 4. Bağımsız Görsel Dosyaları
    # =========================================================================
    elif path.suffix.lower() in SUPPORTED_IMAGE_EXTENSIONS:
        img_bytes = path.read_bytes()
        local_res = parse_image_with_rapid_local(img_bytes)
        g_score = detect_garbage_score(local_res)
        if local_res and g_score <= 0.15:
            parsed_pages.append(local_res)
        else:
            v_res = parse_page_with_gemini_vision(img_bytes, 1)
            parsed_pages.append(v_res or local_res)



    full_output = f"# Kaynak: {path.name}\n\n" + "\n\n".join(parsed_pages)



    # Önbelleğe yaz
    if cache_file is not None and len(full_output.strip()) > 100:
        try:
            cache_file.write_text(full_output, encoding="utf-8")
        except Exception:
            pass



    return full_output

