"""Second no-Claude actor technical refinement pass.

Keeps the same guardrail as the first pass: update only rows whose
current_activities still starts with the generic deterministic-fill marker.
"""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from actor_technical_no_claude_improve_more import TEMPLATES, rec  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TEMPLATES.update(
    {
        "un_policy_body": rec(
            "Policy, standards, intergovernmental review, sustainable development, social systems, and public-sector implementation support.",
            "Uses expert reports, negotiated recommendations, monitoring frameworks, convenings, and member-state coordination to shape policy action.",
            "Core assets are mandates, standards, reports, datasets, convening authority, and implementation guidance rather than proprietary technology IP.",
            "Influence depends on member-state consensus, funding, data quality, political alignment, institutional capacity, and implementation follow-through.",
            "validation",
        ),
        "development_finance": rec(
            "Development finance, infrastructure investment, private-sector growth, climate finance, food systems, and implementation capacity.",
            "Uses loans, grants, guarantees, advisory services, safeguards, technical assistance, and country or private-sector partnerships.",
            "IP emphasis is low; value lies in financing instruments, project data, safeguards, procurement practices, and implementation know-how.",
            "Impact depends on country demand, credit risk, governance, co-financing, safeguard compliance, political stability, and project execution.",
            "scaling",
        ),
        "ag_science_company": rec(
            "Crop protection, seeds, traits, agronomy, biologicals, digital agriculture, and farm productivity technologies.",
            "Combines field trials, breeding, chemistry, biology, data tools, regulatory studies, and grower-facing commercialization.",
            "Likely IP includes seed genetics, traits, formulations, biologicals, patents, data assets, regulatory dossiers, and trade secrets.",
            "Constraints include regulatory approvals, field performance, resistance management, farmer economics, stewardship, and seasonal validation cycles.",
            "deployment",
        ),
        "innovation_district": rec(
            "Innovation real estate, startup commercialization, life sciences, digital technology, and regional cluster development.",
            "Provides physical infrastructure, tenant networks, events, partner access, and commercialization programming for companies and research groups.",
            "IP generally remains with tenant companies, universities, or partners; the district contributes infrastructure and ecosystem coordination.",
            "Impact depends on tenant quality, capital access, anchor institutions, real estate execution, partner density, and regional talent retention.",
            "scaling",
        ),
        "environmental_studies": rec(
            "Environmental studies, climate policy, sustainability, water, social-ecological systems, and environmental justice.",
            "Combines interdisciplinary research, education, field work, policy analysis, data, and community or agency partnerships.",
            "Outputs include publications, datasets, models, policy analysis, teaching materials, and decision-support tools rather than heavy patent IP.",
            "Impact depends on funding, field data access, stakeholder trust, policy uptake, and translation across scientific and social domains.",
            "discovery",
        ),
        "renewable_energy_research": rec(
            "Renewable energy, energy systems, solar, storage, grid integration, power electronics, and clean-energy materials.",
            "Uses laboratory research, modeling, prototypes, testbeds, industry partnerships, and interdisciplinary engineering programs.",
            "Outputs may include publications, software, devices, prototypes, materials, patents, and university-managed licenses.",
            "Constraints include lab infrastructure, scale-up cost, grid integration, reliability, funding, partner access, and commercialization pathways.",
            "discovery",
        ),
        "ag_engineering": rec(
            "Agricultural and biological engineering, sensors, water management, bioenergy, food systems, machinery, and digital agriculture.",
            "Combines engineering design, field trials, biological systems research, modeling, prototypes, and extension or industry partnerships.",
            "Outputs include publications, prototypes, software, datasets, methods, patents, and university-managed inventions where applicable.",
            "Impact depends on field validation, farm economics, equipment integration, funding, data access, and producer adoption.",
            "discovery",
        ),
        "crop_science": rec(
            "Crop science, plant breeding, crop physiology, pest management, soil-crop systems, agronomy, and field validation.",
            "Uses field trials, genomics, breeding, phenotyping, agronomic experiments, modeling, and extension partnerships.",
            "IP may include varieties, traits, biological materials, datasets, decision tools, methods, patents, and licenses.",
            "Constraints include seasonal cycles, field variability, pest pressure, climate risk, grower economics, and regulatory or stewardship needs.",
            "validation",
        ),
        "lead_mining": rec(
            "Lead, zinc, and critical-mineral mining, milling, recycling, environmental management, and industrial operations.",
            "Uses mine operations, mineral processing, metallurgical controls, environmental monitoring, reclamation, and logistics.",
            "IP is mainly operational know-how, process controls, geological data, safety practices, and environmental management methods.",
            "Constraints include commodity prices, mine safety, permitting, environmental compliance, tailings and waste management, and community trust.",
            "deployment",
        ),
        "plant_science_center": rec(
            "Plant science, crop improvement, phenotyping, bioinformatics, plant-microbe systems, sustainable agriculture, and ag-biotech.",
            "Combines laboratory biology, greenhouse and field studies, computational biology, partnerships, and translational crop research.",
            "IP may include plant traits, biological materials, methods, datasets, software, patents, and licensed technologies.",
            "Translation depends on field validation, regulatory pathways, crop relevance, funding, partner access, and grower adoption.",
            "validation",
        ),
        "materials_chemicals": rec(
            "Advanced materials, specialty chemicals, polymers, process chemistry, industrial manufacturing, and applications development.",
            "Uses process R&D, formulation, catalyst or materials work, pilot operations, manufacturing know-how, and customer qualification.",
            "Likely IP includes formulations, process know-how, materials grades, patents, trade secrets, and applications data.",
            "Constraints include process safety, environmental compliance, feedstock cost, scale-up, customer qualification, and market cycles.",
            "deployment",
        ),
        "chemical_department": rec(
            "Chemistry, chemical biology, catalysis, materials, molecular design, synthesis, and reaction mechanisms.",
            "Combines faculty-led laboratory research, computation, instrumentation, graduate training, and interdisciplinary collaborations.",
            "Outputs include publications, molecules, catalysts, datasets, software, methods, patents, and university-managed licenses.",
            "Progress depends on research funding, lab infrastructure, safety, reproducibility, talent, and translation partners.",
            "discovery",
        ),
        "berry_producer": rec(
            "Berry production, plant breeding partnerships, crop quality, supply-chain operations, food safety, and grower networks.",
            "Combines proprietary varieties, agronomy, grower partnerships, quality systems, packaging, logistics, and consumer market development.",
            "Likely IP includes plant varieties, trademarks, growing protocols, quality data, supply-chain know-how, and brand assets.",
            "Constraints include disease pressure, labor, water, climate variability, food safety, logistics, and maintaining grower economics.",
            "deployment",
        ),
        "health_regulator": rec(
            "Food, drugs, biologics, medical devices, diagnostics, clinical evidence, safety surveillance, and regulatory science.",
            "Uses review standards, inspections, guidance, clinical data evaluation, surveillance, and enforcement to assess regulated products.",
            "Core assets are regulatory frameworks, review methods, datasets, guidance, and compliance authority rather than proprietary technology IP.",
            "Constraints include safety evidence, data quality, legal requirements, review capacity, public trust, and rapidly changing technology.",
            "validation",
        ),
        "automotive": rec(
            "Automotive engineering, electric vehicles, batteries, software-defined vehicles, manufacturing, autonomy-adjacent systems, and mobility.",
            "Uses vehicle R&D, platform engineering, manufacturing systems, supplier networks, testing, software, and customer-scale deployment.",
            "Likely IP includes patents, software, battery and vehicle designs, manufacturing know-how, safety systems, and trade secrets.",
            "Constraints include capital intensity, safety regulation, supply chains, charging infrastructure, labor, cost targets, and consumer adoption.",
            "deployment",
        ),
        "biopharma": rec(
            "Biopharmaceutical research, therapeutics, biologics, clinical development, diagnostics-adjacent science, and translational medicine.",
            "Combines discovery biology, clinical trials, regulatory strategy, manufacturing, partnerships, and commercialization.",
            "Likely IP includes patents, biologics, molecules, clinical data, regulatory dossiers, manufacturing know-how, and trade secrets.",
            "Constraints include clinical risk, safety, regulation, reimbursement, manufacturing quality, patent life, and competitive pipelines.",
            "deployment",
        ),
        "synthetic_biology": rec(
            "Synthetic biology, cell engineering, fermentation, biomanufacturing, enzyme pathways, and bio-based chemicals or materials.",
            "Uses organism engineering, automation, screening, fermentation scale-up, process development, and commercial partnerships.",
            "IP may include engineered strains, pathways, genetic designs, fermentation processes, datasets, software, patents, and trade secrets.",
            "Constraints include scale-up yield, feedstock cost, bioprocess reliability, customer qualification, regulation, and capital intensity.",
            "demonstration",
        ),
        "corporate_ai_lab": rec(
            "Artificial intelligence, machine learning, foundation models, data systems, product AI, safety, and applied research.",
            "Combines research teams, large-scale compute, datasets, product integration, evaluation, and partnerships to move AI into deployed systems.",
            "Likely IP includes models, software, datasets, patents, evaluation methods, infrastructure, and trade secrets.",
            "Constraints include compute cost, data governance, safety, regulation, talent, model reliability, and product integration risk.",
            "demonstration",
        ),
        "water_program": rec(
            "Water quality, watershed restoration, aquatic ecosystems, pollution reduction, monitoring, and regional water governance.",
            "Uses grants, monitoring, restoration projects, interagency coordination, data, compliance programs, and stakeholder engagement.",
            "Core assets are program data, restoration methods, grants, plans, monitoring systems, and implementation partnerships rather than proprietary IP.",
            "Constraints include long ecological timelines, jurisdictional complexity, funding, data quality, pollution sources, and stakeholder alignment.",
            "validation",
        ),
        "flood_control": rec(
            "Flood risk reduction, stormwater infrastructure, watershed planning, hydrology, drainage systems, and climate resilience.",
            "Uses engineering projects, modeling, maintenance, land acquisition, public works coordination, and emergency planning.",
            "Core assets are infrastructure, hydrologic models, engineering plans, maintenance data, and public authority rather than patents.",
            "Constraints include funding, land access, rainfall extremes, aging infrastructure, permitting, community impacts, and climate uncertainty.",
            "deployment",
        ),
        "port_authority": rec(
            "Port operations, ship channel infrastructure, industrial logistics, dredging, safety, resilience, and emissions management.",
            "Uses infrastructure management, vessel coordination, dredging programs, public-private coordination, safety systems, and capital projects.",
            "IP emphasis is low; value lies in infrastructure, operating data, logistics coordination, permits, and project delivery know-how.",
            "Constraints include safety, congestion, dredging permits, extreme weather, emissions rules, financing, and coordination with industrial users.",
            "deployment",
        ),
        "national_lab": rec(
            "National laboratory science, energy, security, computing, materials, climate, engineering, and mission-driven technology development.",
            "Uses large research facilities, multidisciplinary teams, federal programs, modeling, experiments, prototypes, and industry partnerships.",
            "Outputs include publications, software, datasets, prototypes, patents, licenses, and mission-specific technical know-how.",
            "Translation depends on federal missions, security requirements, facility access, funding, partner pathways, and scale-up readiness.",
            "validation",
        ),
        "energy_test_facility": rec(
            "Energy systems integration, grid modernization, power electronics, storage, buildings, hydrogen, mobility, and clean-energy testbeds.",
            "Provides lab infrastructure, simulation, hardware-in-the-loop testing, partner projects, and systems validation for clean-energy technologies.",
            "Outputs include test data, validation methods, software, experimental platforms, reports, patents, and partner-specific technical knowledge.",
            "Constraints include facility access, safety, interoperability, funding, partner equipment readiness, and translation from testbed to field.",
            "validation",
        ),
        "critical_minerals_company": rec(
            "Critical minerals, lithium or copper production, mine development, mineral processing, resource modeling, and environmental management.",
            "Uses exploration, resource estimation, mine engineering, processing, permitting, project finance, and operational execution.",
            "IP is mostly geological data, processing know-how, mine plans, operational methods, permits, and trade secrets.",
            "Constraints include permitting, commodity cycles, water, tailings, community acceptance, capital intensity, and processing reliability.",
            "deployment",
        ),
        "life_science_incubator": rec(
            "Life-science startup incubation, wet-lab infrastructure, biotech commercialization, founder support, and translational health innovation.",
            "Provides shared laboratories, equipment, programming, investor access, partner networks, and startup support for early-stage biotech companies.",
            "Startup IP remains with resident companies; the incubator contributes infrastructure, ecosystem access, and commercialization support.",
            "Impact depends on lab capacity, startup quality, capital access, regulatory timelines, partner networks, and regional talent density.",
            "scaling",
        ),
        "earth_sciences_school": rec(
            "Earth sciences, mining engineering, geological engineering, critical minerals, geophysics, hydrology, and resource systems.",
            "Combines field studies, laboratories, modeling, engineering education, industry partnerships, and applied geoscience research.",
            "Outputs include publications, datasets, geological models, engineering methods, prototypes, patents, and workforce training.",
            "Translation depends on field access, permitting, data quality, safety, funding, commodity cycles, and industry adoption.",
            "discovery",
        ),
    }
)


