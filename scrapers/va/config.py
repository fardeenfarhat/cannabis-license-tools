"""Virginia city/platform configuration for the cannabis scraper."""

from datetime import date, timedelta
from ..types import CityConfig, Platform

KEYWORDS = ["cannabis", "cannabis retail", "cannabis license"]

# Rolling 1-year window ending today
_today = date.today()
START_DATE = (_today - timedelta(days=365)).strftime("%Y-%m-%d")
END_DATE   = _today.strftime("%Y-%m-%d")


# ── AgendaCenter sites ────────────────────────────────────────────────────────
CITIES: list[CityConfig] = [
    # ── Independent cities ────────────────────────────────────────────────────
    CityConfig("Waynesboro",       Platform.AGENDACENTER, "https://www.waynesboro.va.us"),
    CityConfig("Chesapeake",       Platform.AGENDACENTER, "https://www.cityofchesapeake.net"),
    CityConfig("Colonial Heights", Platform.AGENDACENTER, "https://www.colonialheightsva.gov"),
    CityConfig("Fredericksburg",   Platform.AGENDACENTER, "https://www.fredericksburgva.gov"),
    CityConfig("Norfolk",          Platform.AGENDACENTER, "https://www.norfolk.gov"),
    CityConfig("Lynchburg",        Platform.AGENDACENTER, "https://www.lynchburgva.gov"),
    CityConfig("Charlottesville",  Platform.AGENDACENTER, "https://www.charlottesville.gov"),
    CityConfig("Hopewell",         Platform.AGENDACENTER, "https://www.hopewellva.gov"),
    CityConfig("Emporia",          Platform.AGENDACENTER, "https://www.ci.emporia.va.us"),
    CityConfig("Martinsville",     Platform.AGENDACENTER, "https://www.martinsville-va.gov"),
    CityConfig("Williamsburg",     Platform.AGENDACENTER, "https://www.williamsburgva.gov"),
    CityConfig("Bristol",          Platform.AGENDACENTER, "https://www.bristolva.gov"),
    # ── Counties ──────────────────────────────────────────────────────────────
    CityConfig("Middlesex County",    Platform.AGENDACENTER, "https://www.co.middlesex.va.us"),
    CityConfig("Cumberland County",   Platform.AGENDACENTER, "https://www.cumberlandcounty.virginia.gov"),
    CityConfig("Madison County",      Platform.AGENDACENTER, "https://www.madisonco.virginia.gov"),
    CityConfig("Henry County",        Platform.AGENDACENTER, "https://www.henrycountyva.gov"),
    CityConfig("Roanoke County",      Platform.AGENDACENTER, "https://www.roanokecountyva.gov"),
    CityConfig("Chesterfield County", Platform.AGENDACENTER, "https://www.chesterfield.gov"),
    CityConfig("Shenandoah County",   Platform.AGENDACENTER, "https://www.shenandoahcountyva.gov"),
    CityConfig("Appomattox County",   Platform.AGENDACENTER, "https://www.appomattoxcountyva.gov"),
    CityConfig("King William County", Platform.AGENDACENTER, "https://www.kwc.gov"),
    CityConfig("Essex County",        Platform.AGENDACENTER, "https://www.essexva.gov"),
    CityConfig("Salem",               Platform.AGENDACENTER, "https://www.salemva.gov"),
    CityConfig("Norton",              Platform.AGENDACENTER, "https://www.nortonva.org"),
    CityConfig("Wythe County",        Platform.AGENDACENTER, "https://www.wytheco.org"),
    CityConfig("Botetourt County",    Platform.AGENDACENTER, "https://www.botetourtva.gov"),
    CityConfig("Franklin County",     Platform.AGENDACENTER, "https://www.franklincountyva.gov"),
    CityConfig("Pittsylvania County", Platform.AGENDACENTER, "https://www.pittsylvaniacountyva.gov"),
    CityConfig("New Kent County",     Platform.AGENDACENTER, "https://www.newkent-va.us"),
    CityConfig("Halifax County",      Platform.AGENDACENTER, "https://www.halifaxcountyva.gov"),
    CityConfig("Mecklenburg County",  Platform.AGENDACENTER, "https://www.mecklenburgva.com"),
    CityConfig("Surry County",        Platform.AGENDACENTER, "https://www.surrycountyva.gov"),
    CityConfig("Warren County",       Platform.AGENDACENTER, "https://www.warrencountyva.gov"),
    CityConfig("Craig County",        Platform.AGENDACENTER, "https://va-craigcounty.civicplus.com"),
    CityConfig("Grayson County",      Platform.AGENDACENTER, "https://www.graysoncountyva.gov"),
    CityConfig("Patrick County",      Platform.AGENDACENTER, "https://www.co.patrick.va.us"),
    CityConfig("Wise County",         Platform.AGENDACENTER, "https://www.wisecounty.org"),
    CityConfig("Westmoreland County", Platform.AGENDACENTER, "https://va-westmorelandcounty.civicplus.com"),
    # ── Regional bodies ───────────────────────────────────────────────────────
    CityConfig("Hampton Roads PDC",   Platform.AGENDACENTER, "https://www.hrpdcva.gov"),

    # ── civic-scraper (CivicPlus va-*.civicplus.com) ──────────────────────────
    CityConfig("va-bedford",                     Platform.CIVIC_SCRAPER, "http://va-bedford.civicplus.com/AgendaCenter"),
    CityConfig("va-bristol",                     Platform.CIVIC_SCRAPER, "http://va-bristol.civicplus.com/AgendaCenter"),
    CityConfig("va-campbellcounty",              Platform.CIVIC_SCRAPER, "http://va-campbellcounty.civicplus.com/AgendaCenter"),
    CityConfig("va-campbellcountyed",            Platform.CIVIC_SCRAPER, "http://va-campbellcountyed.civicplus.com/AgendaCenter"),
    CityConfig("va-carolinecounty",              Platform.CIVIC_SCRAPER, "http://va-carolinecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-charlescitycounty2",          Platform.CIVIC_SCRAPER, "http://va-charlescitycounty2.civicplus.com/AgendaCenter"),
    CityConfig("va-colonialheights",             Platform.CIVIC_SCRAPER, "http://va-colonialheights.civicplus.com/AgendaCenter"),
    CityConfig("va-dinwiddiecounty",             Platform.CIVIC_SCRAPER, "http://va-dinwiddiecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-fallschurch",                 Platform.CIVIC_SCRAPER, "http://va-fallschurch.civicplus.com/AgendaCenter"),
    CityConfig("va-fredericksburg",              Platform.CIVIC_SCRAPER, "http://va-fredericksburg.civicplus.com/AgendaCenter"),
    CityConfig("va-fredericksburged",            Platform.CIVIC_SCRAPER, "http://va-fredericksburged.civicplus.com/AgendaCenter"),
    CityConfig("va-frontroyal",                  Platform.CIVIC_SCRAPER, "http://va-frontroyal.civicplus.com/AgendaCenter"),
    CityConfig("va-gloucestercounty",            Platform.CIVIC_SCRAPER, "http://va-gloucestercounty.civicplus.com/AgendaCenter"),
    CityConfig("va-goochlandcounty",             Platform.CIVIC_SCRAPER, "http://va-goochlandcounty.civicplus.com/AgendaCenter"),
    CityConfig("va-hampton",                     Platform.CIVIC_SCRAPER, "http://va-hampton.civicplus.com/AgendaCenter"),
    CityConfig("va-hanovercounty",               Platform.CIVIC_SCRAPER, "http://va-hanovercounty.civicplus.com/AgendaCenter"),
    CityConfig("va-kinggeorgecounty",            Platform.CIVIC_SCRAPER, "http://va-kinggeorgecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-loudouncounty",               Platform.CIVIC_SCRAPER, "http://va-loudouncounty.civicplus.com/AgendaCenter"),
    CityConfig("va-louisacounty",                Platform.CIVIC_SCRAPER, "http://va-louisacounty.civicplus.com/AgendaCenter"),
    CityConfig("va-manassas",                    Platform.CIVIC_SCRAPER, "http://va-manassas.civicplus.com/AgendaCenter"),
    CityConfig("va-newportnews",                 Platform.CIVIC_SCRAPER, "http://va-newportnews.civicplus.com/AgendaCenter"),
    CityConfig("va-nvrc2",                       Platform.CIVIC_SCRAPER, "http://va-nvrc2.civicplus.com/AgendaCenter"),
    CityConfig("va-orangecounty",                Platform.CIVIC_SCRAPER, "http://va-orangecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-pagecounty",                  Platform.CIVIC_SCRAPER, "http://va-pagecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-petersburg",                  Platform.CIVIC_SCRAPER, "http://va-petersburg.civicplus.com/AgendaCenter"),
    CityConfig("va-poquoson",                    Platform.CIVIC_SCRAPER, "http://va-poquoson.civicplus.com/AgendaCenter"),
    CityConfig("va-portsmouth",                  Platform.CIVIC_SCRAPER, "http://va-portsmouth.civicplus.com/AgendaCenter"),
    CityConfig("va-powhatancounty",              Platform.CIVIC_SCRAPER, "http://va-powhatancounty.civicplus.com/AgendaCenter"),
    CityConfig("va-purcellville2",               Platform.CIVIC_SCRAPER, "http://va-purcellville2.civicplus.com/AgendaCenter"),
    CityConfig("va-radford",                     Platform.CIVIC_SCRAPER, "http://va-radford.civicplus.com/AgendaCenter"),
    CityConfig("va-roanoke",                     Platform.CIVIC_SCRAPER, "http://va-roanoke.civicplus.com/AgendaCenter"),
    CityConfig("va-rockbridgecounty",            Platform.CIVIC_SCRAPER, "http://va-rockbridgecounty.civicplus.com/AgendaCenter"),
    CityConfig("va-rockinghamcounty",            Platform.CIVIC_SCRAPER, "http://va-rockinghamcounty.civicplus.com/AgendaCenter"),
    CityConfig("va-russellcounty",               Platform.CIVIC_SCRAPER, "http://va-russellcounty.civicplus.com/AgendaCenter"),
    CityConfig("va-rvra",                        Platform.CIVIC_SCRAPER, "http://va-rvra.civicplus.com/AgendaCenter"),
    CityConfig("va-spotsylvaniacounty",          Platform.CIVIC_SCRAPER, "http://va-spotsylvaniacounty.civicplus.com/AgendaCenter"),
    CityConfig("va-staffordcounty3",             Platform.CIVIC_SCRAPER, "http://va-staffordcounty3.civicplus.com/AgendaCenter"),
    CityConfig("va-suffolk",                     Platform.CIVIC_SCRAPER, "http://va-suffolk.civicplus.com/AgendaCenter"),
    CityConfig("va-wata",                        Platform.CIVIC_SCRAPER, "http://va-wata.civicplus.com/AgendaCenter"),
    CityConfig("va-waynesboro",                  Platform.CIVIC_SCRAPER, "http://va-waynesboro.civicplus.com/AgendaCenter"),
    CityConfig("va-westernvirginiaregionaljail", Platform.CIVIC_SCRAPER, "http://va-westernvirginiaregionaljail.civicplus.com/AgendaCenter"),
    CityConfig("va-yorkcounty",                  Platform.CIVIC_SCRAPER, "http://va-yorkcounty.civicplus.com/AgendaCenter"),
    CityConfig("va-yorkcountyed",                Platform.CIVIC_SCRAPER, "http://va-yorkcountyed.civicplus.com/AgendaCenter"),

    # ── Legistar cities ───────────────────────────────────────────────────────
    CityConfig("Richmond",             Platform.LEGISTAR, "https://richmondva.legistar.com",      legistar_client="RichmondVA"),
    CityConfig("Alexandria",           Platform.LEGISTAR, "https://alexandria.legistar.com",      legistar_client="Alexandria"),
    CityConfig("Hampton",              Platform.LEGISTAR, "https://hampton.legistar.com",         legistar_client="HamptonVA"),
    CityConfig("Harrisonburg",         Platform.LEGISTAR, "https://harrisonburg-va.legistar.com", legistar_client="harrisonburg-va"),
    CityConfig("Albemarle County",     Platform.LEGISTAR, "https://albemarle.legistar.com",       legistar_client="albemarle"),
    CityConfig("Town of Vienna",       Platform.LEGISTAR, "https://vienna-va.legistar.com",       legistar_client="vienna-va"),
    CityConfig("Brunswick County",     Platform.LEGISTAR, "https://brunswickcounty.legistar.com", legistar_client="BrunswickCounty"),
    CityConfig("Petersburg (Legistar)",Platform.LEGISTAR, "https://petersburg.legistar.com",      legistar_client="Petersburg"),

    # ── CivicWeb cities ───────────────────────────────────────────────────────
    CityConfig("Williamsburg",       Platform.CIVICWEB, "https://williamsburg.civicweb.net"),
    CityConfig("Winchester",         Platform.CIVICWEB, "https://winchesterva.civicweb.net"),
    CityConfig("Newport News",       Platform.CIVICWEB, "https://nngov.civicweb.net"),
    CityConfig("Lancaster County",   Platform.CIVICWEB, "https://lancova.civicweb.net"),
    CityConfig("Lexington",          Platform.CIVICWEB, "https://lexingtonva.civicweb.net"),
    CityConfig("Northampton County", Platform.CIVICWEB, "https://co-northampton-va.community.highbond.com"),

    # ── CivicClerk cities ─────────────────────────────────────────────────────
    CityConfig("Petersburg",          Platform.CIVICCLERK, "https://petersburgva.portal.civicclerk.com"),
    CityConfig("Danville",            Platform.CIVICCLERK, "https://danvilleva.portal.civicclerk.com"),
    CityConfig("Amherst County",      Platform.CIVICCLERK, "https://amherstcova.portal.civicclerk.com"),
    CityConfig("Augusta County",      Platform.CIVICCLERK, "https://augustacova.portal.civicclerk.com"),
    CityConfig("Bedford County",      Platform.CIVICCLERK, "https://bedfordva.portal.civicclerk.com"),
    CityConfig("Frederick County",    Platform.CIVICCLERK, "https://frederickco.portal.civicclerk.com"),
    CityConfig("Greene County",       Platform.CIVICCLERK, "https://greenecova.portal.civicclerk.com"),
    CityConfig("Isle of Wight County",Platform.CIVICCLERK, "https://isleofwightcova.portal.civicclerk.com"),
    CityConfig("James City County",   Platform.CIVICCLERK, "https://jamescitycova.portal.civicclerk.com"),
    CityConfig("Mathews County",      Platform.CIVICCLERK, "https://mathewscova.portal.civicclerk.com"),
    CityConfig("Scott County",        Platform.CIVICCLERK, "https://scottcova.portal.civicclerk.com"),
]


def cities_for_platform(platform: Platform) -> list[CityConfig]:
    return [c for c in CITIES if c.platform == platform]
