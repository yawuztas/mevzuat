import os
from pathlib import Path
from dotenv import load_dotenv

# .env dosyasını yükle
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

# Dizin Yolları
DATA_DIR = BASE_DIR / "data"
GENEL_MEVZUAT_DIR = DATA_DIR / "1_genel_mevzuat_ve_standartlar"
PROJE_EVRAKLARI_DIR = DATA_DIR / "2_proje_evraklari"
YUKLENICI_TALEPLERI_DIR = DATA_DIR / "3_yuklenici_talepleri"
RAPORLAR_DIR = DATA_DIR / "raporlar"

# Geriye dönük uyumluluk takma adları (Alias)
KANUNLAR_DIR = GENEL_MEVZUAT_DIR
YUKLENICI_DIR = YUKLENICI_TALEPLERI_DIR
VECTOR_DB_DIR = BASE_DIR / "vector_db"

# Model ve Aygıt Ayarları
DEVICE = os.getenv("DEVICE", "cuda")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "BAAI/bge-m3")
RERANKER_MODEL_NAME = os.getenv("RERANKER_MODEL_NAME", "BAAI/bge-reranker-v2-m3")

# LLM Ayarları
DEFAULT_LLM_PROVIDER = os.getenv("DEFAULT_LLM_PROVIDER", "google").lower()
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY", "")
GOOGLE_MODEL_NAME = os.getenv("GOOGLE_MODEL_NAME", "gemini-3.5-flash-lite")
ANTHROPIC_MODEL_NAME = os.getenv("ANTHROPIC_MODEL_NAME", "claude-3-7-sonnet-latest")


def get_llm(provider: str | None = None, temperature: float = 0.1):
    """
    Kullanıcının tercihine veya parametreye göre Chat LLM nesnesi döndürür.
    Desteklenen sağlayıcılar: 'anthropic', 'google'
    """
    selected_provider = (provider or DEFAULT_LLM_PROVIDER).lower()

    if selected_provider == "anthropic":
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError(
                "ANTHROPIC_API_KEY .env dosyasında bulunamadı! Lütfen .env dosyasına anahtarınızı ekleyin."
            )
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model_name=ANTHROPIC_MODEL_NAME,
            temperature=temperature,
            max_tokens=4096,
        )

    elif selected_provider == "google":
        api_key = os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError(
                "GOOGLE_API_KEY (veya GEMINI_API_KEY) .env dosyasında bulunamadı! Lütfen .env dosyasına anahtarınızı ekleyin."
            )
        # Ortama aktar
        os.environ["GOOGLE_API_KEY"] = api_key
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=GOOGLE_MODEL_NAME,
            temperature=temperature,
            max_output_tokens=4096,
            max_retries=3,
        )

    else:
        raise ValueError(f"Desteklenmeyen LLM sağlayıcısı: {selected_provider}. ('anthropic' veya 'google' seçiniz)")
