# -*- coding: utf-8 -*-
"""
Standart kodu normalizasyonu ve atıf çıkarımı — %100 deterministik (LLM yok).

Amaç:
    Poz / şartname / yazışma metinlerindeki standart atıflarını tek bir kanonik
    anahtara indirger. Böylece "EN50126", "EN 50126:2006", "TS EN 50122-1:2020+A1"
    ve "DİN 16726" (Türkçe İ) gibi yazımlar aynı kimliğe bağlanır.

Kural:
    - Bu modül ASLA LLM çağırmaz; regex + harita tabanlıdır.
    - Tüm fonksiyonlar safdır (girdi -> çıktı), yan etkisi yoktur.
"""
import re
from typing import Any, Dict, List, Optional

# --- Karakter normalizasyon tabloları ---------------------------------------
# Standart kodlarında Türkçe harfler Latin karşılıklarına sabitlenir (DİN -> DIN)
_TR_FIX = str.maketrans({"İ": "I", "ı": "I"})
# Birleşik nokta (İ üstü nokta kalıntısı, U+0307) temizliği regex ile yapılır
# OCR kaynaklı tire varyantları -> düz tire (non-breaking, en/em dash, soft hyphen)
_HYPHEN_FIX = str.maketrans({
    "\u2011": "-",  # non-breaking hyphen
    "\u2013": "-",  # en dash
    "\u2014": "-",  # em dash
    "\u2212": "-",  # minus sign
    "\u00ad": "-",  # soft hyphen
})

# --- Önek -> çekirdek önek haritası ------------------------------------------
# Ulusal sarmalayıcılar (TS/BS/DIN/NF + EN/ISO/IEC) kanonikte ulusal öneki kaybeder;
# tek başına ulusal standartlar (TS 500, DIN 16726, BS 476) korunur.
_PREFIX_CORE_MAP = {
    "TS EN ISO": "EN ISO", "BS EN ISO": "EN ISO", "DIN EN ISO": "EN ISO", "NF EN ISO": "EN ISO",
    "TS EN IEC": "EN IEC", "BS EN IEC": "EN IEC", "DIN EN IEC": "EN IEC", "NF EN IEC": "EN IEC",
    "TS EN": "EN", "BS EN": "EN", "DIN EN": "EN", "NF EN": "EN",
    "EN IEC": "EN IEC", "TS ISO": "ISO", "TS IEC": "IEC", "DIN VDE": "DIN VDE",
    "EN": "EN", "IEC": "IEC", "ISO": "ISO", "NFPA": "NFPA", "IEEE": "IEEE",
    "ETSI": "ETSI", "UIC": "UIC", "ASTM": "ASTM", "ANSI": "ANSI", "AGMA": "AGMA",
    "TS": "TS", "BS": "BS", "DIN": "DIN", "NF": "NF", "VDE": "VDE",
}
# Uzun önekler önce eşleşsin (TS EN ISO, TS EN'den önce gelmeli)
_PREFIX_PATTERN = "|".join(sorted(_PREFIX_CORE_MAP.keys(), key=len, reverse=True))

# --- Atıf yakalama regex'i ----------------------------------------------------
# Önek + sayı (+ noktalı alt sayı) (+ parça) (+ :baskı) (+ +Ek)
# NOT: IGNORECASE YOK — Türkçe "en az 210 gün" ifadesindeki küçük harf "en"
# kelimesi sahte "EN 210" standardı olarak yakalanmasın. Gerçek standart
# atıfları belgelerde büyük harf yazılır (EN 50122-1, IEC 60870-5-104 ...).
_REF_RE = re.compile(
    r"\b(?:" + _PREFIX_PATTERN + r")\s*[-/ ]?\s*\d+(?:[.\-/]\d+)*"
    r"(?:\s*[-/]\s*\d+)?(?::\s*\d{4}(?:\s*\+\s*[^\s:]+)*)?",
)

# Bir atıfın gerçekten standart kodu görünüp görünmediğini hızlıca sınayan desen
# (is_standard_like: ham metin zaten büyük harf kurallarından geçer)
_STANDARD_LIKE_RE = re.compile(
    r"^(?:" + _PREFIX_PATTERN + r")\s*[-/ ]?\s*\d+", re.IGNORECASE,
)


def _clean_raw(raw: str) -> str:
    """Ham atıf metnini ortak taban forma indirger (TR harf, tire varyantı, boşluk)."""
    s = raw.translate(_TR_FIX).translate(_HYPHEN_FIX)
    s = re.sub(r"\u0307", "", s)  # birleşik nokta kalıntısı
    s = re.sub(r"\s+", " ", s).strip().upper()
    return s.strip(".,;:()\"'")


