"""
Sub-task 7 — Email Drafter
==============================
Writes 4 outreach emails from the completed workspace:
  E1. Town Clerk       -- "when will the RFP drop / how do we apply?"
  E2. Council Member   -- friendliest voter, relationship-building intro
  E3. Zoning Officer   -- confirm zones, request overlay map PDF
  E4. Top Attorney     -- gauge interest in representing an applicant

Voice is professional-but-direct. Phase 5 Correspondence.ai will voice-match
to the CEO corpus once it arrives; for now drafts are generic but grounded in
real workspace data (ordinance number, zone names, actual appearances).

Returns list of 4 dicts (always 4, even when data is partial):
  [{to_role, recipient_name, recipient_email, subject, body,
    status, context_used}]

status values:
  "Draft"               -- ready for human review
  "Draft -- needs contact"  -- no email address found; human must fill in
"""

import csv
import json
import os
import re
from pathlib import Path

# ---------------------------------------------------------------------------
# Paths / constants
# ---------------------------------------------------------------------------
_CRM_CSV = Path(__file__).parent.parent.parent / "cannabis_hits" / "crm" / "cannabis_crm_enriched.csv"
_OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")

_CRM_ROLE_CLERK   = {"Township Clerk", "Town Clerk", "Borough Clerk", "Municipal Clerk", "City Clerk", "Village Clerk"}
_CRM_ROLE_ZONING  = {"Zoning Officer", "Zoning Official", "Land Use Administrator", "Zoning Administrator"}
_CRM_ROLE_COUNCIL = {"Mayor", "Councilman", "Councilwoman", "Council Member", "Councilmember",
                     "Commissioner", "Trustee", "Alderman", "Alderwoman", "Deputy Mayor"}


# ---------------------------------------------------------------------------
# CRM helpers
# ---------------------------------------------------------------------------

def _load_crm(town: str) -> list[dict]:
    """Return all CRM rows for this municipality (case-insensitive)."""
    if not _CRM_CSV.exists():
        return []
    rows = []
    try:
        with open(_CRM_CSV, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("municipality", "").strip().lower() == town.strip().lower():
                    rows.append(row)
    except Exception:
        pass
    return rows


def _find_clerk(crm_rows: list[dict]) -> dict | None:
    for row in crm_rows:
        if row.get("role", "") in _CRM_ROLE_CLERK:
            return row
    return None


def _find_zoning_officer(crm_rows: list[dict]) -> dict | None:
    for row in crm_rows:
        if row.get("role", "") in _CRM_ROLE_ZONING:
            return row
    return None


def _find_friendliest_council(crm_rows: list[dict], council_votes: list[dict]) -> dict | None:
    """
    Match council_votes entries (from workspace) against CRM rows.
    Returns the CRM row for the member with the highest 'friendly' score,
    preferring those who have an email on file.
    Friendly flag in council_votes is bool/int; higher = more receptive.
    """
    if not council_votes:
        # Fall back to any council member in CRM
        for row in crm_rows:
            if row.get("role", "") in _CRM_ROLE_COUNCIL and row.get("name"):
                return row
        return None

    # Build name->friendly map from workspace
    name_to_friendly: dict[str, int] = {}
    for cv in council_votes:
        name = (cv.get("name") or "").strip()
        friendly = cv.get("friendly", 0)
        if isinstance(friendly, bool):
            friendly = 1 if friendly else 0
        try:
            friendly = int(friendly)
        except (ValueError, TypeError):
            friendly = 0
        if name:
            name_to_friendly[name.lower()] = friendly

    # Match CRM rows to workspace names
    best_row = None
    best_score = -1
    for row in crm_rows:
        if row.get("role", "") not in _CRM_ROLE_COUNCIL:
            continue
        row_name = (row.get("name") or "").strip().lower()
        # Loose match: last-name in row name
        score = 0
        for ws_name, ws_friendly in name_to_friendly.items():
            ws_last = ws_name.split()[-1] if ws_name.split() else ws_name
            if ws_last and ws_last in row_name:
                score = ws_friendly
                break
        if score > best_score or (score == best_score and row.get("email") and best_row and not best_row.get("email")):
            best_score = score
            best_row = row

    return best_row


def _crm_to_contact(row: dict | None) -> tuple[str, str | None]:
    """Return (name, email|None) from a CRM row."""
    if row is None:
        return ("", None)
    name  = (row.get("name") or "").strip()
    email = (row.get("email") or "").strip() or None
    return (name, email)


# ---------------------------------------------------------------------------
# LLM call (house pattern -- gpt-4o-mini, json_object, fallback to template)
# ---------------------------------------------------------------------------

def _llm_draft_email(
    role: str,
    system_prompt: str,
    user_prompt: str,
) -> dict | None:
    """
    Returns {"subject": str, "body": str} or None on any failure.
    Caller is responsible for fallback.
    """
    if not _OPENAI_API_KEY:
        return None
    try:
        import openai
        client = openai.OpenAI(api_key=_OPENAI_API_KEY)
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user",   "content": user_prompt},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
            max_tokens=600,
        )
        data = json.loads(response.choices[0].message.content)
        subject = (data.get("subject") or "").strip()
        body    = (data.get("body")    or "").strip()
        if subject and body:
            return {"subject": subject, "body": body}
    except Exception as e:
        print(f"      [email_drafter] LLM error for {role}: {e}")
    return None


