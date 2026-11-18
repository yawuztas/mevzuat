# -*- coding: utf-8 -*-
"""
Kimlik Kartı Çıkarıcısı (Adım 3) — İki Aşamalı.

Aşama 1 (deterministik — LLM yok):
    Resmi yazı başlığındaki Tarih / Sayı / İlgi / Konu alanları regex + dateparser
    ile çıkarılır. dateparser ASLA DATE_ORDER'sız çağrılmaz:
        settings = {"DATE_ORDER": "DMY", "STRICT_PARSING": True}
    (yoksa "02.04.2023" sessizce 4 Şubat olur — gün/ay takas hatası).

Aşama 2 (LLM — zarif bozulmalı):
    - instructor (Pydantic şema): konu etiketleri, talep özeti, hukuki dayanaklar
    - langextract: standart/poz atıflarının karakter ofsetli (char_interval)
      kaynak-geri izlemeli çıkarımı
    Anahtar yoksa / servis düşerse None döner — kart deterministik alanlarla
    pending_review'a düşer. Aşama 1'i asla gölgelemez.

İnsan onay kuyruğu kuralı:
    doc_date VE doc_no deterministik bulunamazsa (veya sender_role ipucu yoksa)
    review_status = "pending_review" — onaylanana kadar İlgi zinciri bağlanmaz.
"""
import re
from typing import Any, Dict, List, Optional, Tuple

# dateparser hattı zorunlu kurulum (Adım 3.1); içe aktarım burada sabittir
import dateparser

# --- Alan regex'leri (resmi yazı başlığı formatı — OCR dostu) ----------------
_RE_DATE = re.compile(r"(?im)^[ \t]*(?:Tarih|Tar[ıi1l]h)(?:[ \t]*|[ \t]*\r?\n+[ \t]*)[:\-][ \t]*(.+?)[ \t]*$")
_RE_CITY_DATE = re.compile(
    r"(?im)(?:İstanbul|Istanbul|Ankara|İzmir|Izmir|Bakırköy|Bakirkoy|Beşiktaş|Besiktas)[,\s]+"
    r"(\d{1,2}\s*[./]\s*\d{1,2}\s*[./]\s*\d{2,4}|\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+\d{4})"
)
_RE_EIMZA_DATE = re.compile(
    r"(?ims)(\d{1,2}[ \t]*[./][ \t]*\d{1,2}[ \t]*[./][ \t]*\d{4})[ \t]*(?:tarihli[ \t]+)?(?:e-?imza|elektronik[ \t]+imza)|"
    r"(?:5070[ \t]*say[ıi1l]l[ıi]|e-?imza|elektronik[ \t]+imza).{0,260}?(\d{1,2}[ \t]*[./][ \t]*\d{1,2}[ \t]*[./][ \t]*\d{4})"
)
_RE_DOCNO = re.compile(
    r"(?im)^[ \t]*(?:Say[ıi1l](?:[ \t]+No)?|Evrak[ \t]*No|Belge[ \t]*No|Numara|Ref(?:erans)?)(?:[ \t]*|[ \t]*\r?\n+[ \t]*)[:\-][ \t]*(.+?)[ \t]*$"
)
_RE_INVERTED_DOCNO = re.compile(
    r"(?im)^[ \t]*[:\-][ \t]*([^\r\n]{3,60}?)[ \t]*\r?\n+(?:[ \t]*\r?\n+)*[ \t]*(?:Say[ıi1l](?:[ \t]+No)?|Evrak[ \t]*No|Belge[ \t]*No)\b"
)
_RE_INLINE_REF = re.compile(
    r"(?im)(?:^|\s)Ref(?:erans)?[ \t]*[:\-][ \t]*([A-ZÇĞİÖŞÜ0-9][A-ZÇĞİÖŞÜa-z0-9/.\- ]{2,42})"
)
_RE_HEADER_COLON_DOCNO = re.compile(
    r"(?m)^[ \t]*:[ \t]*([A-Z0-9][A-Z0-9./\- \t]{4,45})[ \t]*$"
)
_RE_ILGI_HEAD = re.compile(r"(?im)^[ \t]*(?:##[ \t]*|[-*][ \t]+)?[İI1l]lg[iı1l](?:[ \t]+Yaz[ıi]l?[aı]r[ıi]?)?[ \t]*[:\-][ \t]*(.*?)[ \t]*$")
_RE_KONU = re.compile(r"(?im)^[ \t]*(?:##[ \t]*)?Konu(?:[ \t]*|[ \t]*\r?\n+[ \t]*)[:\-][ \t]*(.+?)[ \t]*$")
_RE_FILENAME_DATE = re.compile(r"(?<!\d)(\d{4})[-_.](\d{2})[-_.](\d{2})(?!\d)")
_RE_FILENAME_DMY = re.compile(r"(?<!\d)(\d{2})[._-](\d{2})[._-](\d{4})(?!\d)")
# İlgi satırındaki evrak numarası adayları:
#   çok segmentli kurumsal kod: ATI/AS/TR/PM/4236, ATi-AS-TR-PM-4236, E-70659999-755.02.S.21-2202, 2016.03/GD-5751
#   harf önekli: E-84920, S.23-401, GD-4503
#   tarih biçimli: 02.04.2023
#   çıplak sayı: 4236 ("4236 numaralı yazınız")
_RE_REF_NO = re.compile(
    r"\b[A-ZÇĞİÖŞÜa-z0-9]{1,10}(?:[-./][A-ZÇĞİÖŞÜa-z0-9]{1,10}){2,6}\b"
    r"|\b[A-ZÇĞİÖŞÜ]{1,4}[-./]\d{2,6}(?:[-./]\d{1,6})*\b"
    r"|\b\d{1,6}(?:[-./]\d{2,6}){1,2}\b"
    r"|\b\d{3,7}\b"
)
_RE_ILGI_TARIH = re.compile(r"(\d{1,2}\s*[./]\s*\d{1,2}\s*[./]\s*\d{2,4})|(\d{1,2}\s+[A-Za-zÇĞİÖŞÜçğıöşü]+\s+\d{4})")

