-- ROLLBACK for agents/sql/510_v2_intern_guide_taxonomy.sql.
-- Local ghus_v2_*_test databases only.
--
-- Restores the Phase 5 catalog: the Phase 5 category labels, the 65 Phase 5
-- types as the selectable set, and the 'other'-only catch-all bookkeeping.
--
-- The Intern Guide type rows that Phase 5 never had are RETIRED, not deleted,
-- because an actor row may already reference one. Deleting them would break
-- actor.fk_actor_category_type. Nothing in this project deletes a referenced
-- reference row.
--
-- If actor rows were re-mapped onto Guide-only types after 510 ran, reverse
-- that data step first (docs/evidence/taxonomy_intern_guide_mapping.csv records
-- the before value for every row it touched). This script refuses to run while
-- any actor still holds a Guide-only pair.

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Refuse to strand an actor on a type Phase 5 never had.
-- ---------------------------------------------------------------------------
DO $$
DECLARE stranded integer;
BEGIN
    SELECT count(*) INTO stranded
    FROM actor a
    WHERE (a.actor_category, a.category_type) IN (
        ('university_academic','research_lab_center'),
        ('university_academic','professional_executive_education'),
        ('university_academic','accelerator_incubator'),
        ('university_academic','medical_school'),
        ('university_academic','applied_facility_testbed_field_site'),
        ('university_academic','extension_outreach_program'),
        ('university_academic','tech_transfer_office'),
        ('research_center','nonprofit_operated'),
        ('research_center','corporate_operated'),
        ('research_center','government_affiliated'),
        ('national_laboratory','university_operated_affiliated'),
        ('national_laboratory','corporate_operated'),
        ('national_laboratory','consortium_operated'),
        ('national_laboratory','government_direct'),
        ('applied_facility','independent'),
        ('applied_facility','government_operated'),
        ('applied_facility','corporate_operated'),
        ('applied_facility','nonprofit_operated'),
        ('hospital_clinical','independent_standalone'),
        ('hospital_clinical','nonprofit_health_system'),
        ('hospital_clinical','for_profit_health_system'),
        ('hospital_clinical','public_government_hospital'),
        ('company','public_company'),
        ('company','private_company'),
        ('company','joint_venture'),
        ('startup','accelerator_portfolio_company'),
        ('association_network','innovation_consortium'),
        ('association_network','professional_network'),
        ('association_network','diaspora_network')
    )
    OR a.category_type = 'not_applicable';
    IF stranded <> 0 THEN
        RAISE EXCEPTION
            'refusing to roll back: % actor rows hold an Intern Guide type. Reverse the data mapping first.',
            stranded;
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Catch-all bookkeeping back to 'other' only.
-- ---------------------------------------------------------------------------
ALTER TABLE actor_category_type_definition
    DROP CONSTRAINT IF EXISTS ck_actor_category_type_other_flag;
DROP INDEX IF EXISTS ux_actor_category_one_other;

UPDATE actor_category_type_definition
SET is_other = (type_code = 'other');

-- ---------------------------------------------------------------------------
-- 2. Reinstate the Phase 5 selectable set and its labels and sort order.
-- ---------------------------------------------------------------------------
UPDATE actor_category_type_definition SET sort_order = sort_order + 200
WHERE sort_order < 200;

UPDATE actor_category_type_definition SET active = false
WHERE sort_order >= 200;

UPDATE actor_category_type_definition SET
    display_name = v.display_name,
    sort_order   = v.sort_order,
    active       = true
FROM (VALUES
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
) AS v(category_code, type_code, display_name, sort_order)
WHERE actor_category_type_definition.category_code = v.category_code
  AND actor_category_type_definition.type_code = v.type_code;

ALTER TABLE actor_category_type_definition
    ADD CONSTRAINT ck_actor_category_type_other_flag
    CHECK ((type_code = 'other') = is_other);

CREATE UNIQUE INDEX ux_actor_category_one_other
    ON actor_category_type_definition(category_code)
    WHERE is_other;

-- ---------------------------------------------------------------------------
-- 3. Phase 5 category labels.
-- ---------------------------------------------------------------------------
UPDATE actor_category_definition SET
    display_name = v.display_name,
    description  = v.description
FROM (VALUES
    ('university_academic','University / Academic Institution','Degree-granting institution or formal academic unit'),
    ('research_center','Research Center / Institute / Laboratory','Organization whose main job is research, excluding designated national laboratories'),
    ('national_laboratory','National Laboratory','Designated national laboratory or federal research facility with a national mission'),
    ('applied_facility','Applied Research Facility / Testbed / Field Site','Physical applied testing or demonstration site'),
    ('hospital_clinical','Hospital / Clinical System / Medical Center','Clinical-care, medical-research, or clinical-education organization'),
    ('company','Company / Corporate Actor','Established commercial or industrial company or business unit'),
    ('startup','Startup / Emerging Technology Company','Development-stage company commercializing a new technology or model'),
    ('innovation_platform','Innovation Platform / Incubator / Accelerator / Venture Studio','Organization whose main job is supporting startups or innovation'),
    ('investor','Investor / VC / Funding Platform','Organization that manages investment capital'),
    ('government','Government Agency / Public Authority','Public-sector body with a government mandate'),
    ('foundation_nonprofit','Foundation / Nonprofit','Mission-driven nonprofit, including grant makers'),
    ('association_network','Industry Association / Consortium / Network','Formal multi-organization group or network')
) AS v(category_code, display_name, description)
WHERE actor_category_definition.category_code = v.category_code;

DO $$
DECLARE selectable integer;
BEGIN
    SELECT count(*) INTO selectable
    FROM actor_category_type_definition WHERE active;
    IF selectable <> 65 THEN
        RAISE EXCEPTION 'expected 65 selectable Phase 5 types after rollback, found %', selectable;
    END IF;
END $$;

COMMIT;
