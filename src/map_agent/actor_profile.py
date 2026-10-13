"""Architecture V2 actor light-pull contract, independent of production DB schema."""
from src.map_agent.search_backend import canonical_url

NOT_APPLICABLE = 'Not Applicable'
NOT_CLASSIFIED = 'Not classified'
# The 12 categories and their category types, worded exactly as in the intern
# guide "Actor Mapping: Categories, Category Types, and Link Types".
CATEGORY_TYPES = {
    'University / Academic Institution': [
        'Main Institution', 'Department', 'College / School', 'Research Lab / Center',
        'Tech Transfer Office', 'Professional / Executive Education', 'Accelerator / Incubator',
        'Medical School', 'Applied Facility / Testbed / Field Site', 'Extension / Outreach Program'],
    'Research Center / Institute / Laboratory': [
        'Independent', 'Nonprofit-operated', 'Corporate-operated', 'Government-affiliated'],
    'National Laboratory': [
        'University-Operated / Affiliated', 'Corporate-Operated', 'Consortium-Operated',
        'Government-Direct'],
    'Applied Research Facility / Testbed / Field Site': [
        'Independent', 'Government-operated', 'Corporate-operated', 'Nonprofit-operated'],
    'Hospital / Clinical System / Medical Center': [
        'Independent-Standalone', 'Nonprofit Health System', 'For-Profit Health System',
        'Public or Government Hospital', 'University-Affiliated'],
    'Company / Corporate Actor': [
        'Public Company', 'Private Company', 'SME', 'Subsidiary / Business Unit', 'Joint Venture'],
    'Startup / Emerging Technology Company': [
        'Independent', 'University Spinout', 'Corporate Spinout', 'Accelerator Portfolio Company'],
    'Innovation & Entrepreneurship (E&I) Platform': ['Incubator', 'Accelerator', 'Venture Studio'],
    'Investor / Funding Platform': [
        'Venture Capital Firm', 'Corporate Venture Arm', 'Government Fund',
        'Family Office / Angel Network'],
    'Government Agency / Public Authority': ['Federal', 'State', 'Local / Municipal', 'Public Utility'],
    'Foundation / Nonprofit': [
        'Private Foundation', 'Operating Nonprofit', 'Corporate Foundation', 'Community Foundation'],
    'Association / Consortium / Network': [
        'Trade Association', 'Research Consortium', 'Innovation Consortium',
        'Statewide / Multi-Location Network', 'Professional Network', 'Diaspora Network'],
}
for _types in CATEGORY_TYPES.values():
    _types.append(NOT_APPLICABLE)
CATEGORIES = list(CATEGORY_TYPES)
ALL_CATEGORY_TYPES = list(dict.fromkeys(t for types in CATEGORY_TYPES.values() for t in types))
# Names used before the intern guide renamed three categories. Saved operation
# replays and older maps still carry them.
LEGACY_CATEGORIES = {
    'Innovation Platform / Incubator / Accelerator / Venture Studio':
        'Innovation & Entrepreneurship (E&I) Platform',
    'Investor / VC / Funding Platform': 'Investor / Funding Platform',
    'Industry Association / Consortium / Network': 'Association / Consortium / Network',
}
REGIONS = {
    'Northeast': 'CT ME MA NH NY RI VT',
    'Mid-Atlantic': 'DE MD NJ PA VA WV DC',
    'Southeast': 'AL FL GA KY MS NC SC TN',
    'Midwest / Great Lakes': 'IL IN IA KS MI MN MO NE ND OH SD WI',
    'South Central / Texas Gulf': 'AR LA OK TX',
    'Mountain West / Rocky Mountain': 'AZ CO ID MT NV NM UT WY',
    'West Coast / Pacific': 'AK CA HI OR WA',
}
STATE_NAMES = 'Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|District of Columbia|Florida|Georgia|Hawaii|Idaho|Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming'.split('|')
STATE_CODES = 'AL AK AZ AR CA CO CT DE DC FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY'.split()

def region_for(country, state):
    country = str(country or '').lower().replace('.', '').strip()
    if country not in ('us', 'usa', 'united states', 'united states of america'):
        return ''
    state = str(state or '').strip().lower()
    code = dict(zip((n.lower() for n in STATE_NAMES), STATE_CODES)).get(state, state.upper())
    if state in ('d.c.', 'washington dc', 'washington, d.c.'):
        code = 'DC'
    return next((r for r, codes in REGIONS.items() if code in codes.split()), '')