ACTORS: dict[str, tuple[str, str]] = {
    "079b3d7f-15e0-4a71-95f6-b2c9860253ba": ("un_policy_body", "Advises UN member states on social development policy, inclusion, poverty reduction, employment, and implementation review."),
    "79ae084d-f0c3-414c-9a7b-15487a74d1f2": ("un_policy_body", "Reviews population and development trends and advises UN member states on demographic policy implementation."),
    "41d39158-75d7-49c8-add6-603d78390de4": ("un_policy_body", "Advises UN bodies on science, technology, innovation, digital development, and their role in sustainable development."),
    "58936668-c90e-47fd-b65b-2fb6c29103cb": ("un_policy_body", "Sets and reviews global policy norms on gender equality and the implementation of international commitments on women and girls."),
    "ef7bd2bb-c538-43f9-a6df-0a97aee833dc": ("cornell_tech", "Supports Cornell Tech health-technology activity linking applied technology, data, entrepreneurship, and New York clinical partners."),
    "b82db737-ff45-49ac-91a2-c68e8b933273": ("ai_lab", "Conducts Cornell Tech AI research and education focused on applied machine learning, data systems, and technology translation."),
    "1bce2874-23da-4ecf-ae29-b95c27c8d773": ("ag_college", "Conducts Cornell research, education, and extension across agriculture, life sciences, technology, health, and sustainability."),
    "3ac81d89-bbcc-4eea-8c6c-9fa66f834dce": ("ag_science_company", "Develops and commercializes crop protection, seed, trait, biological, and digital agriculture products for farmers."),
    "9dc13aad-6ffc-408e-9a4e-5c1cf9178351": ("ag_science_company", "Develops and commercializes crop protection, seed, trait, biological, and digital agriculture products for farmers."),
    "c3e1c3a1-9ec5-48ac-9a3b-2a63ed61557c": ("innovation_district", "Operates a St. Louis innovation district supporting bioscience, technology startups, anchor institutions, and regional commercialization."),
    "571cf509-b812-4d0a-98eb-71856b514388": ("environmental_studies", "Conducts CU Boulder environmental studies research and education across sustainability, climate, policy, and social-ecological systems."),
    "dd476bf1-f508-42a6-8822-bd74a9c8995e": ("climate_research", "Conducts CU Boulder arctic, alpine, climate, hydrology, and earth-system research through INSTAAR."),
    "e5545435-8220-432e-abda-725789d1d4d2": ("renewable_energy_research", "Conducts CU Boulder renewable and sustainable energy research through interdisciplinary energy programs and partnerships."),
    "d0e5673c-b614-430d-9dcc-dc3341f09402": ("dairy_research", "Supports dairy product research, processing, training, and industry-facing technical assistance through the Wisconsin dairy center."),
    "53453c44-fc1f-4b57-8e5f-e7f85025dd64": ("ag_engineering", "Conducts UIUC agricultural and biological engineering research and education across digital agriculture, water, food, and biological systems."),
    "1dec4295-ffaa-47e1-8d68-7ec8a1901d4c": ("ag_engineering", "Conducts Texas A&M biological and agricultural engineering research and education across water, machinery, food, and biological systems."),
    "6a3ca546-d9d7-4af2-b4ba-5fc525b193c1": ("crop_science", "Conducts University of Illinois crop science research and education across agronomy, breeding, crop protection, and field systems."),
    "de52b176-ce05-4eb9-ba33-4623a6e04043": ("un_policy_body", "Provides UN intergovernmental support, policy analysis, data, and implementation guidance on economic and social development."),
    "3a0a94e4-c122-4117-9302-0fea27fbe97e": ("crop_science", "Conducts Texas A&M soil and crop sciences research and education across agronomy, soil systems, crops, and field management."),
    "7779966c-2f96-42be-b823-b74441c4a995": ("un_policy_body", "Coordinates and oversees the UN resident coordinator system and country-level sustainable development implementation support."),
    "0535507c-752b-4960-b997-b789b31a5bdd": ("lead_mining", "Operates lead mining, milling, recycling, and environmental management activities in the Missouri Lead Belt context."),
    "9de478e6-aa63-47cf-86cb-2588a3e626f4": ("plant_science_center", "Conducts plant science and ag-biotech research focused on crop improvement, phenotyping, sustainability, and food security."),
    "f476a8c4-a156-4018-a2e6-5e5eab85f1bf": ("materials_chemicals", "Develops and manufactures chemical, materials, packaging, coatings, and industrial products through global R&D and production assets."),
    "ae6dc0f1-80d3-4a77-a1e2-1f79e92b24f3": ("materials_chemicals", "Supports Dow materials and chemical R&D operations linked to Midwest manufacturing, applications development, and process improvement."),
    "c3f2489a-2962-4962-a315-c641eff356f6": ("catalysis", "Conducts Drexel chemical and biomolecular engineering research and education in catalysis, processes, materials, and biotechnologies."),
    "118ecc95-847a-4734-9222-59610fcead8b": ("berry_producer", "Operates berry production, variety development partnerships, grower networks, quality systems, and fresh-produce supply chains."),
    "89d33fd7-81a7-46b9-ba71-ba283f89b879": ("chemical_department", "Conducts Duke chemistry research and education across molecular science, catalysis, chemical biology, materials, and synthesis."),
    "0225e2e3-597a-4548-89b6-d1c05642fcd3": ("materials_chemicals", "Develops and manufactures specialty materials, electronics materials, industrial technologies, and chemical products through global R&D and operations."),
    "00c2b62e-762c-45e7-b519-421398c149db": ("climate_research", "Conducts NOAA earth-system research in weather, climate, atmospheric chemistry, carbon cycle, and environmental monitoring."),
    "74549553-0e1b-4038-962e-6ae184fd293d": ("un_policy_body", "Provides regional policy analysis, convening, and technical support for African economic development and sustainable transformation."),
    "2e2557c6-c88e-4f9d-bbdd-c74695e960d8": ("energy_policy_center", "Conducts UC Berkeley energy and resources research and education across energy systems, sustainability, economics, and policy."),
    "607c5dd8-2d8e-42d8-925e-8dea758629bb": ("energy_test_facility", "Provides NREL energy-systems integration test infrastructure for grid, storage, buildings, hydrogen, and clean-energy technologies."),
    "e84097f6-8c0c-4d80-96e9-bb50a2803067": ("water_program", "Coordinates EPA Great Lakes restoration, water quality, monitoring, and pollution-reduction programs across regional partners."),
    "46334559-58aa-4a9a-b2a4-10daa2e4e966": ("grid_operator", "Operates the Texas electric grid and market coordination functions for reliability, dispatch, and power-system operations."),
    "3cb28f86-409a-4cd7-9d49-414b20b1088e": ("upstream_energy", "Operates global energy assets while applying subsurface, refining, petrochemical, carbon-management, and operations technologies."),
    "648f15fe-080a-4ede-9639-fa387dc6d60e": ("petrochemicals", "Operates ExxonMobil Baytown refining and petrochemical assets with large-scale process, logistics, and manufacturing operations."),
    "2d4580d4-d14a-4631-9bea-e1a309bcebb7": ("materials_chemicals", "Supports ExxonMobil Baytown technology and engineering work tied to refining, petrochemicals, process improvement, and manufacturing support."),
    "85f229a6-72b5-4a3b-891f-e8b5283d83c1": ("materials_chemicals", "Supports ExxonMobil technology collaborations relevant to advanced materials, catalysis, process engineering, and industrial transition."),
    "011bb16e-cdca-46bc-ab56-46fe3b12305a": ("venture", "Creates, funds, and scales platform companies in life sciences, biotechnology, AI-enabled health, and sustainability-related sectors."),
    "bca13bf2-6250-451e-890a-ca686c06bc47": ("ag_science_company", "Develops and commercializes crop protection, plant health, and specialty agricultural chemistry products."),
    "5295697c-66e2-4e13-9622-c5d2d299fda7": ("ag_science_company", "Develops and commercializes crop protection, plant health, and specialty agricultural chemistry products."),
    "d02f0ffb-b580-45c9-a1a4-af585039294e": ("un_policy_body", "Sets food and agriculture norms, produces data, and supports member countries on food security, forestry, fisheries, and rural development."),
    "1229003e-e75e-467e-ad13-bc0e8422ae8c": ("health_regulator", "Regulates food, drugs, biologics, medical devices, diagnostics, and other health products through evidence review and compliance programs."),
    "a4196d55-27cb-4607-8474-6f0b6e4f998a": ("automotive", "Develops and manufactures vehicles while investing in electrification, software, batteries, manufacturing systems, and mobility technologies."),
    "d7a5e21e-71af-401a-9c87-3993853a4f7a": ("petrochemicals", "Operates Formosa Plastics petrochemical and plastics production assets at Point Comfort with large-scale industrial process operations."),
    "0c8a66e1-8447-4a0b-a4e0-fbfbc9872752": ("critical_minerals_company", "Operates copper and mining assets with resource development, mineral processing, environmental management, and supply-chain execution."),
    "a898cf93-e275-4752-a0f0-7b1d3b658424": ("biopharma", "Develops and commercializes biotechnology medicines, biologics, diagnostics-adjacent science, and translational biomedical research."),
    "5ae56444-e2bc-45ba-8f8c-544979a958b5": ("venture", "Invests in and supports technology companies across AI, health, software, infrastructure, climate, and other growth sectors."),
    "1046c5b1-c064-494b-9896-25858f373187": ("automotive", "Develops and manufactures vehicles while advancing electrification, batteries, software, manufacturing systems, and mobility technologies."),
    "eb4576cd-1be0-42e4-8f03-ecf76a33ec16": ("synthetic_biology", "Develops bio-based chemical and materials production platforms using engineered microbes, fermentation, and industrial biotechnology partnerships."),
    "92bd84b7-5ffa-4657-af7e-58c7406e36ce": ("university_science", "Conducts research and education across public policy, health, engineering, international affairs, law, and applied sciences in Washington, D.C."),
    "2a9e0729-2a77-42dc-8de4-db9f4a877078": ("medical_school", "Conducts Georgetown biomedical, clinical, and health-science research and education through its medical center programs."),
    "50dd4828-52bc-4cdf-a30c-15566b42beae": ("biopharma", "Develops and commercializes medicines for virology, oncology, inflammation, and other therapeutic areas through biopharmaceutical R&D."),
    "2bcf1117-97db-4606-b4a9-0a4424c10e9f": ("synthetic_biology", "Applies cell programming and biological engineering capabilities to West Coast industrial biotechnology and bio-based product collaborations."),
    "71ba3a3c-fd04-4618-88d3-2e19f5e109b2": ("corporate_ai_lab", "Supports Google AI-related research and product-facing technology activity connected to Pittsburgh AI and robotics talent."),
    "833cbb3e-de7a-49c4-8308-326bd6673c3a": ("corporate_ai_lab", "Conducts AI research and develops model, safety, science, and product technologies within Google's AI research organization."),
    "117f6fb5-14ec-45ba-81c3-15436d4a7943": ("water_program", "Coordinates Great Lakes policy, planning, and regional collaboration across U.S. states and Canadian provinces."),
    "ae138986-30c4-49f1-b4b3-2e4813e4984e": ("water_program", "Funds and coordinates Great Lakes restoration projects, water-quality improvements, habitat work, and pollution-reduction programs."),
    "2e4b99e8-32f4-49ac-a8f6-f056074c2362": ("water_policy_board", "Administers Arizona groundwater active management programs focused on conservation, withdrawals, planning, and aquifer sustainability."),
    "a32ba9c9-415f-4e7e-9e04-0a704142b9dc": ("chemical_department", "Conducts Harvard chemistry and chemical biology research and education across molecular design, catalysis, synthesis, and biological chemistry."),
    "8261eaac-f5bf-4ce3-9976-3a62d807b7ad": ("data_science", "Supports Harvard data science research and education across AI, statistics, computational methods, and applied domains."),
    "74f79bed-c0aa-4289-804c-2731ad8c743e": ("chemical_department", "Conducts Harvard chemistry and chemical biology research and education across molecular design, catalysis, synthesis, and biological chemistry."),
    "05bf5856-eb0e-42f1-a871-2ebd4b4f5ac3": ("medical_school", "Conducts medical education and biomedical research through Harvard programs and affiliated clinical research networks."),
    "4ee8cac1-c481-4638-bbe6-bebe27e301c7": ("climate_school", "Supports Harvard climate and sustainability research, convening, education, and solution-oriented programs through the Salata Institute."),
    "8bd52c28-3c70-4722-8268-c974b75460d0": ("computer_science_school", "Conducts Harvard engineering and applied-science research and education across AI, materials, climate, computation, and systems."),
    "337604ec-f890-4614-a2ba-c0286b00c38c": ("university_science", "Conducts research and education across science, medicine, engineering, policy, business, law, and humanities through Harvard University."),
    "37f4f30a-7955-4b40-a421-d5fbedd4bbbb": ("innovation_district", "Supports Texas Medical Center life-science commercialization, research translation, company formation, and health innovation tenants."),
    "ca9be16b-ff31-4599-bc37-21b359d77372": ("flood_control", "Plans and implements flood-risk reduction, drainage, stormwater, and watershed projects in the Houston region."),
    "ce163f6d-fec2-4f7f-83a7-c947187a5e29": ("academic_hospital", "Provides clinical care and conducts translational research through Houston Methodist hospital programs and innovation partnerships."),
    "eaf6e3ae-7854-499f-9e6e-1f6a641d68a2": ("water_agency", "Manages Houston public works services including water, wastewater, drainage, streets, and infrastructure delivery."),
    "e1ecc5c9-bef5-4d84-9238-6a21c3e1c38c": ("port_authority", "Manages Houston Ship Channel and port-related infrastructure supporting industrial logistics, trade, dredging, and resilience."),
    "e21ef24e-a410-408c-ab07-e012df1c689e": ("medical_school", "Conducts medical education, biomedical research, and clinical translation within the Mount Sinai health ecosystem."),
    "ac42d61e-6b2c-4c63-ae8a-a8dae32b957d": ("ag_engineering", "Conducts Illinois digital agriculture work involving sensors, automation, analytics, field data, and farm decision-support tools."),
    "9ff88133-1f28-450a-9e81-59a385c6e319": ("renewable_energy_research", "Supports University of Illinois energy research across efficiency, fuels, storage, grid systems, and sustainable industrial transition."),
    "fb86b2f0-9d51-4f5c-9f03-c8680f0d6aca": ("extension", "Delivers University of Illinois extension programming translating research into agricultural, community, environmental, and youth-development guidance."),
    "de988369-f7be-4245-995c-6b3032b4e840": ("materials_chemicals", "Supports University of Illinois materials research through shared facilities, characterization, synthesis, and interdisciplinary materials science."),
    "3fb69bac-a5a4-4616-bd09-fee6e4dc0b3b": ("innovation_district", "Supports UIUC-linked startups, corporate R&D tenants, entrepreneurship programs, and research commercialization at Illinois Research Park."),
    "85a1aa09-49a5-4dd7-b880-9e6ad335b752": ("petrochemicals", "Develops and manufactures olefins, polymers, and related petrochemical products through U.S. production and applications operations."),
    "906905a8-15b5-43d2-9e7a-a1c5fc191f8e": ("agritech_center", "Supports UC Davis food and health innovation linking agriculture, nutrition, food systems, and translational research partnerships."),
    "366e2d54-7011-4eb7-a1aa-3903d9484383": ("climate_research", "Conducts CU Boulder arctic, alpine, climate, hydrology, and earth-system research through INSTAAR."),
    "7c68512c-286e-437b-b6bf-89859c816505": ("agritech_center", "Conducts Texas A&M research linking agriculture, nutrition, human health, food systems, and translational public-health outcomes."),
    "e49bfe49-498f-4c17-9373-e6ce69b537cb": ("renewable_energy_research", "Conducts University of Delaware energy conversion research focused on photovoltaics, materials, devices, and clean-energy systems."),
    "eba690fa-2c38-47ea-bfd8-c8273b294cf5": ("development_finance", "Provides World Bank lending and technical assistance for middle-income and creditworthy countries to support development projects."),
    "e25cf9e7-8ea8-463b-8c31-003e6f654ebd": ("development_finance", "Provides concessional financing and grants for low-income countries through World Bank development programs."),
    "2b833f43-65f8-4c77-bc3b-a54225b00665": ("development_finance", "Invests in and advises private-sector projects in developing countries through World Bank Group private-sector finance tools."),
    "56712aa3-500c-461f-b562-b1a1baa7dfa2": ("development_finance", "Finances rural development and smallholder agriculture programs through loans, grants, and technical assistance."),
    "d8477e91-5768-4321-86f9-a1b256074099": ("water_program", "Supports U.S.-Canada boundary water governance through investigations, recommendations, monitoring, and dispute-prevention mechanisms."),
    "5628e616-04b6-4c67-a711-6f4299f82bf7": ("un_policy_body", "Develops global telecommunications standards, spectrum coordination, digital policy support, and connectivity capacity-building programs."),
    "f776d377-3d68-43bc-afe3-42ca3ddb8e1a": ("national_lab", "Applies Johns Hopkins APL systems engineering and applied research capabilities to health security and mission-driven technology problems."),
    "a63bf3bd-cb63-4d33-978e-34ac40d63995": ("medical_school", "Conducts public health research, education, epidemiology, health policy, and population-health implementation through Johns Hopkins programs."),
    "91fcadb4-c5c3-4ff5-a7fe-c8858d7ac67f": ("academic_hospital", "Conducts Johns Hopkins university and medical research spanning biomedical science, clinical care, public health, and health technology."),
    "94107bec-61a1-4071-b9a4-c44e084a4990": ("life_science_incubator", "Supports early-stage healthcare and life-science companies in Houston through JLABS incubation, facilities, mentoring, and partner access."),
    "25e62fdc-55a7-4467-9cec-93569f861dbe": ("venture", "Invests in and supports venture-backed technology companies, including AI, software, consumer, enterprise, and frontier technology sectors."),
    "6a8365fd-7185-4cae-81a1-6eccccc2721a": ("life_science_incubator", "Provides shared laboratory infrastructure and startup support for life-science companies in the Boston-Cambridge ecosystem."),
    "121a5d68-305d-48cd-9b89-eaca30c00fb2": ("synthetic_biology", "Develops carbon-recycling and gas-fermentation technologies for producing fuels, chemicals, and materials from waste carbon streams."),
    "3ca18917-49fd-48a0-abb0-37a83f1f46e2": ("national_lab", "Conducts national-security, energy, materials, computing, climate, and engineering research through DOE laboratory programs."),
    "f74ea7c5-fa83-4596-8f51-ddc742612b67": ("energy_test_facility", "Conducts LBNL energy technology research across buildings, grid systems, storage, efficiency, and industrial decarbonization."),
    "090110b2-5725-461e-b920-9ba589a46f2a": ("critical_minerals_company", "Develops lithium resource projects and related critical-mineral supply for battery and energy-transition markets."),
    "235ad870-4c23-45fa-8615-b29df5d42214": ("petrochemicals", "Develops and manufactures petrochemicals, polymers, fuels-adjacent products, and circular materials through global operations."),
    "aed5dee4-752a-43b9-b6a0-fe7801305d82": ("petrochemicals", "Operates LyondellBasell's Channelview chemical complex for large-scale petrochemical and polymer production."),
    "9693c60f-f746-43e4-b399-491913e1c8eb": ("earth_sciences_school", "Conducts earth sciences and engineering education and research focused on geology, mining, critical minerals, and resource systems."),
}


