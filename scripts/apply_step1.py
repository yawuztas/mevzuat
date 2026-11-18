import os
import sys
import re
from pathlib import Path

# 1. Update utils/document_parser.py
dp_path = Path(r"d:\mevzuatinceleme\utils\document_parser.py")
content = dp_path.read_text(encoding="utf-8")
norm = content.replace("\r\n", "\n")

# Replace get_expected_page_count_from_name
old_func_pattern = re.compile(r"def get_expected_page_count_from_name\(filename: str\):.*?(?=\n# =|\ndef )", re.DOTALL)
new_func = '''def get_expected_page_count_from_name(filename: str):
    """
    Dosya adından sayfa sayısı iddiasını çıkarır.
    Örn: '...-604 SAYFA.pdf' -> 604, 'foo SAYFA 10.pdf' -> 10, '...-236 SAYFA-1-130' -> 130.
    İhale kayıt numaralarını ('2015-78345') veya parça kodlarını sayfa aralığı sanmaz.
    """
    # 1. Açık sayfa aralığı (Range): SAYFA-1-130, Sayfa_1_330, 1-130 SAYFA
    range_m = re.search(r"(?:sayfa|sf)[_\\s-]*(\\d+)\\s*[-_]\\s*(\\d+)", filename, re.IGNORECASE)
    if not range_m:
        range_m = re.search(r"(\\d+)\\s*[-_]\\s*(\\d+)\\s*(?:sayfa|sf)", filename, re.IGNORECASE)

    if range_m:
        start_p, end_p = int(range_m.group(1)), int(range_m.group(2))
        if 0 < start_p < end_p and (end_p - start_p + 1) <= 2000 and end_p <= 3000:
            return end_p - start_p + 1

    # 2. Sayı ÖNDE: '10 SAYFA', 'foo-10 SAYFA.pdf', '91_sf'
    m1 = re.search(r"(?<!\\d)(\\d+)\\s*[-_]?(?:sayfa|sf)\\b", filename, re.IGNORECASE)
    if m1:
        val = int(m1.group(1))
        if 0 < val <= 3000:
            return val

    # 3. Sayı ARKADA: 'foo SAYFA 10.pdf', 'foo SAYFA_10.pdf', 'foo sf 10.pdf'
    m2 = re.search(r"\\b(?:sayfa|sf)[_\\s-]+(\\d+)(?!\\d)", filename, re.IGNORECASE)
    if m2:
        val = int(m2.group(1))
        if 0 < val <= 3000:
            return val

    return None

'''

norm = old_func_pattern.sub(lambda m: new_func, norm, count=1)

# Replace get_rapid_ocr
old_ocr_pattern = re.compile(r"def get_rapid_ocr\(\):.*?(?=\ndef get_rapid_table)", re.DOTALL)
new_ocr = '''def get_rapid_ocr():
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


'''

norm = old_ocr_pattern.sub(lambda m: new_ocr, norm, count=1)

dp_path.write_text(norm.replace("\n", "\r\n"), encoding="utf-8")
print("utils/document_parser.py updated successfully!")

# Invalidate bad cache files
deleted_caches = 0
for f in Path("data").rglob(".cache_ocr/*.md"):
    try:
        txt = f.read_text(encoding="utf-8")
        if "## --- Sayfa" not in txt:
            f.unlink()
            deleted_caches += 1
    except Exception:
        pass

print(f"Deleted {deleted_caches} obsolete cache files without page markers.")