# Gönderen rolü ipuçları (klasör konvansiyonu birincil, bunlar yalnızca yedek)
_ROLE_HINTS = {
    "contractor": ("yüklenici", "taahhüt", "müteahhit"),
    "administration": ("idare", "belediye", "bakanlık", "başkanlık"),
    "consultant": ("müşavir", "danışman", "kontrollük"),
}

_DATE_SETTINGS = {"DATE_ORDER": "DMY", "STRICT_PARSING": True}


def parse_tr_date(raw: str, default_year: Optional[int] = None) -> Tuple[Optional[str], float]:
    """
    Türkçe tarih metnini ISO'ya çevirir. DATE_ORDER=DMY ZORUNLU.
    Yıl yoksa default_year ile tamamlar (güven 0.8'e düşer).
    Döndürür: (iso_str | None, confidence 0.0-1.0)
    """
    if not raw or not raw.strip():
        return None, 0.0
    raw = raw.strip().strip(".,;")
    # OCR ayracı içi boşlukları düzelt: "08/ 06/2020" -> "08/06/2020"
    raw = re.sub(r"(\d{1,2})\s*([./])\s*(\d{1,2})\s*([./])\s*(\d{2,4})", r"\1\2\3\4\5", raw)
    d = dateparser.parse(raw, languages=["tr"], settings=_DATE_SETTINGS)
    if d:
        return d.date().isoformat(), 1.0
    # Yılsız kısa biçim ("12/10") — dosya yılıyla tamamlanır
    if default_year and re.fullmatch(r"\d{1,2}[./]\d{1,2}", raw):
        d2 = dateparser.parse(f"{raw}/{default_year}", languages=["tr"], settings=_DATE_SETTINGS)
        if d2:
            return d2.date().isoformat(), 0.8
    # Ay adı biçimi yıl takılmış da olsa başarısızsa ("Nisan 2023" vb. zaten yakalanır)
    return None, 0.0


def _span(m: "re.Match") -> Dict[str, Any]:
    return {"char_start": m.start(), "char_end": m.end(), "exact_quote": m.group(0).strip()}


def _guess_sender_role(md_text: str) -> Tuple[Optional[str], float]:
    """Klasör ipucu yoksa içerikten zayıf tahmin (güven düşük -> pending_review)."""
    head = md_text[:2500]
    low = head.lower()
    scores = {role: sum(1 for kw in kws if kw in low) for role, kws in _ROLE_HINTS.items()}
    best = max(scores, key=scores.get)
    if scores[best] == 0:
        return None, 0.0
    return best, min(0.5, 0.2 + 0.15 * scores[best])


