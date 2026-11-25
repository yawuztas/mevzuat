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

# Gönderen rolü ipuçları (klasör ipucu yoksa çoklu-sinyal sınıflandırıcı kullanılır)
_ROLE_HINTS = {
    "contractor": ("yüklenici", "taahhüt", "müteahhit"),
    "administration": ("idare", "belediye", "bakanlık", "başkanlık"),
    "consultant": ("müşavir", "danışman", "kontrollük"),
}

_DATE_SETTINGS = {"DATE_ORDER": "DMY", "STRICT_PARSING": True}

# Çoklu sinyal taraf/tür sınıflandırıcısı için desenler (proje-bağımsız, global kurallar)
_RE_EBYS_ADMIN_DOCNO = re.compile(
    r"(?i)\b(?:E-\d{6,9}-\d{2,4}(?:\.\d+)?|M\.\d{2}\.\d+\.|B\.\d{2}\.\d+\.|S\.\d{2}-\d{3,6})\b"
)
_RE_CONSULTANT_DOCNO = re.compile(
    r"(?i)(?:^|[\s/.\-])(?:GD|MUS|KONT|CNS|PMO|DEN)[-/]\d{2,6}\b"
)
_RE_CONTRACTOR_DOCNO = re.compile(
    r"(?i)(?:(?:[-/])(?:PM|YK|YUK|CNT)[-/]\d{2,6}\b|^[A-ZÇĞİÖŞÜ]{2,6}[-/](?:AS|JV|OG|TR)[-/])"
)
_RE_DATIVE_RECIPIENT = re.compile(
    r"(?i)(?:müdürlüğüne|müdürlüğü'ne|mudurlugune|mudurlugu'ne|"
    r"başkanlığına|başkanlığı'na|baskanligina|baskanligi'na|"
    r"müşavirliğine|müşavirliği'ne|musavirligine|musavirligi'ne|"
    r"danışmanlığına|danışmanlığı'na|danismanligina|"
    r"kontrollüğüne|kontrollüğü'ne|kontrollugune|"
    r"ortaklığına|ortaklığı'na|ortakligina|"
    r"girişimine|girişimi'ne|girisimine|"
    r"firmasına|firması'na|firmasina|"
    r"a\.ş\.'?ne|ltd\.\s*şti\.'?ne|idare'?ye|yüklenici'?ye|yuklenici'?ye)\s*$"
)
_RE_JOINT_TITLE = re.compile(
    r"(?i)\b(?:toplantı\s+tutanağı|toplanti\s+tutanagi|müşterek\s+tespit|musterek\s+tespit|"
    r"yer\s+teslim\s+tutanağı|yer\s+teslim\s+tutanagi|geçici\s+kabul\s+tutanağı|"
    r"kesin\s+kabul\s+tutanağı|iş\s+bitirme\s+tutanağı|saha\s+tespit\s+tutanağı|"
    r"mutabakat\s+tutanağı|tespit\s+tutanağı)\b"
)
_RE_HAKEDIS_DOC = re.compile(
    r"(?i)\b(?:hakediş\s+(?:özeti|raporu|icmali|kapağı)|yeşil\s+defter|metraj\s+icmali)\b"
)


