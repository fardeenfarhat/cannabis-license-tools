"""
Backward-compatibility shim — forwards to scrapers.va.orchestrator.
VA scraper: python -m scrapers.orchestrator --all
NJ scraper: python -m scrapers.nj --all
"""
from .va.orchestrator import main  # noqa: F401

if __name__ == "__main__":
    main()
