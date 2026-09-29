"""Architecture V2 actor light-pull contract, independent of production DB schema."""
from src.map_agent.search_backend import canonical_url

CATEGORIES = [
    'University / Academic Institution', 'Research Center / Institute / Laboratory',
    'National Laboratory', 'Applied Research Facility / Testbed / Field Site',
    'Hospital / Clinical System / Medical Center', 'Company / Corporate Actor',
    'Startup / Emerging Technology Company',
    'Innovation Platform / Incubator / Accelerator / Venture Studio',
    'Investor / VC / Funding Platform', 'Government Agency / Public Authority',
    'Foundation / Nonprofit', 'Industry Association / Consortium / Network',
]
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

LIGHT_GUIDANCE = '''For actors use the Architecture V2 light pull only. Assign exactly one supplied category by the organization's main job, not its funding or sector. A formal academic department is academic; a research center is not a department; national labs require formal designation. Keep distinct units separate. Record factual topic-relevant information, never imagined GHUS use or engagement recommendations. Use 1–3 factual description sentences. Record aliases, sector, mapped topic, strong/moderate match with explanation, country/state/city and a multi-location flag. Record a real parent only with evidence, otherwise do not invent one. Relationships distinguish unit of, operated by, member of, portfolio of, spinout of, funded by and collaborates with. Hub assignment is not inferred here.
Collect category-specific light facts only: academic—public/private, land-grant if relevant, relevant centers/program names and topic focus; research center—parent/type, focus, 1–2 recent projects and main funders; national lab—sponsor, formal designation and program area; applied facility—operator, facility type, what it tests and current project; hospital—clinical/research focus, academic link, type/scale and initiative; company—public/private, size, relevant product/segment, mapped operating location and current activity; startup—technology/problem, founding year, published stage/TRL, funding stage and visible pilot/customer evidence; innovation platform—operator/type, sector, offerings and scale; investor—type, headquarters, sector/stage/geography, published fund size and thesis; government—jurisdiction, parent, mandate/program and visible funding programs; nonprofit—mission, geography, program and grant themes; consortium—type, sector/geography, member types, visible initiative and documented members. Category details are concise labeled facts, not full catalogs.
One dated recent topic activity, one visible funding signal and documented international/Africa/Morocco connections may be captured from supplied sources. No exhaustive grants, programs, publications or people directories. Never estimate TRL. Cite collected sources for factual claims. Unsupported information is omitted, never guessed. Use only supplied evidence.'''

def normalize_actor_profile(entity, available):
    """Normalize retained actor fields and source-supported relationships."""
    entity['profile_version'] = 2
    for field in ('record_status', 'ghus_notes', 'verification_history', 'field_evidence',
                  'unsupported_fields', 'hub_status', 'um6p_ocp_status'):
        entity.pop(field, None)
    entity['region'] = region_for(entity.get('country'), entity.get('state'))
    entity['category_details'] = [d for d in entity.get('category_details', [])
        if isinstance(d, dict) and isinstance(d.get('label'), str) and isinstance(d.get('value'), str)]
    if entity.get('actor_type') not in CATEGORIES:
        entity['category_note'] = 'Category needs review: ' + str(entity.get('actor_type', 'Not found'))
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
