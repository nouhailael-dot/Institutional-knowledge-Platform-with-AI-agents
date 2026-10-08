-- PROPOSAL ONLY. Never executed against the shared database by an agent.
-- Local ghus_v2_*_test databases only. Production DDL needs schema-owner
-- approval, a verified fresh backup, a tested rollback and a coordinated
-- deployment, all outside this change.
--
-- WS1: replace the Phase 5 category-type catalog with the Intern Guide catalog.
--
-- What this does
--   1. Relabels the 12 actor categories to the Guide's display labels. The
--      category CODES are unchanged, so canonical rows, the hub algorithm,
--      config/architecture_v2.yaml and Agent 3 are unaffected.
--   2. Upserts the Guide's 69 category types. A Phase 5 type code is reused
--      where the Guide type means the same thing in the same category, so an
--      already-classified record keeps its stored value and only its displayed
--      label changes.
--   3. Retires (active = false) every Phase 5 type with no same-category Guide
--      equivalent. Nothing is deleted: retired values still display on the
--      records that hold them, and can still be referenced, but they can no
--      longer be selected.
--   4. Widens the catch-all bookkeeping from 'other' to the Guide's
--      'not_applicable', while keeping the retired 'other' rows valid.
--
-- What this deliberately does NOT do
--   * It does not touch actor rows. Re-mapping already-classified records is a
--     separate, reviewed step: scripts/taxonomy_intern_guide_mapping.py emits
--     docs/evidence/taxonomy_intern_guide_mapping.csv, applies only the 1:1
--     unambiguous pairs, and raises a category_doubt review item for everything
--     else, including every mapping that would change the category.
--   * It does not create or alter actor.fk_actor_category_type. That composite
--     foreign key is owned by the cutover chain
--     (migrations/proposed/deferred/380, 450, 490). This migration keeps it
--     satisfiable: no referenced row is removed.
--
-- ORDERING: run after agents/sql/370_v2_actor_classification.sql. If the
-- Architecture V2 cutover chain has already run, run this after it too — it
-- only ever adds or relabels reference rows, so the order between them is safe
-- in either direction, but the catch-all CHECK below must be the last writer.
--
-- ROLLBACK: agents/sql/rollback/510_v2_intern_guide_taxonomy.sql

BEGIN;

-- ---------------------------------------------------------------------------
-- 0. Preconditions. Fail loudly rather than half-applying.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'actor_category_type_definition'
          AND column_name = 'definition'
    ) THEN
        RAISE EXCEPTION
            'apply agents/sql/370_v2_actor_classification.sql first: actor_category_type_definition.definition is missing';
    END IF;
    IF (SELECT count(*) FROM actor_category_definition) <> 12 THEN
        RAISE EXCEPTION 'expected 12 actor categories, found %',
            (SELECT count(*) FROM actor_category_definition);
    END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 1. Category display labels (decision D1). Codes are untouched.
-- ---------------------------------------------------------------------------
UPDATE actor_category_definition SET
    display_name = v.display_name,
    description  = v.description
FROM (VALUES
    ('university_academic', 'University / Academic Institution',
     'A degree-granting institution, or any formal unit organizationally part of one, including research labs and accelerators run by the university itself.'),
    ('research_center', 'Research Center / Institute / Laboratory',
     'Independent research organizations only. A university research lab is Category 1.'),
    ('national_laboratory', 'National Laboratory',
     'Always its own category, regardless of operator. Requires formal FFRDC or chartered designation under a formal management contract.'),
    ('applied_facility', 'Applied Research Facility / Testbed / Field Site',
     'Independent facilities only. A university-run testbed is Category 1.'),
    ('hospital_clinical', 'Hospital / Clinical System / Medical Center',
     'Always its own category, university-affiliated or not, and never nested under University.'),
    ('company', 'Company / Corporate Actor',
     'Established commercial or industrial company, or business unit.'),
    ('startup', 'Startup / Emerging Technology Company',
     'Judged by development and commercialization stage, not age.'),
    ('innovation_platform', 'Innovation & Entrepreneurship (E&I) Platform',
     'Operates innovation programs or space itself, and is not under a university. A body that convenes independent members is Category 12.'),
    ('investor', 'Investor / Funding Platform',
     'Organization that manages or deploys investment capital.'),
    ('government', 'Government Agency / Public Authority',
     'Public-sector body with a government mandate.'),
    ('foundation_nonprofit', 'Foundation / Nonprofit',
     'Mission-driven nonprofit, including grant makers.'),
    ('association_network', 'Association / Consortium / Network',
     'A membership body that convenes independent organizations rather than operating programs itself.')
) AS v(category_code, display_name, description)
WHERE actor_category_definition.category_code = v.category_code;

