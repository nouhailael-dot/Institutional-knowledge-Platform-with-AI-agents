-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Architecture V2: controlled categories, types, regions, and source origins.

BEGIN;

CREATE TABLE IF NOT EXISTS actor_category_definition (
    category_code text PRIMARY KEY,
    display_name text NOT NULL UNIQUE,
    description text NOT NULL,
    sort_order smallint NOT NULL UNIQUE CHECK (sort_order BETWEEN 1 AND 12),
    active boolean NOT NULL DEFAULT true
);

CREATE TABLE IF NOT EXISTS actor_category_type_definition (
    category_code text NOT NULL REFERENCES actor_category_definition(category_code),
    type_code text NOT NULL,
    display_name text NOT NULL,
    sort_order smallint NOT NULL,
    active boolean NOT NULL DEFAULT true,
    PRIMARY KEY (category_code, type_code),
    UNIQUE (category_code, display_name),
    UNIQUE (category_code, sort_order)
);

CREATE TABLE IF NOT EXISTS region_definition (
    region_code text PRIMARY KEY,
    display_name text NOT NULL UNIQUE,
    sort_order smallint NOT NULL UNIQUE CHECK (sort_order BETWEEN 1 AND 7)
);

CREATE TABLE IF NOT EXISTS region_state (
    state_code text PRIMARY KEY,
    state_name text NOT NULL UNIQUE,
    region_code text NOT NULL REFERENCES region_definition(region_code),
    is_district boolean NOT NULL DEFAULT false
);

CREATE TABLE IF NOT EXISTS source_origin_definition (
    origin_code text PRIMARY KEY,
    display_name text NOT NULL UNIQUE,
    description text NOT NULL
);

INSERT INTO actor_category_definition(category_code, display_name, description, sort_order) VALUES
('university_academic','University / Academic Institution','Degree-granting institution or formal academic unit',1),
('research_center','Research Center / Institute / Laboratory','Organization whose main job is research, excluding designated national laboratories',2),
('national_laboratory','National Laboratory','Designated national laboratory or federal research facility with a national mission',3),
('applied_facility','Applied Research Facility / Testbed / Field Site','Physical applied testing or demonstration site',4),
('hospital_clinical','Hospital / Clinical System / Medical Center','Clinical-care, medical-research, or clinical-education organization',5),
('company','Company / Corporate Actor','Established commercial or industrial company or business unit',6),
('startup','Startup / Emerging Technology Company','Development-stage company commercializing a new technology or model',7),
('innovation_platform','Innovation Platform / Incubator / Accelerator / Venture Studio','Organization whose main job is supporting startups or innovation',8),
('investor','Investor / VC / Funding Platform','Organization that manages investment capital',9),
('government','Government Agency / Public Authority','Public-sector body with a government mandate',10),
('foundation_nonprofit','Foundation / Nonprofit','Mission-driven nonprofit, including grant makers',11),
('association_network','Industry Association / Consortium / Network','Formal multi-organization group or network',12)
ON CONFLICT (category_code) DO NOTHING;

INSERT INTO actor_category_type_definition(category_code,type_code,display_name,sort_order) VALUES
('university_academic','university_system','University or university system',1),
('university_academic','college_school','College / school within a university',2),
('university_academic','academic_department','Academic department or program',3),
('university_academic','branch_campus','Branch campus',4),
('university_academic','community_technical_college','Community or technical college',5),
('university_academic','other','Other',99),
('research_center','independent_institute','Independent research institute',1),
('research_center','university_affiliated_center','University-affiliated research center or institute',2),
('research_center','research_lab_group','Research laboratory or research group',3),
('research_center','other','Other',99),
('national_laboratory','doe_national_lab','DOE national laboratory',1),
('national_laboratory','ffrdc','Other federally funded R&D center (FFRDC)',2),
('national_laboratory','federal_research_facility','Federal agency research facility',3),
('national_laboratory','other','Other',99),
('applied_facility','experimental_farm_station','Experimental farm or research station',1),
('applied_facility','pilot_demonstration_plant','Pilot or demonstration plant',2),
('applied_facility','testbed','Testbed',3),
('applied_facility','field_site_living_lab','Field site or living lab',4),
('applied_facility','other','Other',99),
('hospital_clinical','academic_medical_center','Academic medical center',1),
('hospital_clinical','health_system','Health system',2),
('hospital_clinical','hospital','Hospital',3),
('hospital_clinical','specialty_clinic_center','Specialty clinic or center',4),
('hospital_clinical','other','Other',99),
('company','large_multinational','Large or multinational corporation',1),
('company','small_mid_size','Small or mid-size company',2),
('company','business_unit_subsidiary','Business unit or subsidiary',3),
('company','corporate_rd_center','Corporate R&D or innovation center',4),
('company','other','Other',99),
('startup','university_spinout','University spinout',1),
('startup','corporate_spinout','Corporate spinout',2),
('startup','independent_startup','Independent startup',3),
('startup','other','Other',99),
('innovation_platform','incubator','Incubator',1),
('innovation_platform','accelerator','Accelerator',2),
('innovation_platform','venture_studio','Venture studio',3),
('innovation_platform','innovation_center_shared_lab','Innovation center or shared lab space',4),
('innovation_platform','tech_transfer_office','Technology-transfer or commercialization office',5),
('innovation_platform','other','Other',99),
('investor','venture_capital','Venture capital firm',1),
('investor','corporate_venture','Corporate venture arm',2),
('investor','angel_group','Angel group',3),
('investor','impact_climate_fund','Impact or climate fund',4),
('investor','private_equity_growth','Private equity or growth fund',5),
('investor','public_investment_fund','Public or quasi-public investment fund',6),
('investor','other','Other',99),
('government','federal_agency','Federal agency',1),
('government','state_agency','State agency',2),
('government','local_municipal','Local or municipal government',3),
('government','regional_authority','Regional or special-purpose authority',4),
('government','public_utility','Public utility',5),
('government','other','Other',99),
('foundation_nonprofit','private_foundation','Private foundation',1),
('foundation_nonprofit','corporate_foundation','Corporate foundation',2),
('foundation_nonprofit','community_foundation','Community foundation',3),
('foundation_nonprofit','operating_nonprofit','Operating nonprofit',4),
('foundation_nonprofit','think_tank','Think tank or policy institute',5),
('foundation_nonprofit','other','Other',99),
('association_network','trade_association','Trade or industry association',1),
('association_network','research_consortium','Research consortium',2),
('association_network','professional_society','Professional society',3),
('association_network','standards_body','Standards body',4),
('association_network','alliance_coalition','Alliance or coalition',5),
('association_network','multi_location_network','Statewide or multi-location network',6),
('association_network','other','Other',99)
ON CONFLICT (category_code,type_code) DO NOTHING;

