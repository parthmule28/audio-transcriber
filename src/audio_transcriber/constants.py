TARGET_CHUNK_SECONDS = 30
OVERLAP_SECONDS = 1
MAX_CONCURRENT_REQUESTS = 3

ALLOWED_MODELS = (
    "openai/whisper-large-v3-turbo",
    "openai/whisper-large-v3",
)
DEFAULT_MODEL = "openai/whisper-large-v3-turbo"
ZDR_WARNING = (
    "ZDR must be enforced on this API key/account. "
    "The application cannot verify or enforce this for transcription."
)
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
CANONICAL_SAMPLE_RATE = 16000
CANONICAL_CHANNELS = 1
CANONICAL_FORMAT = "wav"
MAX_RATE_LIMIT_RETRIES = 3
RETRY_BASE_DELAY_SECONDS = 2.0
LANGUAGES = (
    "Auto-detect",
    "English",
    "Spanish",
    "French",
    "German",
    "Italian",
    "Portuguese",
    "Dutch",
    "Japanese",
    "Korean",
    "Chinese",
    "Russian",
    "Arabic",
    "Hindi",
)

MIN_BOUNDARY_DEDUP_TOKENS = 3
MAX_BOUNDARY_DEDUP_TOKENS = 20