-- ---------------------------------------------------------------------------
-- 2. Free the 1..199 sort_order band so the Guide order can be written without
--    tripping UNIQUE (category_code, sort_order) mid-statement.
-- ---------------------------------------------------------------------------
UPDATE actor_category_type_definition SET sort_order = sort_order + 200
WHERE sort_order < 200;

-- ---------------------------------------------------------------------------
-- 3. The catch-all CHECK has to come off before 'not_applicable' can be
--    written. It is restored, widened, in step 6.
-- ---------------------------------------------------------------------------
ALTER TABLE actor_category_type_definition
    DROP CONSTRAINT IF EXISTS ck_actor_category_type_other_flag;
DROP INDEX IF EXISTS ux_actor_category_one_other;

-- ---------------------------------------------------------------------------
-- 4. The Guide catalog: 69 types across 12 categories (Appendix A).
--    Reused codes are relabelled in place; new codes are inserted.
--    Labels are Title Case per decision D12 and must match Appendix A exactly.
-- ---------------------------------------------------------------------------
INSERT INTO actor_category_type_definition
    (category_code, type_code, display_name, sort_order, active, definition, is_other)
VALUES
-- 1 · University / Academic Institution
('university_academic','university_system','Main Institution',1,true,
 'The university record itself - the top of its own tree',false),
('university_academic','academic_department','Department',2,true,
 'An academic subject-area unit (e.g. Dept. of Plant Sciences)',false),
('university_academic','college_school','College / School',3,true,
 'A larger academic division containing multiple departments',false),
('university_academic','research_lab_center','Research Lab / Center',4,true,
 'A research-focused unit inside the university, not its own degree program',false),
('university_academic','tech_transfer_office','Tech Transfer Office',5,true,
 'Patenting and licensing of university research, not startup support',false),
('university_academic','professional_executive_education','Professional / Executive Education',6,true,
 'Non-degree executive education, certificates and short courses',false),
('university_academic','accelerator_incubator','Accelerator / Incubator',7,true,
 'A university-run startup-support program',false),
('university_academic','medical_school','Medical School',8,true,
 'The degree-granting medical academic unit; the clinical hospital is a separate Category 5 record',false),
('university_academic','applied_facility_testbed_field_site','Applied Facility / Testbed / Field Site',9,true,
 'A university-run physical test or demonstration site, such as a farm or pilot plant',false),
('university_academic','extension_outreach_program','Extension / Outreach Program',10,true,
 'A public or community-facing applied program, such as agricultural extension',false),
('university_academic','not_applicable','Not Applicable',11,true,
 'The university itself with no further sub-unit detail needed, or nothing listed fits',true),
-- 2 · Research Center / Institute / Laboratory
('research_center','independent_institute','Independent',1,true,
 'Freestanding, with no parent organization of any kind',false),
('research_center','nonprofit_operated','Nonprofit-Operated',2,true,
 'Run by a nonprofit entity as its primary vehicle',false),
('research_center','corporate_operated','Corporate-Operated',3,true,
 'Run by or embedded in a company',false),
('research_center','government_affiliated','Government-Affiliated',4,true,
 'Government-funded, policy-focused or agency-housed, but not formally designated as a national laboratory',false),
