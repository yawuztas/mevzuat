"""Türkçe metin normalleştirme yardımcıları.

Python'un str.lower() fonksiyonu Türkçe için hatalıdır:
  "İSTASYON".lower() -> "i̇stasyon" (birleşik nokta karakteri ile), "IŞIK".lower() -> "işik".
Bu yüzden anahtar kelime eşleştirmelerinde aşağıdaki fonksiyonlar kullanılmalıdır.
"""

_TR_LOWER_MAP = str.maketrans({"İ": "i", "I": "ı"})
_ASCII_FOLD_MAP = str.maketrans({
    "ç": "c", "ğ": "g", "ı": "i", "ö": "o", "ş": "s", "ü": "u",
    "â": "a", "î": "i", "û": "u",
})


def tr_lower(text: str) -> str:
    """Türkçe kurallarına uygun küçük harfe çevirir (İ→i, I→ı)."""
    return text.translate(_TR_LOWER_MAP).lower()


def ascii_fold(text: str) -> str:
    """Türkçe küçük harfe çevirip Türkçe karakterleri ASCII karşılıklarına indirger.

    Dosya/klasör adı eşleştirmelerinde kullanılır:
      "02.TEKNİK ŞARTNAME İNŞAAT" -> "02.teknik sartname insaat"
      "SÖZLEŞME" -> "sozlesme"
    """
    return tr_lower(text).translate(_ASCII_FOLD_MAP)