def _evidence_weight_for(sender_role: Optional[str], doc_type: str) -> str:
    if doc_type == "tutanak" or sender_role == "joint":
        return "TUTANAK_ORTAK"
    if sender_role == "administration" or sender_role == "consultant":
        return "RESMI_POZISYON_IDARE"
    return "IDDIA_YUKLENICI"


def _extract_ilgi_block(md_text: str) -> Optional[Tuple[int, int, str]]:
    """
    Tek veya çok satırlı `İlgi:` bloğunu (`- a) ... - b) ...`) yakalar.
    Sayfa 1'de `İlgi:` başlığından sonra kısa muhatap satırı (`T.C.`, `Raylı Sistem...`)
    araya girerse onları atlayıp madde listesini toplar.
    """
    m = _RE_ILGI_HEAD.search(md_text)
    if not m:
        return None
    start = m.start()
    end = m.end()
    lines = md_text[start:].splitlines(keepends=True)
    first_rest = (m.group(1) or "").strip()
    collected = [first_rest] if first_rest else []

    bullet_re = re.compile(r"^\s*(?:[-*]\s+|\d+\.\s+)?(?:\(?[a-zçğıöşü]\)|\d{1,2}[./]\d{1,2}[./]\d{2,4})", re.IGNORECASE)
    short_hdr_re = re.compile(r"^\s*(?:##\s*)?(?:T\.C\.|İSTANBUL|ISTANBUL|RAYLI SİSTEM|AVRUPA YAKASI|DAĞITIM|DAGITIM)", re.IGNORECASE)

    consumed_len = len(lines[0]) if lines else 0
    found_bullet = bool(first_rest and re.search(r"^[a-z]\)", first_rest, re.I))
    skipped_headers = 0
    consecutive_blanks = 0
    for ln in lines[1:22]:
        s = ln.strip()
        if not s:
            consecutive_blanks += 1
            if consecutive_blanks > 2:
                break
            consumed_len += len(ln)
            continue
        consecutive_blanks = 0
        if bullet_re.match(s) or (found_bullet and ("sayıl" in s.lower() or "sayil" in s.lower() or "tarih" in s.lower()) and len(s) < 160):
            found_bullet = True
            collected.append(re.sub(r"^\s*(?:[-*]|\d+\.)\s*", "", s))
            consumed_len += len(ln)
            continue
        if not found_bullet and skipped_headers < 4 and (short_hdr_re.match(s) or s.startswith("##")):
            skipped_headers += 1
            consumed_len += len(ln)
            continue
        break

    ilgi_raw = " ; ".join(c for c in collected if c).strip()
    if not ilgi_raw:
        return None
    return start, start + max(end - start, consumed_len), ilgi_raw