('research_center','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 3 · National Laboratory
('national_laboratory','university_operated_affiliated','University-Operated / Affiliated',1,true,
 'Formally designated national lab whose operating contract is held by a university',false),
('national_laboratory','corporate_operated','Corporate-Operated',2,true,
 'Operating contract held by a company',false),
('national_laboratory','consortium_operated','Consortium-Operated',3,true,
 'Operating contract held by a multi-institution consortium',false),
('national_laboratory','government_direct','Government-Direct',4,true,
 'Run directly by the federal agency with no outside operating contractor',false),
('national_laboratory','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 4 · Applied Research Facility / Testbed / Field Site
('applied_facility','independent','Independent',1,true,
 'No parent organization',false),
('applied_facility','government_operated','Government-Operated',2,true,
 'Run by a federal, state or local agency',false),
('applied_facility','corporate_operated','Corporate-Operated',3,true,
 'Run by a company',false),
('applied_facility','nonprofit_operated','Nonprofit-Operated',4,true,
 'Run by a nonprofit',false),
('applied_facility','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 5 · Hospital / Clinical System / Medical Center
('hospital_clinical','independent_standalone','Independent-Standalone',1,true,
 'No parent system or institution',false),
('hospital_clinical','nonprofit_health_system','Nonprofit Health System',2,true,
 'Part of a larger nonprofit hospital network',false),
('hospital_clinical','for_profit_health_system','For-Profit Health System',3,true,
 'Part of a larger for-profit hospital network',false),
('hospital_clinical','public_government_hospital','Public or Government Hospital',4,true,
 'Operated by a government entity',false),
('hospital_clinical','academic_medical_center','University-Affiliated',5,true,
 'Operated by, or formally tied to, a university medical school; the medical school itself is a separate Category 1 record',false),
('hospital_clinical','not_applicable','Not Applicable',6,true,
 'Nothing listed fits yet',true),
-- 6 · Company / Corporate Actor
('company','public_company','Public Company',1,true,
 'Publicly traded',false),
('company','private_company','Private Company',2,true,
 'Privately held, not SME-scale',false),
('company','small_mid_size','SME',3,true,
 'Small or medium enterprise, privately held',false),
('company','business_unit_subsidiary','Subsidiary / Business Unit',4,true,
 'A unit of a larger parent company',false),
('company','joint_venture','Joint Venture',5,true,
 'Jointly owned by two or more companies',false),
('company','not_applicable','Not Applicable',6,true,
 'Nothing listed fits yet',true),
-- 7 · Startup / Emerging Technology Company
('startup','independent_startup','Independent',1,true,
 'Founded and operating with no institutional origin tie',false),
('startup','university_spinout','University Spinout',2,true,
 'Founded on university-originated IP or research',false),
('startup','corporate_spinout','Corporate Spinout',3,true,
 'Spun out of a company',false),
('startup','accelerator_portfolio_company','Accelerator Portfolio Company',4,true,
 'Currently or recently in an accelerator or incubator program',false),
('startup','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 8 · Innovation & Entrepreneurship (E&I) Platform
('innovation_platform','incubator','Incubator',1,true,
 'Provides space and resources for early-stage companies over an open-ended term',false),
('innovation_platform','accelerator','Accelerator',2,true,
 'Runs fixed-term, cohort-based startup programs',false),
('innovation_platform','venture_studio','Venture Studio',3,true,
 'Builds and launches new ventures itself rather than supporting external founders',false),
('innovation_platform','not_applicable','Not Applicable',4,true,
 'Nothing listed fits yet',true),
-- 9 · Investor / Funding Platform
('investor','venture_capital','Venture Capital Firm',1,true,
 'Institutional VC investing from managed funds',false),
('investor','corporate_venture','Corporate Venture Arm',2,true,
 'A company internal investment arm',false),
('investor','public_investment_fund','Government Fund',3,true,
 'Public-sector investment vehicle',false),
('investor','angel_group','Family Office / Angel Network',4,true,
 'Private individual or family capital, or an organized angel group',false),
('investor','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 10 · Government Agency / Public Authority
('government','federal_agency','Federal',1,true,
 'National-level agency',false),
('government','state_agency','State',2,true,
 'State-level agency',false),
('government','local_municipal','Local / Municipal',3,true,
 'City or county-level agency',false),
('government','public_utility','Public Utility',4,true,
 'Government-affiliated utility provider',false),
('government','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 11 · Foundation / Nonprofit
('foundation_nonprofit','private_foundation','Private Foundation',1,true,
 'Privately endowed, typically grant-making',false),
('foundation_nonprofit','operating_nonprofit','Operating Nonprofit',2,true,
 'Runs its own programs rather than primarily granting funds',false),
('foundation_nonprofit','corporate_foundation','Corporate Foundation',3,true,
 'A company affiliated philanthropic arm',false),
('foundation_nonprofit','community_foundation','Community Foundation',4,true,
 'Pools local or regional donor funds for local grantmaking',false),
('foundation_nonprofit','not_applicable','Not Applicable',5,true,
 'Nothing listed fits yet',true),
-- 12 · Association / Consortium / Network
('association_network','trade_association','Trade Association',1,true,
 'Represents a commercial industry shared interests',false),
('association_network','research_consortium','Research Consortium',2,true,
 'Multi-member group organized around shared research; each member links in as Member of, never as parent or child',false),
('association_network','innovation_consortium','Innovation Consortium',3,true,
 'Multi-member group organized around innovation or commercialization themes rather than research',false),
('association_network','multi_location_network','Statewide / Multi-Location Network',4,true,
 'One parent record, with each individual physical location mapped as its own linked child actor',false),
('association_network','professional_network','Professional Network',5,true,
 'Organized around a shared profession or role, not research or innovation',false),
('association_network','diaspora_network','Diaspora Network',6,true,
 'Organized around shared national or regional origin',false),
('association_network','not_applicable','Not Applicable',7,true,
 'Nothing listed fits yet',true)
ON CONFLICT (category_code, type_code) DO UPDATE SET
    display_name = EXCLUDED.display_name,
    sort_order   = EXCLUDED.sort_order,
    active       = true,
    definition   = EXCLUDED.definition,
    is_other     = EXCLUDED.is_other;

-- ---------------------------------------------------------------------------
-- 5. Retire every Phase 5 type the Guide does not carry forward. Retired rows
--    are kept so the records holding them keep displaying a real label; they
--    are simply no longer selectable. 'other' rows keep is_other = true.
-- ---------------------------------------------------------------------------
UPDATE actor_category_type_definition
SET active = false
WHERE sort_order >= 200;

-- ---------------------------------------------------------------------------
-- 6. Catch-all bookkeeping, widened from 'other' to 'not_applicable'.
--    'other' is retired but still flagged, so history stays readable, and the
--    partial unique index now guarantees exactly one SELECTABLE catch-all per
--    category.
-- ---------------------------------------------------------------------------
UPDATE actor_category_type_definition
SET is_other = (type_code IN ('other', 'not_applicable'));

ALTER TABLE actor_category_type_definition
    ADD CONSTRAINT ck_actor_category_type_other_flag
    CHECK ((type_code IN ('other', 'not_applicable')) = is_other);

CREATE UNIQUE INDEX ux_actor_category_one_other
    ON actor_category_type_definition(category_code)
    WHERE is_other AND active;

-- ---------------------------------------------------------------------------
-- 7. Post-apply assertions. A failure here aborts the whole transaction.
-- ---------------------------------------------------------------------------
DO $$
DECLARE
    selectable integer;
    missing_na integer;
    orphaned   integer;
BEGIN
    SELECT count(*) INTO selectable
    FROM actor_category_type_definition WHERE active;
    IF selectable <> 69 THEN
        RAISE EXCEPTION 'expected 69 selectable Intern Guide types, found %', selectable;
    END IF;

    SELECT count(*) INTO missing_na
    FROM actor_category_definition c
    WHERE NOT EXISTS (
        SELECT 1 FROM actor_category_type_definition t
        WHERE t.category_code = c.category_code
          AND t.type_code = 'not_applicable'
          AND t.active
    );
    IF missing_na <> 0 THEN
        RAISE EXCEPTION '% categories are missing a selectable Not Applicable type', missing_na;
    END IF;

    -- Every pair already stored on an actor must still resolve to a definition
    -- row. Retiring never deletes, so this must be zero.
    SELECT count(*) INTO orphaned
    FROM actor a
    WHERE a.actor_category IS NOT NULL
      AND a.category_type IS NOT NULL
      AND NOT EXISTS (
        SELECT 1 FROM actor_category_type_definition t
        WHERE t.category_code = a.actor_category
          AND t.type_code = a.category_type
    );
    IF orphaned <> 0 THEN
        RAISE EXCEPTION '% actor rows hold a category pair with no definition row', orphaned;
    END IF;
END $$;

COMMIT;