LIGHT_GUIDANCE = '''For actors use the Architecture V2 light pull only. Assign exactly one supplied category by the organization's main job as it describes itself, never by its funder, sector or fame. Any formal unit run by a university (department, college or school, research lab or center, tech transfer office, executive education, accelerator or incubator, medical school, testbed or field site, extension program) is University / Academic Institution, related "unit of" the university. Research Center, Applied Research Facility and E&I Platform are for independent organizations only. Two exceptions never become University: a hospital or medical center is always Hospital / Clinical System / Medical Center, even when a university runs it; a formally designated national laboratory (on the NSF FFRDC list or chartered as one) is always National Laboratory, even when a university holds the operating contract, related "operated by" the operator. Government funding or agency housing alone is not designation; such a lab is a Research Center. An E&I Platform runs programs or space itself; an Association / Consortium / Network convenes member organizations that run their own. Judge a startup by development stage, not age. Keep distinct units separate, one record each. When the category is genuinely uncertain, still choose the closest one and write a one-line category_note explaining the doubt. Then choose the category_type from that category's own list only; when none fits, choose Not Applicable and explain why in category_note. Record factual topic-relevant information, never imagined GHUS use or engagement recommendations. Use 1–3 factual description sentences. Record aliases, sector, mapped topic, strong/moderate match with explanation, country/state/city and a multi-location flag. Record a real parent only with evidence, otherwise do not invent one. Relationships distinguish unit of, operated by, member of, portfolio of, spinout of, funded by and collaborates with. Hub assignment is not inferred here.
Collect category-specific light facts only: academic—public/private, land-grant if relevant, relevant centers/program names and topic focus; research center—operator/type, focus, 1–2 recent projects and main funders; national lab—sponsor, formal designation and program area; applied facility—operator, facility type, what it tests and current project; hospital—clinical/research focus, academic link, type/scale and initiative; company—public/private, size, relevant product/segment, mapped operating location and current activity; startup—technology/problem, founding year, published stage/TRL, funding stage and visible pilot/customer evidence; E&I platform—operator/type, sector, offerings and scale; investor—type, headquarters, sector/stage/geography, published fund size and thesis; government—jurisdiction, parent, mandate/program and visible funding programs; nonprofit—mission, geography, program and grant themes; association/consortium/network—type, sector/geography, member types, visible initiative and documented members. Category details are concise labeled facts, not full catalogs.
One dated recent topic activity, one visible funding signal and documented Africa/Morocco connections may be captured from supplied sources. No exhaustive grants, programs, publications or people directories. Never estimate TRL. Cite collected sources for factual claims. Unsupported information is omitted, never guessed. Use only supplied evidence.'''

def _check_category_type(entity):
    """Keep a category type only when it belongs to the record's category."""
    chosen = entity.get('category_type')
    if not chosen:
        entity['category_type'] = NOT_CLASSIFIED
        return
    allowed = CATEGORY_TYPES.get(entity.get('actor_type'))
    if allowed is None or chosen in allowed:
        return
    entity['category_type'] = NOT_APPLICABLE
    doubt = f'Category type "{chosen}" is not a type of {entity.get("actor_type")}.'
    entity['category_note'] = '; '.join(n for n in (entity.get('category_note'), doubt) if n)


def normalize_actor_profile(entity, available):
    """Normalize retained actor fields and source-supported relationships."""
    entity['profile_version'] = 2
    for field in ('record_status', 'ghus_notes', 'verification_history', 'field_evidence',
                  'unsupported_fields', 'hub_status', 'um6p_ocp_status'):
        entity.pop(field, None)
    entity['region'] = region_for(entity.get('country'), entity.get('state'))
    entity['category_details'] = [d for d in entity.get('category_details', [])
        if isinstance(d, dict) and isinstance(d.get('label'), str) and isinstance(d.get('value'), str)]
    if entity.get('actor_type') in LEGACY_CATEGORIES:
        entity['actor_type'] = LEGACY_CATEGORIES[entity['actor_type']]
    if entity.get('actor_type') not in CATEGORIES:
        entity['category_note'] = 'Category needs review: ' + str(entity.get('actor_type', 'Not found'))
    _check_category_type(entity)
    relationships = []
    for row in entity.get('actor_relationships') or []:
        if not isinstance(row, dict):
            continue
        try:
            url = canonical_url(row.get('source_url', ''))
        except (ValueError, TypeError):
            continue
        if url in available and row.get('organization_name') and row.get('relationship') in (
            'unit of','operated by','member of','portfolio of','spinout of','funded by','collaborates with'):
            relationships.append({**row, 'source_url': url})
    entity['actor_relationships'] = relationships
