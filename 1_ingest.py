import json
import hashlib
import os
import re
import sys
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
# Windows konsolunda Türkçe karakter ve Unicode desteği
if sys.platform.startswith("win"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
console = Console(legacy_windows=False)
from utils.config import (
    GENEL_MEVZUAT_DIR,
    PROJE_EVRAKLARI_DIR,
    VECTOR_DB_DIR,
    EMBEDDING_MODEL_NAME,
)
from utils.retriever import (
    get_chroma_client,
    get_chroma_collection,
    get_embedding_model,
    get_device,
)
from utils.document_parser import parse_any_document
from utils.config import DATA_DIR
from utils.text_tr import tr_lower, ascii_fold
from utils.standards import extract_standard_refs
PAGE_PATTERN = re.compile(
    r"(?:##\s*---\s*Sayfa\s+(\d+)|---\s*\[SAYFA\s+(\d+)\]|###\s*\[Sayfa\s*(?:/\s*[^\]]+)?\s*(\d+)|<!--\s*Sayfa\s+(\d+)\s*-->)",
    re.IGNORECASE,
)
SUBSYSTEM_TO_DOMAIN_MAP = {
    # Elektromekanik
    "sinyalizasyon_cbtc": "elektromekanik",
    "cer_gucu_ve_elektrifikasyon": "elektromekanik",
    "zayif_akim_ve_scada": "elektromekanik",
    "havalandirma_ve_yangin_tvs": "elektromekanik",
    "asansor_ve_yuruyen_merdiven": "elektromekanik",
    "genel_rams_ve_emniyet": "elektromekanik",
    "genel_elektromekanik": "elektromekanik",
    # İnşaat
    "tunel_ve_kazilar": "insaat",
    "demiryolu_ustyapi_ve_ray": "insaat",
    "istasyon_kaba_ince": "insaat",
    "genel_insaat": "insaat",
    # İdari / Mevzuat
    "sure_uzatimi_ve_mucbir_sebep": "idari",
    "hakedis_ve_fiyat_farki": "idari",
    "yeni_birim_fiyat_ve_analiz": "idari",
    "kabul_muayene_ve_teminat": "idari",
    "tasaron_ve_alt_yuklenici": "idari",
    "ceza_ve_fesih_hukuk": "idari",
    "sozlesme_ve_idari": "idari",
}
def is_ignored_path(fp: Path) -> bool:
    """Geçici, ham, önbellek ve tahkim dava dosyası klasörlerini filtreler (dosya adlarını etkilemez)."""
    ignored = {".cache", "ham_dosyalar", "hamdosyalar", "arsiv", "_arsiv", "tahkim"}
    try:
        dir_parts = fp.resolve().relative_to(DATA_DIR.resolve()).parent.parts
    except Exception:
        dir_parts = fp.parent.parts
    return any(any(pattern in ascii_fold(part) for pattern in ignored) for part in dir_parts)
def extract_page_number_from_text(text: str) -> Optional[int]:
    """Metin içindeki sayfa başlığı işaretleyicisini tespit eder."""
    m = PAGE_PATTERN.search(text)
    if m:
        for g in m.groups():
            if g is not None:
                try:
                    return int(g)
                except ValueError:
                    pass
    return None
FOLDER_TO_SUBSYSTEM_MAP = {
    "sinyalizasyon_ve_cbtc": "sinyalizasyon_cbtc",
    "cer_gucu_ve_elektrifikasyon": "cer_gucu_ve_elektrifikasyon",
    "zayif_akim_ve_scada": "zayif_akim_ve_scada",
    "yangin_ve_havalandirma": "havalandirma_ve_yangin_tvs",
    "asansor_ve_yuruyen_merdiven": "asansor_ve_yuruyen_merdiven",
    "demiryolu_ustyapi_ve_ray": "demiryolu_ustyapi_ve_ray",
}


def detect_procurement_type_from_path(file_path: Path, project_id: str = "global") -> str:
    """
    Dokümanın veya projenin ihale/sözleşme türünü belirler:
    - 'yapim': Yapım işleri (YİGŞ, yapım yönetmelikleri ve yapım projeleri)
    - 'danismanlik': Danışmanlık / Müşavirlik / Kontrollük hizmet işleri
    - 'ortak': Tüm ihale türlerinde geçerli ortak mevzuat, standart ve formlar (4734, 4735, EN/IEC/NFPA standartları)
    """
    if project_id and project_id != "global":
        pid_clean = ascii_fold(project_id)
        if any(k in pid_clean for k in ["musavir", "danisman", "kontrolluk"]):
            return "danismanlik"
        return "yapim"

    try:
        rel = file_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        rel = file_path
    parts = [ascii_fold(p) for p in rel.parts]
    joined_parts = "/".join(parts)

    if any(k in joined_parts for k in ["danismanlik_ve_musavirlik", "danismanlik", "musavirlik"]):
        return "danismanlik"
    if any(k in joined_parts for k in ["yapim_isleri", "yapim_islerinde", "yonetmelikler_ve_yigs"]):
        return "yapim"
    return "ortak"


def detect_folder_subsystem(file_path: Path) -> Optional[str]:
    """Klasör yapısından veya disiplin bazlı teknik şartname dosya adından doğrudan alt sistem (disiplin) etiketi çıkarır."""
    try:
        rel = file_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        rel = file_path
    parts = [ascii_fold(p) for p in rel.parts]
    for p in parts:
        if p in FOLDER_TO_SUBSYSTEM_MAP:
            return FOLDER_TO_SUBSYSTEM_MAP[p]
        if "3_sinyalizasyon" in p or p == "sinyalizasyon" or "sinyalizasyon_test" in p:
            return "sinyalizasyon_cbtc"

    name = ascii_fold(file_path.stem)
    if any(k in name for k in ["guc temini", "guc_temini", "cer gucu", "cer_gucu", "elektrifikasyon", "trafo merkezi"]):
        return "cer_gucu_ve_elektrifikasyon"
    if "sinyalizasyon" in name:
        return "sinyalizasyon_cbtc"
    if any(k in name for k in ["haberlesme", "scada", "zayif akim", "zayif_akim", "telekom"]):
        return "zayif_akim_ve_scada"
    if any(k in name for k in ["cevresel kontrol", "cevresel_kontrol", "yardimci tesis", "yardimci_tesis", "borulama", "sihhi tesisat", "mekanik tesisat", "havalandirma", "yangin", "iklimlendirme", "sprinkler"]):
        return "havalandirma_ve_yangin_tvs"
    if any(k in name for k in ["yuruyen merdiven", "yuruyen_merdiven", "dusey tasima", "dusey_tasima", "asansor"]):
        return "asansor_ve_yuruyen_merdiven"
    if any(k in name for k in ["ustyapi", "ray isleri", "ray_isleri", "demiryolu ray"]):
        return "demiryolu_ustyapi_ve_ray"
    if any(k in name for k in ["yeterlilik", "sistem muhendisligi", "rams"]):
        return "genel_rams_ve_emniyet"
    if "is programi" in name or "is_programi" in name:
        return "sure_uzatimi_ve_mucbir_sebep"
    return None


def detect_domain_from_path(file_path: Path) -> str:
    """
    Dosyanın ana domainini data/ klasörüne göreli yoldan belirler.
    Domainler: mevzuat | idari | elektromekanik | insaat | karma
    """
    try:
        rel = file_path.resolve().relative_to(DATA_DIR.resolve())
    except ValueError:
        rel = Path(file_path.name)
    parts = [ascii_fold(p) for p in rel.parts]
    name = ascii_fold(file_path.stem)
    # 1. Genel havuz: alt klasör adı belirleyicidir
    if parts and parts[0].startswith("1_genel"):
        sub = parts[1] if len(parts) > 2 else ""
        sub_child = parts[2] if len(parts) > 3 else ""
        if sub in ("1_kanunlar", "kanunlar", "2_sozlesme_ve_genel_sartnameler", "yonetmelikler_ve_yigs", "3_tebligler_ve_kararnameler", "tebligler_ve_esaslar"):
            return "mevzuat"
        if sub in ("5_standart_formlar", "standart_formlar"):
            return "idari"
        if sub in ("4_standart_normlar", "standart_normlar"):
            if sub_child in ("insaat_ve_geoteknik", "demiryolu_ustyapi_ve_ray"):
                return "insaat"
            if sub_child == "genel_rayli_sistemler":
                return "karma"
            if sub_child in FOLDER_TO_SUBSYSTEM_MAP:
                return SUBSYSTEM_TO_DOMAIN_MAP.get(FOLDER_TO_SUBSYSTEM_MAP[sub_child], "elektromekanik")
            return "insaat" if any(k in name for k in ["insaat", "beton", "tunel"]) else "elektromekanik"
        return "mevzuat"
    # 2. Proje evrakları: 5 Sütunlu Kategori Klasörü + Dosya Adı
    category = parts[2] if len(parts) > 3 else ""
    sub_cat = parts[3] if len(parts) > 4 else ""
    if any(k in category for k in ["1_sozlesme", "2_idari_sartname", "4_birim_fiyat", "5_zeyilname", "sozlesme", "idari"]):
        return "idari"
    if "bim" in category or "bim" in sub_cat:
        return "insaat"
    if "sinyal" in category or "sinyal" in sub_cat:
        return "elektromekanik"
    # Master / Genel / Ortak teknik şartnameler çoklu disiplin içerir: karma
    if any(k in name for k in ["tam_teknik", "genel_ortak", "ortak_teknik", "00_ortak_teknik", "teknik_sartname_kisim"]):
        return "karma"
    elektro_kw = ["elektro", "mekanik", "sinyal", "cbtc", "guc temini", "guc_temini", "cer gucu",
                  "cer_gucu", "haberlesme", "havalandirma", "iklimlendirme", "yangin", "borulama",
                  "yardimci tesis", "yardimci_tesis", "asansor", "yuruyen", "dusey tasima",
                  "dusey_tasima", "scada", "isa", "atc", "yeterlilik", "rams"]
    insaat_kw = ["insaat", "ince is", "ince_is", "kaba", "guzergah", "yapi bilgi", "yapi_bilgi",
                 "statik", "mimari", "tunel", "zemin", "ray", "ustyapi"]
    if any(k in name for k in elektro_kw):
        return "elektromekanik"
    if any(k in name for k in insaat_kw):
        return "insaat"
    if any(k in name for k in ["sozlesme", "birim fiyat", "birim_fiyat", "idari", "zeyilname", "is programi", "is_programi", "analiz formu"]):
        return "idari"
    if "teknik" in category or "teknik" in sub_cat or "teknik" in name or "sartname" in name:
        return "karma"
    return "idari"
SUBSYSTEM_KEYWORDS: Dict[str, List[str]] = {
    "sure_uzatimi_ve_mucbir_sebep": [
        "süre uzatım", "mücbir sebep", "yer teslimi", "iş programı", "kritik yol", "cpm",
        "gecikilen süre", "madde 29", "madde 10", "1140 gün", "ara termin", "hava şartları",
        "süre talebi", "ek süre", "işin süresi", "zaman uzatımı"
    ],
    "hakedis_ve_fiyat_farki": [
        "hakediş", "fiyat farkı", "tüik", "yi-üfe", "endeks", "b katsayısı",
        "geçici 6", "geçici 5", "5546", "2013/5217", "2013/5215", "avans mahsubu",
        "yeşil defter", "metraj", "hakediş raporu", "kesinti", "ihzarat"
    ],
    "yeni_birim_fiyat_ve_analiz": [
        "yeni birim fiyat", "ybf", "madde 22", "revize birim fiyat", "%25 kâr",
        "rayiç", "analiz formatı", "piyasa fiyat araştırması", "sıralı iş kalemi",
        "özel poz", "yeni poz", "analiz girdisi"
    ],
    "kabul_muayene_ve_teminat": [
        "geçici kabul", "kesin kabul", "muayene ve kabul", "kabul noksan",
        "%5 teminat", "%6 teminat", "teminat süresi", "sgk ilişiksizlik",
        "trial running", "deneme işletme", "kabul heyeti", "teminat mektubu"
    ],
    "tasaron_ve_alt_yuklenici": [
        "alt yüklenici", "taşeron", "madde 62", "müteselsil", "devir yasağı",
        "alt yüklenici onayı", "taşeron sözleşmesi"
    ],
    "ceza_ve_fesih_hukuk": [
        "gecikme ceza", "günlük ceza", "on binde", "fesih", "ihtar",
        "teminatın gelir kaydı", "madde 20", "sözleşmenin feshi", "cezai şart"
    ],
    "sinyalizasyon_cbtc": [
        "sinyalizasyon", "cbtc", "atc", "atp", "ato", "ats", "ixl", "anklaşman",
        "baliz", "aks sayıcı", "en 50128", "en 50129", "sil 4", "ieee 1474",
        "goa 4", "uto", "alstom", "hassas durma", "headway", "tren kontrol"
    ],
    "cer_gucu_ve_elektrifikasyon": [
        "cer gücü", "elektrifikasyon", "750v", "1500v", "3. ray", "third rail",
        "kataner", "trafo", "gis", "redresör", "stray current", "kaçak akım",
        "en 50122", "en 50163", "topraklama", "ovpd", "cer trafo", "aydınlatma", "jeneratör", "ups"
    ],
    "zayif_akim_ve_scada": [
        "scada", "plc", "rtu", "tetra", "telsiz", "cctv", "kamera", "yangın algılama",
        "en 54", "sesli anons", "anons sistemi", "pa/pas", "yolcu anons",
        "yolcu bilgilendirme", "pis ekranı", "peron ayırıcı kapı", "psd",
        "fiber optik", "transmisyon", "geçiş kontrol", "kartlı geçiş"
    ],
    "havalandirma_ve_yangin_tvs": [
        "havalandırma", "tvs", "jet fan", "şaft fan", "duman tahliye", "damper",
        "nfpa 130", "en 12101", "f250", "f300", "sprinkler", "hidrant",
        "nfpa 13", "nfpa 14", "novec 1230", "fm-200", "drenaj", "yangın pompası",
        "borulama", "sıhhi tesisat", "hidrofor", "chiller", "iklimlendirme", "vrf"
    ],
    "asansor_ve_yuruyen_merdiven": [
        "yürüyen merdiven", "yürüyen bant", "asansör", "en 115", "en 81",
        "heavy duty", "itfaiyeci asansör", "manlift", "kaldırma platformu",
        "engelli asansörü", "düşey taşıma"
    ],
    "tunel_ve_kazilar": [
        "tünel", "tbm", "natm", "segment", "püskürtme beton", "shotcrete",
        "kaya bulon", "sürme kovan", "pipe umbrella", "enjeksiyon", "grout",
        "kazı", "aç-kapa tünel"
    ],
    "demiryolu_ustyapi_ve_ray": [
        "demiryolu rayı", "ray hattı", "ray montajı", "ray döşeme", "ray kaynağı",
        "üstyapı ray", "60 e1", "uic 60", "r260", "r350ht", "makas", "balastsız",
        "slab track", "ray pedi", "mass-spring", "alüminotermit", "balast"
    ],
    "istasyon_kaba_ince": [
        "istasyon yapısı", "aç-kapa istasyon", "diyafram duvar", "fore kazık",
        "grobeton", "donatı çeliği", "granit kaplama", "asma tavan", "a1 yanmazlık",
        "kalıp işleri", "betonarme", "mimari bitirme", "bim", "yapı bilgi modellemesi"
    ],
    "genel_rams_ve_emniyet": [
        "rams", "en 50126", "hazard log", "tehlike kütüğü", "safety case",
        "isa raporu", "bağımsız emniyet", "safety assessor", "italcertifer",
        "v&v", "emniyet yönetimi"
    ],
    "sozlesme_ve_idari": [
        "sözleşme bedeli", "öncelik sıralaması", "ihale kayıt no", "yüklenici",
        "idare", "taraflar", "tanımlar", "tebligat", "euro", "avrupa yakası",
        "işin tanımı", "özel şartlar", "danışman", "müşavir", "kilit personel"
    ],
}

_COMPILED_SUBSYSTEM_PATTERNS: Dict[str, List[re.Pattern]] = {
    sub: [re.compile(r"(?<!\w)" + re.escape(tr_lower(kw)) + r"(?!\w)") for kw in kws]
    for sub, kws in SUBSYSTEM_KEYWORDS.items()
}


def infer_document_dominant_subsystem(
    markdown_text: str,
    domain: str = "karma",
    folder_subsystem: Optional[str] = None,
) -> Optional[str]:
    """
    Dosya adına bağımlı kalmadan tüm belge metninden baskın mühendislik/idari
    disiplini çıkarır (yeni yüklenen projelerde dosya adı keyfi olsa bile çalışır).
    Yalnızca tek bir disiplin belirgin biçimde baskınsa değer döndürür; çok
    disiplinli master şartnamelerde None döndürüp kararı parça içeriğine bırakır.
    """
    if folder_subsystem:
        return folder_subsystem
    if domain in ("mevzuat", "idari"):
        return None
    sample_lower = tr_lower(markdown_text[:120000])
    counts: Dict[str, int] = {}
    for sub, pats in _COMPILED_SUBSYSTEM_PATTERNS.items():
        if sub == "sozlesme_ve_idari":
            continue
        total = 0
        for pat in pats:
            hits = len(pat.findall(sample_lower))
            if hits:
                total += min(hits, 8)
        counts[sub] = total
    ranked = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    if not ranked or ranked[0][1] < 4:
        return None
    top_sub, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    if top_score >= 2 * max(second_score, 1):
        return top_sub
    return None


def classify_chunk_metadata(
    text: str,
    title: str,
    filename: str,
    domain: str,
    folder_subsystem: Optional[str] = None,
    rel_path: str = "",
    doc_dominant_subsystem: Optional[str] = None,
) -> Dict[str, Any]:
    """Her bir chunk için doküman türünü, alt sistemini (subsystem), doğru domainini ve konu etiketlerini çıkarır."""
    full_text_lower = tr_lower(text + " " + title + " " + filename)
    title_lower = tr_lower(title)
    fn_lower = ascii_fold(filename)
    rel_lower = ascii_fold(rel_path)
    # 1. Doküman Türü (doc_type) - 5 Sütunlu Proje Hiyerarşisi + Genel Mevzuat
    if "5_zeyilname" in rel_lower or "zeyilname" in fn_lower:
        doc_type = "zeyilname_ve_aciklama"
    elif "4_birim_fiyat" in rel_lower or "birim_fiyat" in fn_lower or "birim fiyat" in fn_lower or "analiz formu" in fn_lower:
        doc_type = "birim_fiyat_tarifi"
    elif "2_idari_sartname" in rel_lower or "idari_sartname" in fn_lower or "idari sartname" in fn_lower:
        doc_type = "idari_sartname"
    elif "4_standart_normlar" in rel_lower or "standart_normlar" in rel_lower:
        doc_type = "standart_norm_katalogu"
    elif "1_genel_mevzuat" in rel_lower:
        if any(k in fn_lower for k in ["gecici", "kararname", "teblig", "fiyat_farki_esaslari", "5203", "5546", "8089", "5217", "5215", "5216"]):
            doc_type = "teblig_ve_kararname"
        elif "1_kanunlar" in rel_lower or any(k in fn_lower for k in ["kanun", "4734", "4735_kamu", "4686", "6098", "6100", "5018", "6085", "6331", "4857", "2872"]):
            doc_type = "kanun"
        elif "5_standart_formlar" in rel_lower or "form" in fn_lower:
            doc_type = "standart_form_sablonu"
        elif any(k in fn_lower for k in ["yigs", "yonetmeli", "genel_sartname", "tip_sozlesme", "muayene", "basvuru", "danismanlik_hizmet_isleri", "tbdy", "deprem", "yangin"]):
            doc_type = "yonetmelik"
        elif any(k in fn_lower for k in ["katalog", "rehber", "standart"]):
            doc_type = "standart_norm_katalogu"
        else:
            doc_type = "genel_referans"
    elif "1_sozlesme" in rel_lower or ("sozlesme" in fn_lower and "genel_sartname" not in fn_lower):
        doc_type = "sozlesme"
    elif "3_teknik_sartnameler" in rel_lower or "2_teknik_sartnameler" in rel_lower:
        doc_type = "teknik_sartname"
    elif any(k in fn_lower for k in ["4734", "4735_kamu_ihale"]):
        doc_type = "kanun"
    elif any(k in fn_lower for k in ["yigs", "yonetmeli", "danismanlik_hizmet_isleri"]):
        doc_type = "yonetmelik"
    elif any(k in fn_lower for k in ["teblig", "kararname", "fiyat_farki_esaslari", "gecici"]):
        doc_type = "teblig_ve_kararname"
    elif any(k in fn_lower for k in ["katalog", "rehber", "standart"]):
        doc_type = "standart_norm_katalogu"
    elif "sartname" in fn_lower:
        doc_type = "teknik_sartname"
    elif "form" in fn_lower:
        doc_type = "standart_form_sablonu"
    else:
        doc_type = "genel_referans"

    # 2. Alt Sistem (subsystem) Ağırlıklandırması (Proje-bağımsız: klasör/dosya + belge baskınlığı + parça metni)
    subsystem_scores: Dict[str, int] = {k: 0 for k in SUBSYSTEM_KEYWORDS}
    if folder_subsystem and folder_subsystem in subsystem_scores:
        subsystem_scores[folder_subsystem] += 6
    elif doc_dominant_subsystem and doc_dominant_subsystem in subsystem_scores:
        subsystem_scores[doc_dominant_subsystem] += 4

    for sub, pats in _COMPILED_SUBSYSTEM_PATTERNS.items():
        for pat in pats:
            if pat.search(full_text_lower):
                subsystem_scores[sub] += 3 if pat.search(title_lower) else 1

    best_subsystem = max(subsystem_scores, key=subsystem_scores.get)
    if subsystem_scores[best_subsystem] == 0:
        if folder_subsystem:
            best_subsystem = folder_subsystem
        elif doc_dominant_subsystem:
            best_subsystem = doc_dominant_subsystem
        elif domain in ["mevzuat", "idari"]:
            best_subsystem = "sozlesme_ve_idari"
        elif domain == "elektromekanik":
            best_subsystem = "genel_elektromekanik"
        elif domain == "insaat":
            best_subsystem = "genel_insaat"
        else:
            best_subsystem = "sozlesme_ve_idari"
    # Chunk domain çözümü (Karma/master şartnamelerde chunk içeriği belirleyicidir)
    if domain == "karma":
        chunk_domain = SUBSYSTEM_TO_DOMAIN_MAP.get(best_subsystem, "elektromekanik")
    else:
        chunk_domain = domain
    # 3. Konu Başlıkları ve Standartlar (topics)
    standards_found = re.findall(r'(?:EN|TS\s*EN|IEC|ISO|NFPA|IEEE|ETSI|UIC|BS|DIN)\s*\d+[-–\d]*', text, re.IGNORECASE)
    clauses_found = re.findall(r'(?:Madde\s+\d+|Geçici\s+Madde\s+\d+|Poz\s+\d+[\.\d]*)', text, re.IGNORECASE)
    unique_topics = set()
    for s in standards_found[:5]:
        unique_topics.add(s.upper().strip())
    for c in clauses_found[:5]:
        unique_topics.add(c.strip())
    key_tags = ["SIL 4", "GoA 4", "F250", "F300", "B2ca", "1140 gün", "%6 teminat", "%25 kâr", "Euro", "YİGŞ"]
    for kt in key_tags:
        if kt.lower() in full_text_lower:
            unique_topics.add(kt)
    topics_str = ", ".join(sorted(list(unique_topics))) if unique_topics else "Genel Hükümler"
    # 4. Standart Kodu Kanonikleştirme (Adım 2 — utils/standards.py)
    std_refs = extract_standard_refs(text + " " + title)
    standard_codes = "|".join(r["canonical"] for r in std_refs)
    return {
        "doc_type": doc_type,
        "subsystem": best_subsystem,
        "domain": chunk_domain,
        "topics": topics_str,
        "standard_codes": standard_codes,
        "doc_role": "normative_rule",
    }
def _split_section_units(cleaned: str, max_chunk_size: int) -> List[str]:
    """Uzun bölümleri önce paragraf (\n\n), hâlâ büyükse tek satır (\n) ve cümle sınırlarından böler."""
    units: List[str] = []
    for block in cleaned.split("\n\n"):
        if len(block) <= max_chunk_size:
            if block.strip():
                units.append(block)
            continue
        for line in block.split("\n"):
            if len(line) <= max_chunk_size:
                if line.strip():
                    units.append(line)
                continue
            sentences = re.split(r"(?<=[.!?])\s+", line)
            for sent in sentences:
                if len(sent) <= max_chunk_size:
                    if sent.strip():
                        units.append(sent)
                else:
                    for start in range(0, len(sent), max_chunk_size):
                        piece = sent[start:start + max_chunk_size].strip()
                        if piece:
                            units.append(piece)
    return units


def split_markdown_into_legal_chunks(
    markdown_text: str,
    filename: str,
    domain: str,
    scope: str = "global",
    project_id: str = "global",
    project_name: str = "Genel Mevzuat ve Standartlar",
    rel_path: str = "",
    procurement_type: str = "ortak",
    folder_subsystem: Optional[str] = None
) -> List[Dict[str, Any]]:
    """
    Mevzuat, sözleşme ve teknik şartnameleri 'Madde X', 'Bölüm X' veya Markdown başlıklarına (#, ##, ###) göre
    bağlam bütünlüğünü koruyarak parçalar; sayfa numaralarını takip eder ve proje-bağımsız metadata üretir.
    """
    chunks: List[Dict[str, Any]] = []
    pattern = r"(?=(?:^|\n)(?:#{1,4}\s+|MADDE\s+\d+|Madde\s+\d+|Poz\s+\d+|BÖLÜM\s+\d+|Grup\s+\d+))"
    raw_sections = re.split(pattern, markdown_text, flags=re.MULTILINE)
    current_title = f"{filename} Genel Hükümler"
    doc_has_any_page = bool(PAGE_PATTERN.search(markdown_text))
    current_page = 1 if doc_has_any_page else 0
    document_id = f"{project_id}::{rel_path or filename}"
    doc_dominant_subsystem = infer_document_dominant_subsystem(
        markdown_text, domain=domain, folder_subsystem=folder_subsystem
    )

    def _make_record(content_str: str, title_str: str, page_val: int, parent_txt: str) -> Dict[str, Any]:
        meta = classify_chunk_metadata(
            content_str,
            title_str,
            filename,
            domain,
            folder_subsystem=folder_subsystem,
            rel_path=rel_path,
            doc_dominant_subsystem=doc_dominant_subsystem,
        )
        return {
            "content": content_str,
            "metadata": {
                "document_id": document_id,
                "rel_path": rel_path or filename,
                "source_file": filename,
                "domain": meta["domain"],
                "title": title_str,
                "subsystem": meta["subsystem"],
                "doc_type": meta["doc_type"],
                "topics": meta["topics"],
                "standard_codes": meta["standard_codes"],
                "doc_role": meta["doc_role"],
                "scope": scope,
                "project_id": project_id,
                "project_name": project_name,
                "procurement_type": procurement_type,
                "page_num": page_val,
                "has_page_marker": doc_has_any_page,
                "parent_content": parent_txt,
            },
        }

    for section in raw_sections:
        cleaned = section.strip()
        if not cleaned:
            continue
        p_num = extract_page_number_from_text(cleaned)
        if p_num is not None:
            current_page = p_num
        if len(cleaned) < 35:
            continue
        lines = cleaned.split("\n")
        first_line = lines[0].strip()
        if re.search(r"(?:#{1,4}\s+|MADDE\s+\d+|Madde\s+\d+|Poz\s+\d+|BÖLÜM\s+\d+|Grup\s+\d+)", first_line, re.IGNORECASE):
            current_title = first_line.replace("#", "").strip()
        max_chunk_size = 1800
        parent_section_text = cleaned[:3500]
        if len(cleaned) > max_chunk_size:
            units = _split_section_units(cleaned, max_chunk_size)
            chunk_page = current_page
            page_header_str = f" - Sayfa {chunk_page}" if chunk_page > 0 else ""
            temp_chunk = f"[{filename} - {current_title}{page_header_str}]\n"
            for p_item in units:
                p_page = extract_page_number_from_text(p_item)
                if p_page is not None:
                    current_page = p_page
                if len(temp_chunk) + len(p_item) > max_chunk_size and len(temp_chunk) > 100:
                    chunks.append(_make_record(temp_chunk.strip(), current_title, chunk_page, parent_section_text))
                    chunk_page = current_page
                    page_header_str = f" - Sayfa {chunk_page}" if chunk_page > 0 else ""
                    temp_chunk = f"[{filename} - {current_title}{page_header_str}]\n" + p_item + "\n"
                else:
                    temp_chunk += p_item + "\n"
            if len(temp_chunk.strip()) > 30:
                chunks.append(_make_record(temp_chunk.strip(), current_title, chunk_page, parent_section_text))
        else:
            chunks.append(_make_record(cleaned, current_title, current_page, parent_section_text))
    return chunks
def get_file_quick_hash(path: Path) -> str:
    """Dosya boyutu ve değiştirilme tarihine dayalı hızlı MD5 hash üretir."""
    stat = path.stat()
    h_str = f"{path.name}_{stat.st_size}_{stat.st_mtime}"
    return hashlib.md5(h_str.encode()).hexdigest()
MANIFEST_FILE = VECTOR_DB_DIR / "ingested_manifest.json"
def get_manifest_key(project_id: str, file_path: Path) -> str:
    """Dokümanın manifest içindeki benzersiz anahtarını oluşturur (aynı adlı dosyaların çakışmasını engeller)."""
    try:
        rel = file_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
        return f"{project_id}::{rel}"
    except Exception:
        return f"{project_id}::{file_path.name}"
def load_manifest() -> Dict[str, Any]:
    if MANIFEST_FILE.exists():
        try:
            with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}
    return {}