def extract_card_regex(
    md_text: str,
    *,
    filename: str,
    sender_role_hint: Optional[str] = None,
    doc_type: str = "yuklenici_yazisi",
    default_year: Optional[int] = None,
) -> Dict[str, Any]:
    """
    Aşama 1 — %100 deterministik Kimlik Kartı + kanıt span'leri.
    default_year: dosya adı/klasör yılından gelir (yıl eksik tarihlerde kullanılır).
    """
    spans: List[Dict[str, Any]] = []
    confidences: List[float] = []

    # --- Tarih ---
    doc_date, date_conf = None, 0.0
    m = _RE_DATE.search(md_text)
    if m:
        spans.append({"field": "doc_date", **_span(m)})
        doc_date, date_conf = parse_tr_date(m.group(1), default_year=default_year)
        confidences.append(date_conf)
    if not doc_date:
        m_city = _RE_CITY_DATE.search(md_text)
        if m_city:
            spans.append({"field": "doc_date", **_span(m_city)})
            doc_date, date_conf = parse_tr_date(m_city.group(1), default_year=default_year)
            if doc_date:
                date_conf = min(date_conf, 0.95)
                confidences.append(date_conf)
    if not doc_date:
        m_eimza = _RE_EIMZA_DATE.search(md_text)
        if m_eimza:
            raw_ed = m_eimza.group(1) or m_eimza.group(2)
            spans.append({"field": "doc_date", **_span(m_eimza)})
            doc_date, date_conf = parse_tr_date(raw_ed, default_year=default_year)
            if doc_date:
                date_conf = min(date_conf, 0.9)
                confidences.append(date_conf)
    if not doc_date:
        # Yedek: dosya adı YYYY-MM-DD veya DD.MM.YYYY konvansiyonu
        mf = _RE_FILENAME_DATE.search(filename or "")
        if mf:
            doc_date = f"{mf.group(1)}-{mf.group(2)}-{mf.group(3)}"
            date_conf = 1.0
            confidences.append(1.0)
        else:
            mf2 = _RE_FILENAME_DMY.search(filename or "")
            if mf2:
                doc_date, _ = parse_tr_date(f"{mf2.group(1)}.{mf2.group(2)}.{mf2.group(3)}")
                if doc_date:
                    date_conf = 0.9
                    confidences.append(0.9)
    if not default_year and doc_date:
        default_year = int(doc_date[:4])

    # --- Sayı ---
    doc_no, no_conf = None, 0.0
    for pat, conf in (
        (_RE_DOCNO, 1.0),
        (_RE_INVERTED_DOCNO, 0.95),
        (_RE_INLINE_REF, 0.95),
    ):
        m = pat.search(md_text)
        if not m:
            continue
        raw_no = m.group(1).strip()
        # OCR tek satıra yapıştırma, sondaki çıplak "Ref"/"Sayı" ve ayraç boşluğu temizliği:
        raw_no = re.split(
            r"\s+(?:Tarih|Konu|[İI]lg[iı]|Ref(?:erans)?|Say[ıi1l])(?:\s*[:\-]|$)",
            raw_no,
            flags=re.IGNORECASE,
        )[0]
        raw_no = re.sub(r"([-/])\s+([0-9S])", r"\1\2", raw_no)
        raw_no = re.sub(r"\s{2,}", " ", raw_no).strip().lstrip(":").strip()
        if 3 <= len(raw_no) <= 45 and re.search(r"\d", raw_no):
            spans.append({"field": "doc_no", **_span(m)})
            doc_no, no_conf = raw_no, conf
            confidences.append(conf)
            break
    if not doc_no:
        # Docling çift sütunda üstte kalan yalnız `:CODE` satırı (başlık bölgesinde, tire/eğik çizgi içerir)
        for hm in _RE_HEADER_COLON_DOCNO.finditer(md_text[:1500]):
            cand = re.sub(r"([-/])\s+([0-9S])", r"\1\2", hm.group(1)).strip()
            if ("-" in cand or "/" in cand) and re.search(r"\d{3,}", cand) and not re.search(r"(?:tel|fax|faks|0\d{3}\s+\d{3})", cand, re.I):
                spans.append({"field": "doc_no", **_span(hm)})
                doc_no, no_conf = cand, 0.9
                confidences.append(0.9)
                break
    if not doc_no:
        m2 = re.search(r"\bE-\d{4,7}\b", md_text)
        if m2:
            spans.append({"field": "doc_no_fallback", **_span(m2)})
            doc_no, no_conf = m2.group(0), 0.7
            confidences.append(0.7)

    # --- İlgi (tek veya çok satırlı) ---
    ilgi_raw, ilgi_refs = None, []
    ilgi_blk = _extract_ilgi_block(md_text)
    if ilgi_blk:
        i_start, i_end, ilgi_raw = ilgi_blk
        spans.append({"field": "ilgi_raw", "char_start": i_start, "char_end": i_end, "exact_quote": ilgi_raw[:250]})
        # OCR yapışma temizliği: "veS.20-1394sayılı" -> "ve S.20-1394 sayılı"
        ilgi_clean = re.sub(r"(?<=ve)(?=[A-Z0-9])", " ", ilgi_raw)
        ilgi_clean = re.sub(r"(?<=\d)(?=say[ıi1l]|tarih)", " ", ilgi_clean, flags=re.IGNORECASE)
        ilgi_clean = re.sub(r"(\d{1,2})\s*([./])\s*(\d{1,2})\s*([./])\s*(\d{2,4})", r"\1\2\3\4\5", ilgi_clean)

        raw_refs = []
        for mm in _RE_REF_NO.finditer(ilgi_clean):
            tok = mm.group(0)
            if not re.search(r"\d", tok):
                continue
            raw_refs.append(tok)
        # Yarım tarih parçalarını ("02.02") atla — tam biçim veya ISO zaten eklenir.
        # Çıplak 4 haneli yıl (1995-2035) da evrak numarası değildir ("2023" sızıntısı).
        for t in dict.fromkeys(raw_refs):
            if re.fullmatch(r"\d{1,2}[./]\d{1,2}", t) and any(t in full for full in ilgi_refs):
                continue
            if re.fullmatch(r"(?:19|20)\d{2}", t):
                continue
            ilgi_refs.append(t)
        for mm in _RE_ILGI_TARIH.finditer(ilgi_clean):
            iso, _ = parse_tr_date(mm.group(0), default_year=default_year)
            if iso:
                ilgi_refs.append(iso)
        ilgi_refs = list(dict.fromkeys(ilgi_refs))

    # --- Konu ---
    subject = None
    m = _RE_KONU.search(md_text)
    if m:
        spans.append({"field": "subject", **_span(m)})
        subject = m.group(1).strip()

    # --- Gönderen rolü ---
    if sender_role_hint:
        sender_role, role_conf = sender_role_hint, 1.0
    else:
        sender_role, role_conf = _guess_sender_role(md_text)
    confidences.append(role_conf)

    confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    auto = bool(doc_date and doc_no and sender_role_hint and date_conf >= 1.0)

    return {
        "card": {
            "doc_date": doc_date,
            "doc_no": doc_no,
            "subject": subject,
            "ilgi_raw": ilgi_raw,
            "sender_role": sender_role,
            "doc_type": doc_type,
            "evidence_weight": _evidence_weight_for(sender_role, doc_type),
            "review_status": "auto_approved" if auto else "pending_review",
            "extraction_confidence": confidence,
            "summary": (md_text[:200].replace("\n", " ").strip()),
        },
        "spans": spans,
        "ilgi_refs": ilgi_refs,
    }