# ---------------------------------------------------------------------------
# Fallback templates (no LLM required)
# ---------------------------------------------------------------------------

def _fallback_clerk(ctx: dict) -> dict:
    town = ctx["town"]
    subj = f"Cannabis Retail RFP Inquiry — {town}"
    body = (
        f"Dear {ctx['recipient_name'] or 'Municipal Clerk'},\n\n"
        f"I hope this note finds you well. My name is [Your Name] and I represent "
        f"a prospective cannabis retail applicant interested in {town}.\n\n"
        f"I am writing to inquire about the timeline and process for the upcoming "
        f"cannabis retail license RFP. Specifically:\n\n"
        f"  1. When is the RFP expected to be released?\n"
        f"  2. Where will the RFP be posted (town website, state portal, etc.)?\n"
        f"  3. Who is the designated point of contact for application questions?\n\n"
        f"Any guidance you can provide would be greatly appreciated.\n\n"
        f"Thank you for your time.\n\nBest regards,\n[Your Name]\n[Organization]\n[Phone]"
    )
    return {"subject": subj, "body": body}


def _fallback_council(ctx: dict) -> dict:
    town   = ctx["town"]
    ord_no = ctx.get("ordinance_number") or "the cannabis ordinance"
    subj = f"Introduction — Cannabis Retail Applicant in {town}"
    body = (
        f"Dear {ctx['recipient_name'] or 'Council Member'},\n\n"
        f"I wanted to reach out and introduce myself. My name is [Your Name] and I represent "
        f"a group exploring a cannabis retail application in {town}.\n\n"
        f"I appreciated {town}'s thoughtful approach to {ord_no}. "
        f"We share the community's interest in a responsible, locally-rooted operation.\n\n"
        f"I would welcome the opportunity to connect briefly at your convenience — "
        f"even a short call to understand the community's priorities would be invaluable.\n\n"
        f"Thank you for your public service.\n\nBest regards,\n[Your Name]\n[Organization]\n[Phone]"
    )
    return {"subject": subj, "body": body}


def _fallback_zoning(ctx: dict) -> dict:
    town  = ctx["town"]
    zones = ctx.get("allowed_zones") or "the permitted zones"
    subj = f"Cannabis Retail Zoning Inquiry — {town}"
    body = (
        f"Dear {ctx['recipient_name'] or 'Zoning Officer'},\n\n"
        f"My name is [Your Name] and I am researching a potential cannabis retail "
        f"application in {town}.\n\n"
        f"I understand that cannabis retail is permitted in {zones}. "
        f"I have a few questions:\n\n"
        f"  1. Could you confirm which specific zones or overlay districts allow Class 5 retail?\n"
        f"  2. Is a zoning overlay map or GIS layer available that shows eligible parcels?\n"
        f"  3. Are there any pending zone amendments that might affect eligibility?\n\n"
        f"Any materials you can share would be very helpful as we evaluate sites.\n\n"
        f"Thank you for your time.\n\nBest regards,\n[Your Name]\n[Organization]\n[Phone]"
    )
    return {"subject": subj, "body": body}


