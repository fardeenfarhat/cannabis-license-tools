"""Shared helpers used by all scraper agents."""

import re
import sys
import subprocess
from io import BytesIO


def _ensure(*packages):
    for pip_name, import_name in packages:
        try:
            __import__(import_name)
        except ImportError:
            subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "-q"])


_ensure(("pdfplumber", "pdfplumber"), ("pypdf", "pypdf"))

import requests
import pdfplumber
from pypdf import PdfReader


# ── Filename helpers ──────────────────────────────────────────────────────────

def safe_filename(s: str, maxlen: int = 80) -> str:
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789 _-.")
    return "".join(c if c in keep else "_" for c in s)[:maxlen]


def extract_date_from_viewfile_path(path: str) -> str:
    """Pull date like _07142025 from a ViewFile path -> '2025-07-14'."""
    m = re.search(r'_(\d{2})(\d{2})(\d{4})', path)
    if m:
        mo, day, yr = m.groups()
        return f"{yr}-{mo}-{day}"
    return "unknown-date"


# ── PDF helpers ───────────────────────────────────────────────────────────────

def keyword_in_pdf(pdf_bytes: bytes, keywords: list[str]) -> list[str]:
    """Return list of matched keywords found in PDF. pdfplumber primary, pypdf fallback."""
    found: list[str] = []

    try:
        with pdfplumber.open(BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                text = (page.extract_text() or "").lower()
                for kw in keywords:
                    if kw not in found and kw.lower() in text:
                        found.append(kw)
                if len(found) == len(keywords):
                    break
        if found:
            return found
    except Exception:
        pass

    try:
        reader = PdfReader(BytesIO(pdf_bytes))
        for page in reader.pages:
            text = (page.extract_text() or "").lower()
            for kw in keywords:
                if kw not in found and kw.lower() in text:
                    found.append(kw)
            if len(found) == len(keywords):
                break
    except Exception:
        pass

    return found


def download_pdf(url: str, session: requests.Session, timeout: int = 60) -> bytes | None:
    """Download URL and return bytes only if it looks like a valid PDF."""
    try:
        r = session.get(url, timeout=timeout)
        if r.ok and len(r.content) > 500 and r.content[:4] == b"%PDF":
            return r.content
    except Exception:
        pass
    return None


# ── Session factory ───────────────────────────────────────────────────────────

def make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})
    return s