def normalize_standard_code(raw: str) -> Dict[str, Any]:
    """
    Ham standart kodunu kanonik biçime indirger.

    Döndürür (valid=True iken):
        canonical      : eşleştirme anahtarı  -> "EN 50122-1"
        family         : parça numarasız aile -> "EN 50122"
        edition        : baskı/ek bilgisi     -> "2020+A1" (yoksa "")
        prefix         : metinde görülen önek -> "TS EN"
        core_prefix    : kanonik çekirdek     -> "EN"
        search_aliases : toleranslı arama alternatifleri
    Geçersiz girdide {"valid": False, "canonical": <temizlenmiş metin>} döner.
    """
    s = _clean_raw(raw)
    invalid = {"valid": False, "canonical": s, "family": "", "edition": "",
               "prefix": "", "core_prefix": "", "search_aliases": []}

    m = re.match(r"^(?P<pfx>" + _PREFIX_PATTERN + r")\s*[-/ ]?\s*(?P<rest>\d.*)?$", s)
    if not m:
        return invalid
    pfx_raw = re.sub(r"[\s\-/]+", " ", m.group("pfx")).strip()
    rest = (m.group("rest") or "").strip()

    # Baskı bilgisini ayır ("2020+A1:2015" gibi zincirler olduğu gibi kalır)
    edition = ""
    if ":" in rest:
        rest_main, edition = rest.split(":", 1)
        edition = edition.strip()
    else:
        rest_main = rest
    rest_main = rest_main.strip(" .,;:)(")

    # Ana numara + alt parça zinciri — ÇOK TİRELİ standartları da kapsar:
    # "61000-6-3", "60870-5-104", "50122-1" gibi zincirler bütünüyle yakalanır.
    # (Yalnızca sondaki -N'i ayırmak EN 61000-6-3 / IEC 60870-5-104 kaybına yol açar.)
    m_parts = re.match(r"^(?P<base>\d+(?:\.\d+)*)(?P<subs>(?:[-/]\d{1,3})+)?$", rest_main)
    if not m_parts:
        return invalid
    base = m_parts.group("base")
    subs = (m_parts.group("subs") or "").replace("/", "-")
    part = subs.lstrip("-")

    core = _PREFIX_CORE_MAP.get(pfx_raw, pfx_raw)
    canonical = f"{core} {base}{subs}"
    family = f"{core} {base}"

    aliases = {canonical, canonical.replace(" ", ""), family, family.replace(" ", "")}
    if pfx_raw != core:
        national = f"{pfx_raw} {base}{subs}"
        aliases.add(national)
        aliases.add(national.replace(" ", ""))
    if edition:
        aliases.add(f"{canonical}:{edition}")

    return {
        "valid": True,
        "canonical": canonical,
        "family": family,
        "edition": edition,
        "prefix": pfx_raw,
        "core_prefix": core,
        "number": rest_main,
        "part": part,
        "search_aliases": sorted(a for a in aliases if a),
    }


def is_standard_like(text: str) -> bool:
    """Bir atıf metninin standart kodu biçiminde olup olmadığını hızlıca söyler."""
    if not text:
        return False
    return bool(_STANDARD_LIKE_RE.match(_clean_raw(text)))


def extract_standard_refs(text: str) -> List[Dict[str, Any]]:
    """
    Metindeki tüm standart atıflarını bulur, her birini kanonik forma indirger ve
    kanonik kod bazında tekilleştirerek sıralı liste döndürür.

    Her kayıt: normalize_standard_code çıktısı + {"raw", "span": (start, end)}.
    "Poz 04.191", "Madde 10", "Sayfa 500" gibi ifadeler önek listesinde olmadığı
    için asla yakalanmaz.
    """
    if not text:
        return []
    seen: set = set()
    out: List[Dict[str, Any]] = []
    for m in _REF_RE.finditer(text):
        info = normalize_standard_code(m.group(0))
        if not info.get("valid"):
            continue
        if info["canonical"] in seen:
            continue
        seen.add(info["canonical"])
        info["raw"] = m.group(0)
        info["span"] = (m.start(), m.end())
        out.append(info)
    return out


def match_standard_fuzzy(
    query_code: str,
    available_codes: List[str],
    threshold: int = 92,
) -> Dict[str, Any]:
    """
    Sorgu kodunu mevcut kod listesiyle eşler.

    Öncelik: kanonik tam eşleşme -> aile eşleşmesi -> rapidfuzz benzerlik (>= threshold).
    Döndürür: {"match": <kod|None>, "score": float, "type": exact|family|fuzzy|none}
    """
    q = normalize_standard_code(query_code)
    if not available_codes:
        return {"match": None, "score": 0.0, "type": "none"}

    norm_available: Dict[str, Dict[str, Any]] = {}
    for code in available_codes:
        n = normalize_standard_code(code)
        if n.get("valid"):
            norm_available[n["canonical"]] = n

    # 1) Kanonik tam eşleşme
    if q.get("valid") and q["canonical"] in norm_available:
        return {"match": q["canonical"], "score": 100.0, "type": "exact"}
    # Ham metin zaten listede biçimsiz eşleşiyor olabilir
    cleaned = _clean_raw(query_code)
    for code in available_codes:
        if _clean_raw(code) == cleaned:
            return {"match": code, "score": 100.0, "type": "exact"}

    if not q.get("valid"):
        return {"match": None, "score": 0.0, "type": "none"}

    # 2) Aile eşleşmesi (parça numarasız)
    q_family_norms = {q["family"], q["family"].replace(" ", "")}
    for canon, n in norm_available.items():
        if n["family"] in q_family_norms or canon in q_family_norms:
            return {"match": canon, "score": 95.0, "type": "family"}

    # 3) Bulanık eşleşme (OCR kusurlu yazımlar)
    try:
        from rapidfuzz import fuzz, process
    except ImportError:
        return {"match": None, "score": 0.0, "type": "none"}

    q_norm = q["canonical"]
    best = process.extractOne(
        q_norm,
        list(norm_available.keys()),
        scorer=fuzz.token_sort_ratio,
        score_cutoff=threshold,
    )
    if best:
        return {"match": best[0], "score": float(best[1]), "type": "fuzzy"}
    return {"match": None, "score": 0.0, "type": "none"}