INSERT INTO region_definition(region_code,display_name,sort_order) VALUES
('northeast','Northeast',1),('mid_atlantic','Mid-Atlantic',2),
('southeast','Southeast',3),('midwest_great_lakes','Midwest / Great Lakes',4),
('south_central_texas_gulf','South Central / Texas Gulf',5),
('mountain_west','Mountain West / Rocky Mountain',6),
('west_coast_pacific','West Coast / Pacific',7)
ON CONFLICT (region_code) DO NOTHING;

INSERT INTO region_state(state_code,state_name,region_code,is_district) VALUES
('CT','Connecticut','northeast',false),('ME','Maine','northeast',false),('MA','Massachusetts','northeast',false),('NH','New Hampshire','northeast',false),('NY','New York','northeast',false),('RI','Rhode Island','northeast',false),('VT','Vermont','northeast',false),
('DE','Delaware','mid_atlantic',false),('MD','Maryland','mid_atlantic',false),('NJ','New Jersey','mid_atlantic',false),('PA','Pennsylvania','mid_atlantic',false),('VA','Virginia','mid_atlantic',false),('WV','West Virginia','mid_atlantic',false),('DC','Washington DC','mid_atlantic',true),
('AL','Alabama','southeast',false),('FL','Florida','southeast',false),('GA','Georgia','southeast',false),('KY','Kentucky','southeast',false),('MS','Mississippi','southeast',false),('NC','North Carolina','southeast',false),('SC','South Carolina','southeast',false),('TN','Tennessee','southeast',false),
('IL','Illinois','midwest_great_lakes',false),('IN','Indiana','midwest_great_lakes',false),('IA','Iowa','midwest_great_lakes',false),('KS','Kansas','midwest_great_lakes',false),('MI','Michigan','midwest_great_lakes',false),('MN','Minnesota','midwest_great_lakes',false),('MO','Missouri','midwest_great_lakes',false),('NE','Nebraska','midwest_great_lakes',false),('ND','North Dakota','midwest_great_lakes',false),('OH','Ohio','midwest_great_lakes',false),('SD','South Dakota','midwest_great_lakes',false),('WI','Wisconsin','midwest_great_lakes',false),
('AR','Arkansas','south_central_texas_gulf',false),('LA','Louisiana','south_central_texas_gulf',false),('OK','Oklahoma','south_central_texas_gulf',false),('TX','Texas','south_central_texas_gulf',false),
('AZ','Arizona','mountain_west',false),('CO','Colorado','mountain_west',false),('ID','Idaho','mountain_west',false),('MT','Montana','mountain_west',false),('NV','Nevada','mountain_west',false),('NM','New Mexico','mountain_west',false),('UT','Utah','mountain_west',false),('WY','Wyoming','mountain_west',false),
('AK','Alaska','west_coast_pacific',false),('CA','California','west_coast_pacific',false),('HI','Hawaii','west_coast_pacific',false),('OR','Oregon','west_coast_pacific',false),('WA','Washington','west_coast_pacific',false)
ON CONFLICT (state_code) DO NOTHING;

INSERT INTO source_origin_definition(origin_code,display_name,description) VALUES
('imported','Already mapped','Imported from the Phase 1 map'),
('newly_found','Newly found','Discovered during a mapped search'),
('uploaded_document','Uploaded document','Supplied in a GHUS, UM6P, or OCP document'),
('ghus_manual','GHUS manual','Entered directly by an authorized GHUS reviewer')
ON CONFLICT (origin_code) DO NOTHING;

COMMIT;

-- ROLLBACK: export dependent V2 rows, then drop the five tables in reverse order.
