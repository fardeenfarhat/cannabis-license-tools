"""
Cannabis meeting-minute scrapers — Virginia and New Jersey.

State entry points:
    python -m scrapers.va  [--all | --agendacenter | --legistar | ...]
    python -m scrapers.nj  [--all | --agendacenter | --civicclerk | ...]

Platform detection (NJ):
    python -m scrapers.nj.detect_platform  [--workers N]
    python -m scrapers.nj.retry_timeouts

Platform engines (shared, state-agnostic):
    scrapers/agendacenter.py
    scrapers/civic_scraper_agent.py
    scrapers/civicclerk.py
    scrapers/civicweb.py
    scrapers/legistar.py
"""
