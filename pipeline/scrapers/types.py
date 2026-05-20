"""Shared types for all scraper agents (VA and NJ)."""

import re
from dataclasses import dataclass, field
from enum import Enum


class Platform(Enum):
    AGENDACENTER = "agendacenter"
    CIVIC_SCRAPER = "civic-scraper"
    LEGISTAR = "legistar"
    CIVICWEB = "civicweb"
    CIVICCLERK = "civicclerk"
    IQM2 = "iqm2"
    MUNICODE = "municode"
    CUSTOM_PDF = "custom_pdf"


@dataclass
class CityConfig:
    name: str
    platform: Platform
    url: str                          # base URL or portal URL
    slug: str = ""                    # derived from URL if empty
    legistar_client: str = ""         # only for LEGISTAR
    extra: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.slug:
            host = self.url.split("//")[-1].split("/")[0]
            host = re.sub(r"^www\.", "", host)
            self.slug = host.split(".")[0]


@dataclass
class Hit:
    city: str
    platform: Platform
    date: str
    doc_type: str          # Minutes, Agenda, Packet, Attachment, Document
    label: str
    url: str
    file_path: str = ""
    confirmed: bool = False
    matched_keywords: list[str] = field(default_factory=list)