def save_manifest(manifest: Dict[str, Any]):
    try:
        VECTOR_DB_DIR.mkdir(parents=True, exist_ok=True)
        with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
def ingest_documents(reset_collection: bool = False):
    """
    Tüm dokümanları iki ana havuzda okur:
    1. GENEL MEVZUAT & STANDARTLAR (scope='global', project_id='global')
    2. PROJE EVRAKLARI (scope='project', project_id='proje_kodu')
    Artımlı (Incremental) Mod: Değişmeyen dosyaları atlar, sadece yeni/güncellenenleri indeksler.
    """
    console.rule("[bold cyan]İnşaat & Metro Mevzuat / Şartname Master İndeksleme (1_ingest.py)[/bold cyan]")
    device = get_device()
    console.print(f"[bold green]✔[/bold green] Aktif Aygıt: [yellow]{device.upper()}[/yellow]")
    console.print(f"[bold green]✔[/bold green] Embedding Modeli: [yellow]{EMBEDDING_MODEL_NAME}[/yellow]")
    console.print(f"[bold green]✔[/bold green] 1. Genel Havuz: [yellow]{GENEL_MEVZUAT_DIR}[/yellow]")
    console.print(f"[bold green]✔[/bold green] 2. Projeler Havuzu: [yellow]{PROJE_EVRAKLARI_DIR}[/yellow]")
    client = get_chroma_client()
    collection_name = "insaat_mevzuat"
    manifest = load_manifest()
    if reset_collection:
        try:
            client.delete_collection(name=collection_name)
            console.print("[bold yellow]⟳[/bold yellow] Eski koleksiyon temizlendi, proje izolasyonu destekli yeni şema kuruluyor...")
            manifest = {}
            save_manifest(manifest)
        except Exception:
            pass
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine", "description": "Genel mevzuat ve proje bazlı izole edilmiş sözleşme koleksiyonu"}
    )
    # 1. Genel Mevzuat Dosyalarını Topla
    queue = []
    if GENEL_MEVZUAT_DIR.exists():
        for ext in ["*.md", "*.txt", "*.pdf", "*.html"]:
            for fp in GENEL_MEVZUAT_DIR.rglob(ext):
                if is_ignored_path(fp):
                    continue
                queue.append({
                    "file_path": fp,
                    "scope": "global",
                    "project_id": "global",
                    "project_name": "Genel Mevzuat ve Standartlar"
                })
    # 2. Proje Evraklarını Topla (Klasör Bazlı İzolasyon)
    if PROJE_EVRAKLARI_DIR.exists():
        for proj_dir in PROJE_EVRAKLARI_DIR.iterdir():
            if proj_dir.is_dir():
                pid = proj_dir.name
                pname = pid.replace("_", " ").title()
                for ext in ["*.md", "*.txt", "*.pdf", "*.html"]:
                    for fp in proj_dir.rglob(ext):
                        if is_ignored_path(fp):
                            continue
                        queue.append({
                            "file_path": fp,
                            "scope": "project",
                            "project_id": pid,
                            "project_name": pname
                        })
    if not queue:
        console.print("[bold red]![/bold red] İndekslenecek doküman bulunamadı!")
        return
    # Taşınan veya silinen dokümanların yetim (orphan) kayıtlarını manifest ve ChromaDB'den temizle
    if not reset_collection and manifest:
        active_doc_keys = {get_manifest_key(it["project_id"], it["file_path"]) for it in queue}
        orphan_keys = [k for k in list(manifest.keys()) if k not in active_doc_keys]
        if orphan_keys:
            for ok in orphan_keys:
                try:
                    collection.delete(where={"document_id": ok})
                except Exception:
                    pass
                manifest.pop(ok, None)
            save_manifest(manifest)
            console.print(f"[bold yellow]⟳[/bold yellow] Taşınan/silinen [cyan]{len(orphan_keys)}[/cyan] eski doküman kaydı veritabanından temizlendi.")
    console.print(f"[bold green]✔[/bold green] Toplam [cyan]{len(queue)}[/cyan] adet doküman taranıyor (Mod: {'Tam Sıfırlama' if reset_collection else 'Artımlı/Incremental'}).")
    embedding_model = get_embedding_model()
    summary_data = []
    subsystem_counts = {}
    skipped_count = 0
    updated_count = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Dokümanlar ayrıştırılıyor ve etiketleniyor...", total=len(queue))
        for item in queue:
            file_path = item["file_path"]
            scope = item["scope"]
            project_id = item["project_id"]
            project_name = item["project_name"]
            domain = detect_domain_from_path(file_path)
            procurement_type = detect_procurement_type_from_path(file_path, project_id)
            folder_subsystem = detect_folder_subsystem(file_path)
            filename = file_path.name
            # Artımlı kontrol: Dosya hash'i değişmemişse ve koleksiyonda varsa atla
            file_hash = get_file_quick_hash(file_path)
            doc_key = get_manifest_key(project_id, file_path)
            manifest_entry = manifest.get(doc_key)
            if not manifest_entry and filename in manifest:
                legacy = manifest[filename]
                if legacy.get("project_id") == project_id:
                    manifest_entry = legacy
            if not reset_collection and manifest_entry and manifest_entry.get("hash") == file_hash:
                skipped_count += 1
                progress.advance(task)
                continue
            progress.update(task, description=f"[cyan][{project_id}] Ayrıştırılıyor: [white]{filename}[/white]")
            # Eğer dosya yeni/güncellendiyse olası eski/yetim parçalarını proje izolasyonuyla sil
            if not reset_collection:
                try:
                    collection.delete(where={"document_id": doc_key})
                except Exception:
                    try:
                        collection.delete(where={"$and": [{"source_file": filename}, {"project_id": project_id}]})
                    except Exception:
                        pass
            try:
                if file_path.suffix.lower() in [".md", ".txt"]:
                    with open(file_path, "r", encoding="utf-8") as f:
                        markdown_text = f.read()
                else:
                    markdown_text = parse_any_document(file_path)
            except Exception as e:
                console.print(f"[red]Hata: {filename} okunamadı ({e})[/red]")
                progress.advance(task)
                continue
            try:
                rel_path = file_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()
            except Exception:
                rel_path = filename
            chunks = split_markdown_into_legal_chunks(
                markdown_text=markdown_text,
                filename=filename,
                domain=domain,
                scope=scope,
                project_id=project_id,
                project_name=project_name,
                rel_path=rel_path,
                procurement_type=procurement_type,
                folder_subsystem=folder_subsystem
            )
            if not chunks:
                progress.advance(task)
                continue
            progress.update(task, description=f"[cyan]Vektörleştiriliyor: [white]{filename}[/white] ({len(chunks)} parça)")
            docs_content = [c["content"] for c in chunks]
            metadatas = [c["metadata"] for c in chunks]
            doc_ids = [f"{project_id}_{filename}_{c['metadata']['subsystem']}_{uuid.uuid4().hex[:8]}" for c in chunks]
            for m in metadatas:
                sub = m["subsystem"]
                subsystem_counts[sub] = subsystem_counts.get(sub, 0) + 1
            if hasattr(embedding_model, "encode"):
                res = embedding_model.encode(docs_content, return_dense=True)
                if isinstance(res, dict) and "dense_vecs" in res:
                    vectors = res["dense_vecs"].tolist()
                elif hasattr(res, "tolist"):
                    vectors = res.tolist()
                else:
                    vectors = list(res)
            else:
                vectors = [embedding_model.encode_queries([text])[0].tolist() for text in docs_content]
            collection.add(
                ids=doc_ids,
                documents=docs_content,
                metadatas=metadatas,
                embeddings=vectors,
            )
            manifest[doc_key] = {
                "hash": file_hash,
                "chunks": len(chunks),
                "domain": domain,
                "procurement_type": procurement_type,
                "project_id": project_id,
                "source_file": filename,
                "rel_path": str(file_path.resolve().relative_to(DATA_DIR.resolve()).as_posix()) if file_path.is_relative_to(DATA_DIR) else filename
            }
            if filename in manifest and manifest[filename].get("project_id") == project_id:
                manifest.pop(filename, None)
            save_manifest(manifest)
            updated_count += 1
            summary_data.append((filename, project_id, domain, len(chunks)))
            progress.advance(task)
    console.print(f"\n[bold green]✔ İndeksleme Tamamlandı:[/bold green] [cyan]{updated_count}[/cyan] dosya işlendi, [yellow]{skipped_count}[/yellow] değişmeyen dosya önbellekten korundu.")
    if summary_data:
        # Doküman Özeti Tablosu
        table = Table(title="[bold green]İşlenen Yeni / Güncellenen Dokümanlar[/bold green]")
        table.add_column("Doküman Adı", style="cyan")
        table.add_column("Proje / Kapsam", style="yellow")
        table.add_column("Domain", style="magenta")
        table.add_column("Parça Sayısı", justify="right", style="green")
        for fname, pid, dname, count in summary_data:
            table.add_row(fname, pid, dname, str(count))
        console.print(table)
    console.print(f"[bold green]✔[/bold green] ChromaDB koleksiyonundaki güncel toplam madde/vektör sayısı: [bold yellow]{collection.count()}[/bold yellow]")
if __name__ == "__main__":
    reset_mode = "--reset" in sys.argv
    ingest_documents(reset_collection=reset_mode)