def enrich_with_instructor(md_text: str, max_chars: int = 20000) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
    """
    Aşama 2a — instructor + Pydantic şema ile zenginleştirme.
    Anahtar/servis yoksa (None, hata_mesajı) döner; asla exception sızdırmaz.
    """
    try:
        import instructor
        import google.genai as genai
        from pydantic import BaseModel, Field

        from utils.config import GOOGLE_API_KEY

        if not GOOGLE_API_KEY:
            return None, "GOOGLE_API_KEY tanımlı değil — zenginleştirme atlandı (deterministik alanlar geçerli)."

        class CardEnrichment(BaseModel):
            konu_etiketleri: List[str] = Field(description="1-4 kelime konu/lokasyon etiketleri (snake_case)")
            talep_ozeti: str = Field(description="Yüklenicinin/İdarenin temel taleb veya bildirimi 1-2 cümle")
            hukuki_dayanaklar: List[str] = Field(description="Metinde geçen kanun/madde/şartname atıfları")

        client = genai.Client(api_key=GOOGLE_API_KEY)
        # instructor 1.17: from_gemini YOK — doğrusu from_genai (Mode zorunlu)
        try:
            i_client = instructor.from_genai(client=client, mode=instructor.Mode.GENAI_STRUCTURED_OUTPUTS)
            enriched = i_client.chat.completions.create(
                model="gemini-3.5-flash-lite",
                messages=[{"role": "user", "content": md_text[:max_chars]}],
                response_model=CardEnrichment,
            )
        except Exception:
            # Yapılandırılmış çıktı modu bu modelde desteklenmiyorsa araç çağrısı modu
            i_client = instructor.from_genai(client=client, mode=instructor.Mode.GENAI_TOOLS)
            enriched = i_client.chat.completions.create(
                model="gemini-3.5-flash-lite",
                messages=[{"role": "user", "content": md_text[:max_chars]}],
                response_model=CardEnrichment,
            )
        return enriched.model_dump(), None
    except Exception as e:  # zarif bozulma — Aşama 1 kartı geçerli kalır
        return None, f"instructor zenginleştirme hatası: {e}"


