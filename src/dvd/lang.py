"""Language codes. DVD-Video stores two-letter ISO 639-1 codes; sources usually carry ISO 639-2."""

from __future__ import annotations

# ISO 639-2 (bibliographic and terminology forms) -> ISO 639-1, for languages likely on a disc.
_ISO639_2_TO_1 = {
    "ara": "ar", "aze": "az", "bul": "bg", "cat": "ca", "ces": "cs", "cze": "cs",
    "chi": "zh", "zho": "zh", "dan": "da", "deu": "de", "ger": "de", "ell": "el",
    "gre": "el", "eng": "en", "est": "et", "eus": "eu", "baq": "eu", "fas": "fa",
    "per": "fa", "fin": "fi", "fra": "fr", "fre": "fr", "glg": "gl", "heb": "he",
    "hin": "hi", "hrv": "hr", "hun": "hu", "hye": "hy", "arm": "hy", "ind": "id",
    "isl": "is", "ice": "is", "ita": "it", "jpn": "ja", "kat": "ka", "geo": "ka",
    "kaz": "kk", "kor": "ko", "kur": "ku", "lav": "lv", "lit": "lt", "mkd": "mk",
    "mac": "mk", "msa": "ms", "may": "ms", "nld": "nl", "dut": "nl", "nor": "no",
    "nob": "nb", "nno": "nn", "pol": "pl", "por": "pt", "ron": "ro", "rum": "ro",
    "rus": "ru", "slk": "sk", "slo": "sk", "slv": "sl", "spa": "es", "sqi": "sq",
    "alb": "sq", "srp": "sr", "swe": "sv", "tha": "th", "tur": "tr", "ukr": "uk",
    "urd": "ur", "uzb": "uz", "vie": "vi",
}  # fmt: skip


def to_dvd_code(code: str | None) -> str | None:
    """Normalise a language code to ISO 639-1; None if it cannot be mapped."""
    if not code:
        return None
    code = code.strip().lower()
    if len(code) == 2 and code.isalpha():
        return code
    return _ISO639_2_TO_1.get(code)