def _fallback_attorney(ctx: dict) -> dict:
    town  = ctx["town"]
    atty  = ctx.get("attorney_name") or "your firm"
    subj = f"Cannabis Retail Representation Inquiry — {town}"
    body = (
        f"Dear {ctx['recipient_name'] or 'Counsel'},\n\n"
        f"My name is [Your Name] and I represent a group preparing a cannabis retail "
        f"license application in {town}.\n\n"
        f"I came across {atty}'s work before {town}'s boards and wanted to reach out "
        f"to gauge your interest and availability to represent an applicant in this process.\n\n"
        f"We are at an early stage and would value a brief introductory call to understand "
        f"your approach and confirm capacity.\n\n"
        f"Please let me know if you are open to connecting.\n\n"
        f"Best regards,\n[Your Name]\n[Organization]\n[Phone]"
    )
    return {"subject": subj, "body": body}


# ---------------------------------------------------------------------------
# Per-email drafters
# ---------------------------------------------------------------------------

def _draft_clerk(town: str, crm_rows: list[dict], workspace: dict) -> dict:
    row   = _find_clerk(crm_rows)
    name, email = _crm_to_contact(row)

    # Context signals
    rfp_signals = workspace.get("rfp_signals") or []
    signal_snippets = [s.get("snippet", "") for s in rfp_signals[:2] if s.get("snippet")]
    ordinance = workspace.get("ordinance") or {}
    ord_no    = ordinance.get("ordinance_number", "")
    adopted   = ordinance.get("adopted_date", "")
    context_urls = [s.get("url") for s in rfp_signals[:3] if s.get("url")]

    ctx = {"town": town, "recipient_name": name}

    system_prompt = (
        "You draft outreach emails for a cannabis retail license applicant in New Jersey. "
        "Use a professional, direct tone. Do NOT use em dashes. Do NOT invent facts. "
        "Only reference the information provided. "
        "Respond with JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    user_prompt = f"""Draft an email from a prospective cannabis retail applicant to the Town Clerk of {town}, NJ.

Recipient: {name or "(name unknown)"}
Email: {email or "(unknown)"}

Context:
- Cannabis ordinance number: {ord_no or "(unknown)"}
- Ordinance adopted: {adopted or "(unknown)"}
- RFP signals found: {"; ".join(signal_snippets) if signal_snippets else "none yet"}

The email should ask:
1. When the cannabis retail RFP is expected to be released
2. Where it will be posted
3. Who is the designated point of contact for applicant questions

Keep it under 180 words. End with: Best regards, [Your Name] / [Organization] / [Phone]
"""

    result = _llm_draft_email("clerk", system_prompt, user_prompt)
    if not result:
        result = _fallback_clerk(ctx)

    return {
        "to_role":         "Town Clerk",
        "recipient_name":  name or None,
        "recipient_email": email,
        "subject":         result["subject"],
        "body":            result["body"],
        "status":          "Draft" if email else "Draft -- needs contact",
        "context_used":    context_urls,
    }


def _draft_council(town: str, crm_rows: list[dict], workspace: dict) -> dict:
    council_votes = workspace.get("council_votes") or []
    row   = _find_friendliest_council(crm_rows, council_votes)
    name, email = _crm_to_contact(row)
    role_title = (row.get("role") or "Council Member") if row else "Council Member"

    ordinance = workspace.get("ordinance") or {}
    ord_no    = ordinance.get("ordinance_number", "")
    adopted   = ordinance.get("adopted_date", "")

    # Find this member's vote record in workspace
    vote_note = ""
    for cv in council_votes:
        cv_name = (cv.get("name") or "").strip().lower()
        if name and cv_name and cv_name.split()[-1] in name.lower():
            vote = cv.get("vote", "")
            if vote:
                vote_note = f"voted {vote} on {ord_no or 'the ordinance'}"
            break

    ctx = {"town": town, "recipient_name": name, "ordinance_number": ord_no}

    system_prompt = (
        "You draft outreach emails for a cannabis retail license applicant in New Jersey. "
        "Use a warm but professional tone. Do NOT use em dashes. Do NOT invent facts. "
        "Only reference the information provided. "
        "Respond with JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    user_prompt = f"""Draft a relationship-building introduction email to a council member in {town}, NJ.

Recipient: {name or "(name unknown)"}, {role_title}
Vote record: {vote_note or "(not available)"}
Ordinance: {ord_no or "(unknown)"}, adopted {adopted or "(unknown)"}

The email should:
- Introduce the writer as a prospective cannabis retail applicant
- Briefly reference the ordinance (number and/or adoption date if known)
- Express interest in understanding community priorities
- Request a short call at the council member's convenience
- NOT include a hard business ask

Keep it under 160 words. End with: Best regards, [Your Name] / [Organization] / [Phone]
"""

    result = _llm_draft_email("council", system_prompt, user_prompt)
    if not result:
        result = _fallback_council(ctx)

    return {
        "to_role":         "Council Member",
        "recipient_name":  name or None,
        "recipient_email": email,
        "subject":         result["subject"],
        "body":            result["body"],
        "status":          "Draft" if email else "Draft -- needs contact",
        "context_used":    [],
    }


def _draft_zoning(town: str, crm_rows: list[dict], workspace: dict) -> dict:
    row   = _find_zoning_officer(crm_rows)
    # Fallback to clerk if no zoning officer in CRM
    if row is None:
        row = _find_clerk(crm_rows)
    name, email = _crm_to_contact(row)
    role_title  = (row.get("role") or "Zoning Officer") if row else "Zoning Officer"

    zoning    = workspace.get("zoning") or {}
    ordinance = workspace.get("ordinance") or {}
    zones     = (
        zoning.get("description")
        or ordinance.get("allowed_zones")
        or "(zones not yet confirmed)"
    )
    overlay_url = zoning.get("url", "")

    ctx = {"town": town, "recipient_name": name, "allowed_zones": zones}

    system_prompt = (
        "You draft outreach emails for a cannabis retail license applicant in New Jersey. "
        "Use a professional, direct tone. Do NOT use em dashes. Do NOT invent facts. "
        "Only reference the information provided. "
        "Respond with JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    user_prompt = f"""Draft an email from a cannabis retail applicant to the zoning official in {town}, NJ.

Recipient: {name or "(name unknown)"}, {role_title}
Cannabis retail allowed zones (from ordinance/zoning research): {zones}
Zoning source URL found: {overlay_url or "(none)"}

The email should ask:
1. Confirm which zones/districts allow Class 5 cannabis retail
2. Whether a zoning map or GIS layer of eligible parcels is available
3. Whether any pending amendments might affect eligibility

Keep it under 160 words. End with: Best regards, [Your Name] / [Organization] / [Phone]
"""

    result = _llm_draft_email("zoning", system_prompt, user_prompt)
    if not result:
        result = _fallback_zoning(ctx)

    return {
        "to_role":         "Zoning Officer",
        "recipient_name":  name or None,
        "recipient_email": email,
        "subject":         result["subject"],
        "body":            result["body"],
        "status":          "Draft" if email else "Draft -- needs contact",
        "context_used":    [overlay_url] if overlay_url else [],
    }


def _draft_attorney(town: str, workspace: dict) -> dict:
    attorneys_result = workspace.get("attorneys") or {}
    top_picks = attorneys_result.get("top_picks") or []
    attorneys = attorneys_result.get("attorneys") or []

    # Prefer top_picks; fall back to first attorney by score
    atty = None
    if top_picks:
        top_name = (top_picks[0].get("name") or "").lower()
        for a in attorneys:
            if (a.get("name") or "").lower() == top_name:
                atty = a
                break
        if not atty and top_picks:
            atty = {"name": top_picks[0].get("name", ""), "firm": top_picks[0].get("firm", "")}
    elif attorneys:
        atty = attorneys[0]

    name  = (atty.get("name")  or "") if atty else ""
    firm  = (atty.get("firm")  or "") if atty else ""
    email = (atty.get("email") or "") if atty else ""
    email = email.strip() or None

    # Pull one real appearance to reference
    appearances = (atty.get("appearances") or []) if atty else []
    appearance_note = ""
    if appearances:
        ap = appearances[0]
        board  = ap.get("board", "")
        matter = ap.get("matter", "")
        date_s = ap.get("date", "")
        if board and matter:
            appearance_note = f"your appearance before the {board} on {matter}" + (f" ({date_s})" if date_s else "")
        elif board:
            appearance_note = f"your work before {town}'s {board}"

    ctx = {
        "town": town,
        "recipient_name": name,
        "attorney_name": f"{name} at {firm}" if firm else name,
    }

    system_prompt = (
        "You draft outreach emails for a cannabis retail license applicant in New Jersey. "
        "Use a professional tone. Do NOT use em dashes. Do NOT invent facts. "
        "Only reference the information provided. "
        "Respond with JSON: {\"subject\": \"...\", \"body\": \"...\"}"
    )
    user_prompt = f"""Draft an email from a cannabis retail applicant to a private-practice attorney in {town}, NJ.

Recipient: {name or "(attorney name unknown)"}{(", " + firm) if firm else ""}
Appearance reference: {appearance_note or "(none available)"}

The email should:
- Introduce the writer as representing a prospective cannabis retail applicant in {town}
- Reference the attorney's local board work if available (use the appearance note)
- Ask whether the attorney has capacity and interest in representing an applicant
- Keep the ask brief and leave room for a call

Keep it under 160 words. End with: Best regards, [Your Name] / [Organization] / [Phone]
"""

    result = _llm_draft_email("attorney", system_prompt, user_prompt)
    if not result:
        result = _fallback_attorney(ctx)

    # Gather source URLs from attorney sources
    sources = (atty.get("sources") or []) if atty else []
    context_urls = [s for s in sources[:2] if s]

    return {
        "to_role":         "Attorney",
        "recipient_name":  name or None,
        "recipient_email": email,
        "subject":         result["subject"],
        "body":            result["body"],
        "status":          "Draft" if email else "Draft -- needs contact",
        "context_used":    context_urls,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def draft_emails(workspace: dict) -> list[dict]:
    """
    Drafts 4 outreach emails from the completed deep-dive workspace.
    Always returns exactly 4 entries.  Individual failures produce a
    fallback template draft rather than raising.

    Args:
        workspace: the full workspace dict from run_deep_dive()

    Returns:
        list of 4 email dicts
    """
    town = (workspace.get("municipality") or "").strip()
    if not town:
        return []

    crm_rows = _load_crm(town)

    drafts = []
    for label, fn in [
        ("clerk",   lambda: _draft_clerk(town, crm_rows, workspace)),
        ("council", lambda: _draft_council(town, crm_rows, workspace)),
        ("zoning",  lambda: _draft_zoning(town, crm_rows, workspace)),
        ("attorney",lambda: _draft_attorney(town, workspace)),
    ]:
        try:
            drafts.append(fn())
        except Exception as e:
            print(f"      [email_drafter] failed to draft {label} email: {e}")
            drafts.append({
                "to_role":         label.title(),
                "recipient_name":  None,
                "recipient_email": None,
                "subject":         f"[draft failed — {label}]",
                "body":            "",
                "status":          "Draft -- error",
                "context_used":    [],
            })

    return drafts