def build_update(kind: str, activity: str) -> dict[str, str]:
    values = deepcopy(TEMPLATES[kind])
    values["current_activities"] = activity
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    with SessionLocal() as session:
        session.execute(text("SET LOCAL statement_timeout = '90s'"))
        before = session.scalar(
            select(func.count())
            .select_from(Actor)
            .where(Actor.current_activities.like("Existing GHUS context%"))
        )
        applied: list[str] = []
        skipped: list[tuple[str, str]] = []
        for actor_id, (kind, activity) in ACTORS.items():
            actor = session.get(Actor, UUID(actor_id))
            if actor is None:
                skipped.append((actor_id, "missing"))
                continue
            if not (actor.current_activities or "").startswith("Existing GHUS context"):
                skipped.append((actor.name, "not_generic"))
                continue
            for col, value in build_update(kind, activity).items():
                setattr(actor, col, value)
            applied.append(actor.name)

        if args.dry_run:
            session.rollback()
        else:
            session.commit()

        after = session.scalar(
            select(func.count())
            .select_from(Actor)
            .where(Actor.current_activities.like("Existing GHUS context%"))
        )

    print(f"dry_run={args.dry_run}")
    print(f"planned={len(ACTORS)}")
    print(f"applied={len(applied)}")
    print(f"skipped={len(skipped)}")
    print(f"generic_before={before}")
    print(f"generic_after={after}")
    for name in applied[:120]:
        print(f"APPLIED|{name}")
    for name, reason in skipped[:20]:
        print(f"SKIP|{name}|{reason}")


if __name__ == "__main__":
    main()
