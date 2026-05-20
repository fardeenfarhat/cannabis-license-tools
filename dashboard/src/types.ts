export interface RfpHit {
  id: number;
  municipality: string;
  county: string;
  monitor_url: string;
  rfp_title: string;
  deadline: string;
  application_deadline: string;
  questions_deadline: string;
  license_types: string;
  confidence: 'high' | 'medium' | 'low';
  snippet: string;
  first_seen: string;
}

export interface FirstRunRow {
  town: string;
  date: string;
  summary: string;
}

export interface Appearance {
  board: string;
  matter: string;
  date: string;
}

export interface Attorney {
  name: string;
  firm: string;
  email: string;
  phone: string;
  tier: 'A' | 'B' | 'C';
  score: number;
  this_town_wins: number;
  this_town_losses: number;
  cannabis_experience: boolean;
  appearances: Appearance[];
  sources: string[];
  why: string;
}

export interface TopPick {
  name: string;
  firm: string;
  email: string;
  score: number;
  tier: 'A' | 'B' | 'C';
  why: string;
}

export interface CouncilMember {
  name: string;
  role: string;
  current_title: string;
  vote: string;
  friendly: number;
  still_in_office: boolean;
  email: string;
  phone: string;
  source_url: string;
}

export interface Zone {
  name: string;
  cannabis_retail_permitted: boolean;
  confidence: string;
  setbacks: string;
  min_lot_size: string;
}

export interface Signal {
  type: string;
  confidence: string;
  url: string;
  title: string;
  snippet: string;
  application_deadline?: string;
}

export interface AwardedLicense {
  license_status: string;
  licensee: string;
  address: string;
}

export interface DraftEmail {
  to_role: string;
  recipient_name: string;
  recipient_email: string;
  subject: string;
  body: string;
  status: string;
  context_used: string[];
}

export interface DeepDive {
  municipality: string;
  county: string;
  slug: string;
  run_date: string;
  ordinance: {
    found: boolean;
    is_prohibition: boolean;
    url: string;
    title: string;
    ordinance_number: string;
    adopted_date: string;
    allowed_zones: string[];
    cap: string;
    application_fee: string;
    annual_fee: string;
    buffer_schools: string;
    buffer_houses_of_worship: string;
    hours: string;
    tax_rate: string;
  };
  council_votes: {
    members: CouncilMember[];
    yes: number;
    no: number;
    abstain: number;
    vote_source_type: string;
    vote_source_url: string;
    needs_foia: boolean;
  };
  zoning: {
    found: boolean;
    url: string;
    description: string;
    zones: Zone[];
    cannabis_overlay: { overlay_name: string; url: string } | null;
    zoning_map_url: string;
    gis_portal_url: string;
    zones_source: string;
  };
  rfp_signals: {
    found: boolean;
    signals: Signal[];
    awarded_licenses: AwardedLicense[];
    cap_status: { cap: number; awarded: number; slots_open: number; saturated: boolean };
    next_action_date: string;
  };
  attorneys: {
    found: boolean;
    attorneys: Attorney[];
    top_picks: TopPick[];
    town_solicitor: { name: string; firm: string; conflict_note: string } | null;
    needs_foia: boolean;
  };
  draft_emails: DraftEmail[];
}