def extract_evidence_spans_llm(md_text: str, max_chars: int = 30000) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
    """
    Aşama 2b — langextract ile karakter ofsetli kanıt çıkarımı.
    Standart/poz atıfları ve temel iddia cümleleri (char_start, char_end, exact_quote).
    Not: langextract API imzası ilk gerçek koşturmada pinlenmelidir; hata
    durumunda (None, hata) döner — deterministik kart etkilenmez.
    """
    try:
        import langextract as lx

        from utils.config import GOOGLE_API_KEY

        if not GOOGLE_API_KEY:
            return None, "GOOGLE_API_KEY tanımlı değil — span çıkarımı atlandı."

        examples = [
            lx.data.ExampleData(
                text="Kablolar EN 50122-1 standardına uygundur. İş 210 gün gecikmiştir.",
                extractions=[
                    lx.data.Extraction(extraction_class="standart_atifi", extraction_text="EN 50122-1"),
                    lx.data.Extraction(extraction_class="iddia", extraction_text="İş 210 gün gecikmiştir"),
                ],
            ),
        ]

        result = lx.extract(
            text_or_documents=md_text[:max_chars],
            prompt_description=(
                "Resmi inşaat yazısından şunu çıkar: standart_atifi (EN/IEC/NFPA kodları), "
                "poz_atifi (Poz X.XX), iddia (yüklenicinin doğrulanmaya muhtaç temel cümlesi)."
            ),
            examples=examples,
            model_id="gemini-3.5-flash-lite",
            api_key=GOOGLE_API_KEY,
            # Kota/RPM güvenliği: varsayılan buffer (1000) uzun dilekçede 15-20
            # istek atar; 4000 + 2 işçi + sessiz ilerleme çok daha ekonomiktir.
            max_char_buffer=4000,
            max_workers=2,
            show_progress=False,
        )
        spans = []
        for ex in getattr(result, "extractions", []) or []:
            ci = getattr(ex, "char_interval", None)
            if ci and getattr(ci, "start_pos", None) is not None:
                spans.append({
                    "field": ex.extraction_class,
                    "char_start": ci.start_pos,
                    "char_end": ci.end_pos,
                    "exact_quote": md_text[ci.start_pos:ci.end_pos],
                })
        return spans, None
    except Exception as e:
        return None, f"langextract span hatası: {e}"


def extract_identity_card(
    md_text: str,
    *,
    filename: str,
    rel_path: str = "",
    doc_sha256: str = "",
    doc_id: str = "",
    project_id: str = "",
    doc_type: str = "yuklenici_yazisi",
    sender_role_hint: Optional[str] = None,
    default_year: Optional[int] = None,
    use_llm: bool = False,
) -> Dict[str, Any]:
    """
    Aşama 1 + (isteğe bağlı) Aşama 2 orkestrasyonu.

    Döndürür:
        {"card": <SQLite documents satırına hazır sözlük>,
         "spans": [...], "ilgi_refs": [...], "enrichment": {...}|None,
         "llm_errors": [...]}
    """
    stage1 = extract_card_regex(
        md_text,
        filename=filename,
        sender_role_hint=sender_role_hint,
        doc_type=doc_type,
        default_year=default_year,
    )
    card = stage1["card"]
    card["doc_id"] = doc_id or (f"{project_id}::{doc_sha256[:24]}" if doc_sha256 else f"{project_id}::{filename}")
    card["project_id"] = project_id
    card["file_path"] = rel_path
    card["doc_sha256"] = doc_sha256

    enrichment, llm_errors = None, []
    if use_llm:
        enrichment, err1 = enrich_with_instructor(md_text)
        if err1:
            llm_errors.append(err1)
        if enrichment:
            card["subject"] = card.get("subject") or enrichment.get("talep_ozeti", "")[:200]
            card["summary"] = enrichment.get("talep_ozeti", card.get("summary", ""))
            if enrichment.get("konu_etiketleri"):
                card["konu_etiketleri"] = enrichment["konu_etiketleri"]
        spans_llm, err2 = extract_evidence_spans_llm(md_text)
        if err2:
            llm_errors.append(err2)
        if spans_llm:
            stage1["spans"] = stage1["spans"] + spans_llm

    # Deterministik alan zayıfsa ve LLM zenginleştirmesi yapılmadıysa -> kuyruk
    if not card.get("doc_date") or not card.get("doc_no"):
        card["review_status"] = "pending_review"

    return {
        "card": card,
        "spans": stage1["spans"],
        "ilgi_refs": stage1["ilgi_refs"],
        "enrichment": enrichment,
        "llm_errors": llm_errors,
    }