def classify_sender_role_and_type(
    md_text: str,
    *,
    filename: str = "",
    doc_no: Optional[str] = None,
    subject: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Klasör ipucu olmadan (karma klasörlerde) antet, muhatap yönü, evrak numarası,
    imza/kapanış bloğu ve dosya adından gönderen tarafı ve belge türünü çoklu sinyalle tespit eder.

    Döndürür:
        {"sender_role": "contractor"|"administration"|"consultant"|"joint"|None,
         "doc_type": "yuklenici_yazisi"|"idare_cevabi"|"musavir_yazisi"|"tutanak"|"hakedis",
         "confidence": float (0.0..1.0),
         "reasons": List[str]}
    """
    from utils.text_tr import ascii_fold, tr_lower

    text = md_text or ""
    head = text[:2000]
    tail = text[-1600:] if len(text) > 1600 else text
    # Sayfa 1 sonu (uzun ekli PDF'lerde üst yazının imzası sayfa 1-2'de olur)
    page1_tail = text[max(0, min(len(text), 4000) - 1600):min(len(text), 4000)]
    closing = page1_tail + "\n" + tail

    head_fold = ascii_fold(head)
    closing_fold = ascii_fold(closing)
    fname_fold = ascii_fold(filename or "")
    subj_fold = ascii_fold(subject or "")
    docno_str = (doc_no or "").strip()

    scores: Dict[str, float] = {
        "contractor": 0.0,
        "administration": 0.0,
        "consultant": 0.0,
        "joint": 0.0,
    }
    reasons: List[str] = []

    # 1. Evrak numarası (en yüksek güvenilirlikli sinyal)
    docno_probe = f"{docno_str} {filename or ''}"
    if _RE_EBYS_ADMIN_DOCNO.search(docno_probe):
        scores["administration"] += 4.5
        reasons.append("evrak_no:EBYS/Idare")
    if _RE_CONSULTANT_DOCNO.search(docno_probe):
        scores["consultant"] += 4.0
        reasons.append("evrak_no:Musavir")
    if _RE_CONTRACTOR_DOCNO.search(docno_probe):
        scores["contractor"] += 4.0
        reasons.append("evrak_no:Yuklenici")

    # 2. Üst yazı satırlarını antet vs muhatap olarak ayır
    head_lines = [ln.strip(" #*-_|:") for ln in head.splitlines() if ln.strip(" #*-_|:")]
    letterhead_lines: List[str] = []
    recipient_lines: List[str] = []
    for ln in head_lines[:24]:
        ln_low = tr_lower(ln)
        if re.match(r"^(?:kaynak|sayfa|---)", ln_low):
            continue
        if _RE_DATIVE_RECIPIENT.search(ln) or re.match(r"^(?:sayın|sayin|dağıtım|dagitim)\b", ln_low):
            recipient_lines.append(ln)
            continue
        if len(letterhead_lines) < 8 and not re.match(r"^(?:say[ıi]|tarih|konu|ilgi)\s*[:\-]", ln_low):
            letterhead_lines.append(ln)

    lh_fold = ascii_fold("\n".join(letterhead_lines))
    rc_fold = ascii_fold("\n".join(recipient_lines))

    # Antet (gönderen) sinyalleri
    has_tc_admin_lh = (
        ("t.c." in lh_fold or "turkiye cumhuriyeti" in lh_fold or "buyuksehir" in lh_fold or "bakanligi" in lh_fold)
        and any(k in lh_fold for k in ("belediye", "bakanli", "mudurlug", "baskanli", "rayli sistem", "altyapi", "valilig"))
    )
    if has_tc_admin_lh:
        scores["administration"] += 4.5
        reasons.append("antet:T.C./Idare")

    if any(k in lh_fold for k in ("musavir", "danisman", "kontrolluk", "proje kontrol", "emay", "yuksel proje", "prota", "systra", "egis", "tumas")):
        scores["consultant"] += 4.0
        reasons.append("antet:Musavir/Kontrolluk")

    if any(k in lh_fold for k in ("ortak girisim", "adi ortakl", "konsorsiyum", "yuklenici", "taahhut", "insaat", "alstom", "siemens", "thales", "hitachi", "a.s.", "ltd.")):
        # Müşavir şirket adı da A.Ş. içerebileceğinden müşavir anteti yoksa yükleniciye yaz
        if not any(k in lh_fold for k in ("musavir", "danisman", "kontrolluk")):
            scores["contractor"] += 3.0
            reasons.append("antet:Yuklenici/Firma")

    # Muhatap (alıcı) yönü sinyalleri — muhatap olan taraf gönderen değildir
    if any(k in rc_fold for k in ("belediye", "baskanligina", "mudurlugune", "rayli sistem", "idareye", "bakanligina")):
        if not has_tc_admin_lh:
            scores["administration"] -= 3.0
            scores["contractor"] += 1.0
            reasons.append("muhatap:Idare")
    if any(k in rc_fold for k in ("musavirligine", "danismanligina", "kontrollugune", "proje kontrol")):
        scores["consultant"] -= 2.5
        if not has_tc_admin_lh:
            scores["contractor"] += 1.5
        reasons.append("muhatap:Musavir")
    if any(k in rc_fold for k in ("ortak girisimine", "adi ortakligina", "yukleniciye", "firmasina", "a.s.'ne", "a.s.ne", "konsorsiyum")):
        scores["contractor"] -= 3.0
        if not has_tc_admin_lh:
            scores["consultant"] += 1.0
        else:
            scores["administration"] += 1.0
        reasons.append("muhatap:Yuklenici")

    # 3. İmza ve bürokratik kapanış bloğu
    if any(k in closing_fold for k in ("baskan a.", "daire baskani", "sube muduru", "genel sekreter", "belediye baskani", "idare yetkilisi")):
        scores["administration"] += 3.5
        reasons.append("imza:Idare")
    if any(k in closing_fold for k in ("5070 sayili elektronik imza", "elektronik imza ile imzalanmistir", "e-imzalidir")) and has_tc_admin_lh:
        scores["administration"] += 1.5
        reasons.append("imza:e-imza")
    if any(k in closing_fold for k in ("kontrol amiri", "kontrolluk teskilat", "musavir proje muduru", "musavirlik")):
        scores["consultant"] += 3.0
        reasons.append("imza:Musavir")
    if any(k in closing_fold for k in ("yuklenici yetkilisi", "ortak girisimi", "proje direktoru")) and "musavir" not in closing_fold:
        scores["contractor"] += 2.0
        reasons.append("imza:Yuklenici")

    has_arz = bool(re.search(r"\barz\s+eder(?:im|iz)\b", closing_fold))
    has_rica = bool(re.search(r"\brica\s+eder(?:im|iz)\b", closing_fold))
    if has_arz and not has_rica:
        scores["contractor"] += 1.2
        scores["consultant"] += 0.6
        reasons.append("kapanis:arz")
    elif has_rica and not has_arz:
        scores["administration"] += 1.5
        scores["consultant"] += 0.8
        reasons.append("kapanis:rica")

    # 4. Ortak Tutanak & Hakediş tespiti
    is_formal_letter = bool(recipient_lines) or has_arz or has_rica
    has_joint_title = bool(_RE_JOINT_TITLE.search(head) or "tutanak" in fname_fold or "tutanak" in subj_fold)
    if has_joint_title and not is_formal_letter:
        scores["joint"] += 6.5
        reasons.append("tur:OrtakTutanak")
        if all(k in closing_fold for k in ("idare", "yuklenici")):
            scores["joint"] += 2.0
            reasons.append("imza:CokTarafliTutanak")
    elif _RE_JOINT_TITLE.search(head) and all(k in closing_fold for k in ("idare", "yuklenici")):
        scores["joint"] += 6.0
        reasons.append("imza:CokTarafliTutanak")

    # 5. Dosya adı ipuçları (ikincil destek)
    if any(k in fname_fold for k in ("musavir", "danisman", "kontrolluk")):
        scores["consultant"] += 2.5
        reasons.append("dosya_adi:Musavir")
    if any(k in fname_fold for k in ("idare", "ibb", "belediye", "olur", "baskanlik")):
        scores["administration"] += 2.0
        reasons.append("dosya_adi:Idare")
    if any(k in fname_fold for k in ("yuklenici", "yuk_", "alstom", "dilekce")):
        scores["contractor"] += 2.0
        reasons.append("dosya_adi:Yuklenici")

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    best_role, best_score = ranked[0]
    second_score = ranked[1][1]
    margin = best_score - second_score

    if best_score < 1.0:
        detected_role: Optional[str] = None
        role_conf = 0.0
    else:
        detected_role = best_role
        if best_score >= 4.5 and margin >= 2.5:
            role_conf = 0.95
        elif best_score >= 3.0 and margin >= 1.5:
            role_conf = 0.88
        elif best_score >= 2.0 and margin >= 0.8:
            role_conf = 0.68
        else:
            role_conf = 0.45

    # Belge türü eşlemesi
    if _RE_HAKEDIS_DOC.search(head) and not is_formal_letter:
        detected_type = "hakedis"
    elif "hakedis" in fname_fold and not is_formal_letter:
        detected_type = "hakedis"
    elif detected_role == "joint":
        detected_type = "tutanak"
    elif detected_role == "administration":
        detected_type = "idare_cevabi"
    elif detected_role == "consultant":
        detected_type = "musavir_yazisi"
    else:
        detected_type = "yuklenici_yazisi"

    return {
        "sender_role": detected_role,
        "doc_type": detected_type,
        "confidence": round(role_conf, 3),
        "reasons": reasons,
    }


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


def _extract_clean_summary(md_text: str, max_chars: int = 420) -> str:
    """Antet/Tarih/Sayı/Sayfa başlıklarını atlayıp yazının gerçek gövde paragrafından özet çıkarır."""
    if not md_text:
        return ""
    body_lines: List[str] = []
    started = False
    for raw_ln in md_text.splitlines():
        ln = raw_ln.strip()
        if not ln:
            continue
        low = ln.lower()
        if ln.startswith("#") and ("kaynak:" in low or "sayfa " in low or "---" in low):
            continue
        if not started:
            if re.match(r"^(?:tarih|say[ıi1l]|konu|[iıİ]lgi|ref(?:erans)?|evrak\s*no|dağıtım|dagitim)\s*[:\-]", low):
                continue
            if _RE_DATIVE_RECIPIENT.search(ln) or re.match(r"^(?:t\.c\.|sayın|sayin)\b", low):
                continue
            # Tümü büyük harfli kısa antet satırlarını atla
            if len(ln) <= 75 and ln == ln.upper() and not re.search(r"[.?!]", ln):
                continue
            started = True
        body_lines.append(ln)
        if sum(len(x) + 1 for x in body_lines) >= max_chars:
            break
    joined = re.sub(r"\s+", " ", " ".join(body_lines)).strip()
    if len(joined) < 25:
        joined = re.sub(r"\s+", " ", md_text[:max_chars]).strip()
    return joined[:max_chars]


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

    # --- Gönderen rolü ve belge türü ---
    role_reasons: List[str] = []
    if sender_role_hint:
        sender_role, role_conf = sender_role_hint, 1.0
        effective_doc_type = doc_type if doc_type and doc_type != "auto" else (
            "idare_cevabi" if sender_role == "administration"
            else ("musavir_yazisi" if sender_role == "consultant"
                  else ("tutanak" if sender_role == "joint" else "yuklenici_yazisi"))
        )
    else:
        cls = classify_sender_role_and_type(
            md_text,
            filename=filename,
            doc_no=doc_no,
            subject=subject,
        )
        sender_role = cls["sender_role"]
        role_conf = cls["confidence"]
        role_reasons = cls["reasons"]
        effective_doc_type = cls["doc_type"] if doc_type in (None, "", "auto") else doc_type
    confidences.append(role_conf)

    confidence = round(sum(confidences) / len(confidences), 3) if confidences else 0.0
    auto = bool(
        doc_date
        and doc_no
        and sender_role
        and ((sender_role_hint and date_conf >= 1.0) or (role_conf >= 0.85 and date_conf >= 0.9))
    )

    return {
        "card": {
            "doc_date": doc_date,
            "doc_no": doc_no,
            "subject": subject,
            "ilgi_raw": ilgi_raw,
            "sender_role": sender_role,
            "doc_type": effective_doc_type,
            "evidence_weight": _evidence_weight_for(sender_role, effective_doc_type),
            "review_status": "auto_approved" if auto else "pending_review",
            "extraction_confidence": confidence,
            "summary": _extract_clean_summary(md_text),
        },
        "spans": spans,
        "ilgi_refs": ilgi_refs,
        "role_reasons": role_reasons,
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

        from utils.config import GOOGLE_API_KEY, GOOGLE_MODEL_NAME

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
                model=GOOGLE_MODEL_NAME,
                messages=[{"role": "user", "content": md_text[:max_chars]}],
                response_model=CardEnrichment,
            )
        except Exception:
            # Yapılandırılmış çıktı modu bu modelde desteklenmiyorsa araç çağrısı modu
            i_client = instructor.from_genai(client=client, mode=instructor.Mode.GENAI_TOOLS)
            enriched = i_client.chat.completions.create(
                model=GOOGLE_MODEL_NAME,
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

        from utils.config import GOOGLE_API_KEY, GOOGLE_MODEL_NAME

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
            model_id=GOOGLE_MODEL_NAME,
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
