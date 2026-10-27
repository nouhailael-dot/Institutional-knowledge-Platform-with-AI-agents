"""No-Claude refinement pass for still-generic actor technical fields.

This pass only updates rows whose current_activities still starts with the
generic deterministic-fill marker, so it will not overwrite better rows from a
previous Claude/manual pass.
"""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

PROJECT_ROOT = Path(__file__).resolve().parents[2]  # ghus-backend/
sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select, text  # noqa: E402

from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


def rec(focus: str, approach: str, ip: str, constraints: str, role: str) -> dict[str, str]:
    return {
        "primary_technical_focus": focus,
        "technical_approach": approach,
        "technology_ip_notes": ip,
        "key_constraints": constraints,
        "primary_lifecycle_role": role,
    }


TEMPLATES: dict[str, dict[str, str]] = {
    "ai_startup_space": rec(
        "AI startup formation, model applications, founder support, and ecosystem convening.",
        "Uses workspace, events, mentoring, investor access, and operator networks to help AI founders move from idea to company.",
        "Primarily an ecosystem support actor; IP normally remains with participating startups rather than the hub space.",
        "Quality depends on sustained founder deal flow, mentor density, capital access, compute availability, and local AI talent retention.",
        "scaling",
    ),
    "venture": rec(
        "Venture investment in frontier technology, software infrastructure, AI, life sciences, climate, and other high-growth sectors.",
        "Deploys capital plus recruiting, market development, policy, and operating support to scale venture-backed technology companies.",
        "Portfolio company IP typically remains with the companies; influence comes through financing, governance, and network access.",
        "Impact depends on competitive deal access, venture-scale exit paths, regulatory exposure, and portfolio execution risk.",
        "scaling",
    ),
    "accelerator": rec(
        "Startup acceleration across AI, life sciences, climate, hardware, and enterprise technology.",
        "Combines accelerator cohorts, mentorship, investor introductions, and university or regional ecosystem access for early-stage companies.",
        "Startup IP remains with participating companies; the accelerator contributes commercialization pathways and investor access.",
        "Outcomes depend on startup quality, seed funding availability, founder retention, and fit with commercialization channels.",
        "scaling",
    ),
    "bioscience_ecosystem": rec(
        "Bioscience, agtech, health innovation, entrepreneurship, and regional cluster development.",
        "Builds programs, investment links, and partnerships connecting startups, universities, corporations, and civic institutions.",
        "Primarily an ecosystem builder; protectable IP sits with startups, universities, or corporate partners.",
        "Impact depends on capital access, regional talent retention, corporate partner demand, and startup commercialization speed.",
        "scaling",
    ),
    "academic_hospital": rec(
        "Clinical medicine, biomedical discovery, clinical trials, digital health, diagnostics, therapeutics, and translational research.",
        "Links academic medical research, specialty care, clinical data, trials, and partnerships for patient-facing translation.",
        "Clinical inventions may be protected through patents, licenses, startups, and hospital commercialization channels; patient data requires governance.",
        "Translation is constrained by patient safety, clinical workflow fit, reimbursement, regulatory review, trial recruitment, and privacy requirements.",
        "validation",
    ),
    "robotics_company": rec(
        "Mobile robotics, autonomous inspection, warehouse automation, perception, manipulation, and robot control software.",
        "Combines mechanical design, controls, perception, autonomy software, and field testing to commercialize robots for industrial uses.",
        "Strong robotics IP is likely in mechanisms, control systems, autonomy software, sensor integration, and product engineering know-how.",
        "Adoption depends on safety, reliability, unit economics, service support, customer workflow fit, and integration with existing operations.",
        "deployment",
    ),
    "ai_talent": rec(
        "AI education, applied machine learning training, career access, and inclusive technical talent pipelines.",
        "Combines coursework, portfolio projects, industry challenge work, mentoring, and employer connections for undergraduate learners.",
        "Educational program IP is limited; project outputs generally belong to students, partner institutions, or challenge sponsors.",
        "Scale depends on employer participation, student support, curriculum currency, mentor availability, and inclusive recruitment.",
        "scaling",
    ),
    "climate_venture": rec(
        "Climate and clean energy venture investment across power, fuels, materials, industry, buildings, transportation, and carbon management.",
        "Uses patient venture capital, technical diligence, policy awareness, and corporate networks to scale hard-technology climate companies.",
        "Portfolio IP normally resides with the companies; the fund adds capital, diligence, governance, and commercialization support.",
        "Returns depend on long commercialization cycles, capital intensity, policy support, infrastructure access, and customer adoption.",
        "scaling",
    ),
    "geoscience": rec(
        "Applied geoscience for energy, groundwater, carbon storage, critical minerals, subsurface characterization, and earth systems.",
        "Uses field geology, mapping, geophysics, geochemistry, modeling, and public-private research partnerships to characterize resources and risks.",
        "Outputs are usually datasets, models, maps, reports, and applied methods; patentable IP is secondary to research knowledge products.",
        "Work depends on field data access, sponsor alignment, permitting, long geologic timescales, and uncertainty in subsurface models.",
        "validation",
    ),
    "grid_operator": rec(
        "Electric grid operations, wholesale power markets, renewable integration, transmission reliability, and grid balancing.",
        "Operates real-time dispatch, market clearing, forecasting, reliability coordination, and planning processes for grid operations.",
        "IP is mainly operational data, market systems, reliability procedures, software workflows, and grid planning know-how rather than patents.",
        "Reliability, transmission congestion, interconnection queues, extreme weather, storage needs, and market rules constrain adoption speed.",
        "deployment",
    ),
    "environment_regulator": rec(
        "Air quality, emissions regulation, climate policy, clean transportation, fuels, industrial standards, and environmental monitoring.",
        "Uses inventories, regulatory standards, modeling, compliance programs, incentives, and enforcement to reduce pollution and climate impacts.",
        "Core assets are regulatory frameworks, datasets, models, and compliance methods; patentable technology IP is not the primary output.",
        "Policy design must manage legal risk, equity impacts, economic cost, data quality, enforcement capacity, and technology readiness.",
        "validation",
    ),
    "ag_agency": rec(
        "Agricultural policy, specialty crops, pest and disease management, conservation, food safety, and climate-smart farming programs.",
        "Uses regulation, inspection, grants, technical assistance, market programs, and interagency coordination to support agriculture.",
        "Primary assets are program rules, datasets, standards, and implementation capacity; technology IP usually resides with partners.",
        "Program outcomes depend on grower participation, budget cycles, water availability, pest pressure, regulation, and climate variability.",
        "scaling",
    ),
    "green_chem_policy": rec(
        "Green chemistry, safer consumer products, toxics reduction, chemical alternatives assessment, and pollution prevention.",
        "Uses regulatory screening, alternatives analysis, priority product rules, stakeholder input, and lifecycle risk assessment.",
        "Outputs are policy tools, assessments, and compliance frameworks; commercial chemistry IP generally belongs to companies or research partners.",
        "Constraints include data gaps, compliance burden, legal review, substitution risk, and the pace of safer-material commercialization.",
        "validation",
    ),
    "water_agency": rec(
        "Water supply, flood management, drought planning, hydrology, climate resilience, water infrastructure, and statewide water operations.",
        "Combines infrastructure operation, hydrologic modeling, planning, grants, engineering, and interagency coordination for water management.",
        "Core assets are operational datasets, models, engineering plans, and program authority; patented technology is not the primary output.",
        "Work is constrained by hydrologic variability, environmental rules, aging infrastructure, water rights, financing, and climate change.",
        "deployment",
    ),
    "energy_agency": rec(
        "Energy policy, clean energy deployment, grid planning, efficiency, storage, transportation electrification, and energy innovation programs.",
        "Uses planning, standards, grants, public programs, modeling, and market coordination to advance clean energy goals.",
        "Primary assets are program designs, datasets, standards, and public funding mechanisms; technology IP usually remains with grantees or vendors.",
        "Progress depends on grid reliability, permitting, public funding, technology readiness, equity requirements, and utility coordination.",
        "scaling",
    ),
    "university_science": rec(
        "Fundamental science and engineering across AI, computation, materials, energy, climate, physics, biology, and chemistry.",
        "Combines faculty-led research, graduate training, laboratories, national research partnerships, and technology transfer for early-stage discovery.",
        "University IP is managed through technology transfer; much output is publications, open science, datasets, prototypes, and patentable inventions.",
        "Translation depends on research funding, lab infrastructure, faculty capacity, graduate talent, industry partnerships, and commercialization support.",
        "discovery",
    ),
    "ai_lab": rec(
        "Artificial intelligence, machine learning, computational science, algorithms, scientific computing, and data-intensive research.",
        "Combines computer science, applied mathematics, domain science, and interdisciplinary research to develop computational methods and AI applications.",
        "Outputs include publications, software, datasets, prototypes, and patentable methods managed through university technology transfer when applicable.",
        "Progress depends on research funding, compute access, faculty and student capacity, data availability, and translation partners.",
        "discovery",
    ),
    "sustainability_institute": rec(
        "Sustainability science, energy, climate, water, materials, environmental systems, and clean technology research.",
        "Funds and coordinates interdisciplinary research, facilities, fellowships, and partnerships focused on sustainability challenges.",
        "University-managed IP may emerge from sponsored research; the institute also produces publications, prototypes, methods, and collaborative programs.",
        "Impact depends on research funding, interdisciplinary coordination, pilot partners, infrastructure, and pathways from discovery to deployment.",
        "discovery",
    ),
    "catalysis": rec(
        "Catalysis, reaction engineering, renewable fuels, chemical process design, sustainable chemistry, and advanced materials.",
        "Uses experimental catalysis, reactor testing, materials characterization, modeling, and industry-linked research to improve chemical transformations.",
        "Outputs include publications, catalyst formulations, process know-how, prototypes, and inventions handled through university technology transfer.",
        "Key constraints include scale-up risk, catalyst durability, process economics, feedstock quality, safety, and industrial validation requirements.",
        "discovery",
    ),
    "watershed_center": rec(
        "Watershed science, hydrology, water policy, aquatic ecosystems, climate impacts, and water-resource management.",
        "Uses field monitoring, modeling, policy analysis, stakeholder engagement, and interdisciplinary research to support water decisions.",
        "Outputs are mostly datasets, models, publications, policy analyses, and decision-support tools rather than proprietary hardware IP.",
        "Work depends on long-term monitoring, data quality, stakeholder alignment, funding, and changing hydrologic conditions.",
        "validation",
    ),
    "water_operator": rec(
        "Large-scale water conveyance, storage, pumping, drought planning, hydrology, and water infrastructure operations.",
        "Operates water delivery infrastructure, pumping, scheduling, conservation programs, planning, and coordination with water stakeholders.",
        "Core assets are infrastructure, operating data, water agreements, planning models, and engineering know-how rather than patent portfolios.",
        "Operations are constrained by hydrology, drought, legal allocations, energy cost, infrastructure maintenance, and regional growth.",
        "deployment",
    ),
    "fertilizer_company": rec(
        "Nitrogen fertilizer, ammonia production, low-carbon ammonia, hydrogen-linked pathways, and industrial process operations.",
        "Uses large-scale chemical manufacturing, process optimization, emissions management, logistics, and energy inputs to produce nitrogen products.",
        "IP is likely in process know-how, operating practices, partnerships, and project execution rather than a single standalone technology platform.",
        "Constraints include natural gas price exposure, emissions regulation, capital intensity, hydrogen supply, logistics, and fertilizer market cycles.",
        "deployment",
    ),
    "specialty_chemicals": rec(
        "Specialty chemicals, fluoroproducts, advanced materials, thermal management, process chemistry, and industrial manufacturing.",
        "Develops and manufactures specialty materials through process R&D, formulation work, plant operations, compliance, and customer applications support.",
        "Likely IP includes formulations, process know-how, materials applications, patents, and trade secrets across specialty chemical product lines.",
        "Constraints include environmental compliance, product stewardship, feedstock cost, process safety, customer qualification, and regulatory scrutiny.",
        "deployment",
    ),
    "petrochemicals": rec(
        "Petrochemicals, olefins, polymers, specialty chemicals, process engineering, and large-scale chemical manufacturing.",
        "Uses integrated chemical production assets, process R&D, catalyst and process optimization, logistics, and customer applications support.",
        "IP is likely concentrated in process know-how, catalyst use, polymer grades, plant operations, patents, and trade secrets.",
        "Constraints include feedstock price volatility, emissions rules, process safety, commodity cycles, capital intensity, and customer qualification timelines.",
        "deployment",
    ),
    "commodity_exchange": rec(
        "Agricultural commodity markets, futures contracts, price discovery, risk management, and market infrastructure.",
        "Provides exchange-based trading, clearing-linked market rules, contract specifications, and price signals for market participants.",
        "Core assets are exchange rules, contract designs, market data, trading systems, and trust infrastructure rather than technology patents.",
        "Constraints include market liquidity, regulatory oversight, contract relevance, clearing risk, data integrity, and competition.",
        "scaling",
    ),
    "climate_research": rec(
        "Climate science, atmospheric research, cryosphere, hydrology, earth-system modeling, hazards, and environmental data.",
        "Uses field observations, satellite and instrument data, modeling, interdisciplinary teams, and federal-university partnerships.",
        "Outputs include datasets, models, publications, instruments, software, and decision-support methods, with limited proprietary IP emphasis.",
        "Work depends on sustained funding, observational infrastructure, data continuity, model uncertainty, and interdisciplinary coordination.",
        "discovery",
    ),
    "clinical_research_hospital": rec(
        "Clinical research, translational medicine, early clinical trials, rare disease studies, diagnostics, and patient-centered biomedical research.",
        "Provides a dedicated clinical research hospital environment combining investigators, protocols, patient care, and regulatory oversight.",
        "IP may arise from biomedical discoveries and clinical methods; patient data, biospecimens, and trial records require strict governance.",
        "Constraints include patient recruitment, ethics review, safety monitoring, privacy, protocol complexity, and translation beyond the hospital setting.",
        "validation",
    ),
    "healthcare_innovation": rec(
        "Healthcare technology commercialization, medical devices, diagnostics, digital health, therapeutics, and clinical innovation partnerships.",
        "Identifies clinical inventions, supports licensing and startup formation, connects clinicians with industry partners, and guides commercialization pathways.",
        "Directly supports protected healthcare IP including patents, licenses, software, clinical know-how, and startup assets.",
        "Success depends on regulatory pathways, clinical validation, reimbursement, partner fit, product-market need, and health-system adoption.",
        "scaling",
    ),
    "steel_company": rec(
        "Iron ore, steel manufacturing, advanced steels, mining operations, process optimization, and industrial decarbonization.",
        "Uses integrated mining and steelmaking operations, materials engineering, process control, customer qualification, and capital project execution.",
        "IP is likely in process know-how, materials grades, plant operations, customer specifications, patents, and trade secrets.",
        "Constraints include energy cost, emissions rules, commodity cycles, capital intensity, customer qualification, and plant reliability.",
        "deployment",
    ),
    "ai_engineering": rec(
        "AI engineering, trustworthy AI systems, software engineering for AI, assurance, human-centered AI, and operational AI adoption.",
        "Combines applied research, methods, tools, evaluation frameworks, and partnerships to make AI systems reliable in real-world settings.",
        "Outputs include methods, software tools, reports, datasets, evaluation frameworks, and possible university-managed inventions.",
        "Constraints include model reliability, assurance, data access, compute cost, security, governance, and translation into production workflows.",
        "validation",
    ),
    "cybersecurity": rec(
        "Cybersecurity, privacy, trustworthy computing, secure systems, network defense, policy, and AI-security intersections.",
        "Uses interdisciplinary research, testbeds, software tools, policy analysis, and industry/government partnerships to improve digital security.",
        "Outputs include publications, software, datasets, testbeds, methods, and university-managed inventions where protectable.",
        "Constraints include evolving threats, data sensitivity, deployment complexity, sponsor requirements, talent competition, and reproducibility.",
        "discovery",
    ),
    "machine_learning": rec(
        "Machine learning, artificial intelligence, statistical learning, optimization, data science, and applied AI research.",
        "Combines faculty-led research, graduate education, algorithms, theory, benchmarks, datasets, and interdisciplinary application projects.",
        "Outputs include publications, open-source software, datasets, models, and university-managed inventions when applicable.",
        "Progress depends on compute access, data quality, research funding, faculty and student capacity, and responsible deployment pathways.",
        "discovery",
    ),
    "robotics_institute": rec(
        "Robotics, autonomous systems, perception, manipulation, mobility, human-robot interaction, and embodied AI.",
        "Combines algorithms, mechanical systems, sensors, controls, simulation, field testing, and interdisciplinary robotics research.",
        "Outputs include publications, prototypes, software, datasets, patents, and startups through university commercialization channels.",
        "Constraints include hardware cost, safety, field reliability, compute, sim-to-real transfer, funding, and application-specific validation.",
        "discovery",
    ),
    "computer_science_school": rec(
        "Computer science, artificial intelligence, robotics, human-computer interaction, software systems, security, and data science.",
        "Combines academic departments, research institutes, labs, education, open-source work, and partnerships across computing fields.",
        "Outputs include publications, software, datasets, prototypes, startups, and university-managed patents or licenses.",
        "Translation depends on talent, compute resources, research funding, interdisciplinary partnerships, and commercialization support.",
        "discovery",
    ),
    "ag_college": rec(
        "Agriculture and life sciences, plant science, food systems, animal science, sustainability, biotechnology, and extension.",
        "Combines research, education, experiment stations, extension, field trials, and partnerships with growers, agencies, companies, and communities.",
        "University IP may include biological materials, software, datasets, methods, crop or food technologies, and licensed inventions.",
        "Translation depends on field validation, extension capacity, research funding, grower adoption, regulation, and partner demand.",
        "discovery",
    ),
    "state_energy_office": rec(
        "Clean energy programs, energy efficiency, building decarbonization, transportation electrification, grid modernization, and climate implementation.",
        "Uses grants, policy design, technical assistance, market programs, data, and coordination with utilities, agencies, communities, and private partners.",
        "Primary assets are program designs, datasets, funding mechanisms, standards, and implementation partnerships rather than proprietary technology IP.",
        "Progress depends on public funding, grid capacity, permitting, consumer adoption, equity requirements, workforce capacity, and utility coordination.",
        "scaling",
    ),
    "mining_department": rec(
        "Mining engineering, mineral extraction, mine safety, critical minerals, geomechanics, processing, and sustainable resource development.",
        "Combines engineering research, field work, laboratory testing, modeling, education, and industry partnerships for mining and mineral systems.",
        "Outputs include publications, engineering methods, datasets, prototypes, patents, and workforce training rather than a single product platform.",
        "Constraints include field validation, safety, permitting, environmental impact, commodity cycles, capital intensity, and industry adoption.",
        "discovery",
    ),
    "water_policy_board": rec(
        "Water conservation, water planning, flood and drought resilience, watershed health, and water policy.",
        "Uses planning, grants, policy guidance, technical studies, data, and coordination with basins, local governments, and water users.",
        "Core assets are plans, datasets, grants, policy frameworks, and technical guidance rather than proprietary technology IP.",
        "Constraints include hydrologic variability, legal water rights, basin priorities, public funding, climate change, and stakeholder alignment.",
        "validation",
    ),
    "energy_policy_center": rec(
        "Energy policy, geopolitics, power markets, fuels, climate policy, carbon management, and energy-transition strategy.",
        "Uses policy research, economic analysis, convening, publications, and expert networks to inform public and private energy decisions.",
        "Outputs are policy papers, datasets, models, convenings, and expert analysis; proprietary technology IP is not the primary output.",
        "Influence depends on policy relevance, data quality, political context, sponsor trust, and uptake by decision makers.",
        "validation",
    ),
    "climate_school": rec(
        "Climate science, sustainability, adaptation, earth systems, climate justice, policy, and environmental data.",
        "Combines interdisciplinary research, education, field science, analytics, policy work, and partnerships across climate-related disciplines.",
        "Outputs include publications, datasets, models, tools, policy analysis, and university-managed inventions where applicable.",
        "Impact depends on research funding, data continuity, interdisciplinary coordination, partner uptake, and implementation capacity.",
        "discovery",
    ),
    "data_science": rec(
        "Data science, artificial intelligence, machine learning, responsible data use, analytics, and cross-domain computational research.",
        "Combines faculty research, education, data-intensive projects, industry partnerships, methods development, and interdisciplinary application work.",
        "Outputs include publications, software, datasets, models, methods, and university-managed inventions where applicable.",
        "Constraints include data access, privacy, compute resources, responsible AI governance, funding, and translation into partner workflows.",
        "discovery",
    ),
    "medical_school": rec(
        "Medical education, biomedical science, clinical research, diagnostics, therapeutics, public health, and translational medicine.",
        "Combines faculty-led biomedical research, clinical training, medical center partnerships, labs, trials, and technology transfer.",
        "University medical IP can include patents, therapeutics, diagnostics, software, data resources, and licensed inventions.",
        "Translation depends on funding, clinical validation, patient privacy, regulatory pathways, hospital partnerships, and commercialization support.",
        "discovery",
    ),
    "upstream_energy": rec(
        "Oil and gas exploration and production, subsurface engineering, methane management, operations analytics, and energy-system performance.",
        "Uses geoscience, reservoir engineering, drilling, operations technology, emissions monitoring, project execution, and asset management.",
        "IP is likely in subsurface data, operational know-how, process methods, software workflows, patents, and trade secrets.",
        "Constraints include commodity prices, emissions regulation, permitting, capital discipline, safety, geology, and energy-transition pressure.",
        "deployment",
    ),
    "agritech_center": rec(
        "Specialty crops, plant breeding, plant pathology, food science, controlled environment agriculture, and agricultural extension.",
        "Combines experiment-station research, field trials, laboratories, extension, grower partnerships, and commercialization channels.",
        "University IP may include varieties, biological materials, methods, software, datasets, and licensed inventions; extension outputs are often public-facing.",
        "Impact depends on field validation, grower adoption, seasonal cycles, funding, pest and climate pressures, and commercialization support.",
        "validation",
    ),
    "ai_initiative": rec(
        "Artificial intelligence, machine learning, responsible AI, data science, robotics-adjacent systems, and domain-specific AI applications.",
        "Coordinates university AI research, education, seminars, faculty networks, and interdisciplinary projects across campuses and disciplines.",
        "Outputs include publications, models, software, datasets, methods, and university-managed inventions where appropriate.",
        "Progress depends on compute access, data availability, research funding, responsible AI governance, and interdisciplinary coordination.",
        "discovery",
    ),
    "tech_transfer": rec(
        "University technology licensing, invention disclosure, patents, startup formation, industry licensing, and research commercialization.",
        "Evaluates inventions, manages IP protection, negotiates licenses, supports startups, and connects researchers with commercial partners.",
        "Directly handles university IP portfolios, patents, licenses, material transfer agreements, and startup-related commercialization assets.",
        "Success depends on invention quality, market demand, patentability, faculty engagement, partner fit, and licensing execution.",
        "scaling",
    ),
    "extension": rec(
        "Agricultural extension, community education, applied crop and food systems, youth development, natural resources, and local problem solving.",
        "Uses county-based extension staff, applied research translation, workshops, demonstrations, technical assistance, and community partnerships.",
        "IP emphasis is low; outputs are education, technical guidance, decision tools, public materials, and applied program know-how.",
        "Reach depends on local staffing, funding, community trust, grower participation, seasonal conditions, and alignment with research expertise.",
        "scaling",
    ),
    "dairy_research": rec(
        "Dairy systems, animal nutrition, herd management, feed efficiency, manure and nutrient management, and dairy production research.",
        "Uses herd facilities, applied trials, monitoring, nutrition studies, producer engagement, and research partnerships to test dairy practices.",
        "Outputs include datasets, protocols, field guidance, biological materials, methods, and potentially university-managed inventions.",
        "Constraints include animal welfare, trial design, farm economics, feed and manure variability, regulatory requirements, and producer adoption.",
        "validation",
    ),
    "food_pilot": rec(
        "Food science, pilot-scale processing, product development, food safety, formulation, and process validation.",
        "Provides pilot equipment, technical staff, processing trials, safety guidance, and scale-up support for foods and ingredients.",
        "IP may arise in formulations, processes, recipes, datasets, and partner-owned products; facility know-how supports commercialization.",
        "Constraints include food safety, equipment availability, sanitation, ingredient variability, regulatory requirements, and partner scale-up capacity.",
        "demonstration",
    ),
    "horticulture": rec(
        "Horticulture, specialty crops, plant physiology, controlled environment agriculture, crop management, and sustainable production systems.",
        "Combines faculty research, field trials, greenhouse studies, extension, breeding-adjacent work, and grower partnerships.",
        "University IP may include plant materials, methods, data, decision tools, software, and inventions; many outputs are publications and extension guidance.",
        "Impact depends on field validation, seasonal cycles, grower adoption, funding, pest pressure, climate conditions, and extension reach.",
        "discovery",
    ),
    "soil_lab": rec(
        "Soil health assessment, soil biology, soil testing, crop-soil interactions, nutrient management, and regenerative agriculture metrics.",
        "Uses laboratory assays, field samples, indicators, datasets, outreach, and applied research to evaluate soil function and management effects.",
        "Outputs include testing methods, datasets, protocols, decision support, publications, and extension guidance; proprietary IP is secondary.",
        "Constraints include sampling variability, regional soil differences, interpretation standards, farmer adoption, lab capacity, and long-term monitoring needs.",
        "validation",
    ),
    "cornell_tech": rec(
        "Digital technology, AI, urban systems, entrepreneurship, product design, computer science, and applied technology education.",
        "Combines graduate education, applied research, studio projects, industry partnerships, startups, and New York City technology networks.",
        "Outputs include student ventures, software, prototypes, publications, datasets, and university-managed inventions where applicable.",
        "Impact depends on faculty and student talent, employer partnerships, startup funding, compute access, and translation into durable products.",
        "scaling",
    ),
}


ACTORS: dict[str, tuple[str, str]] = {
    "49aaadb1-2b03-4162-9897-fff046402d13": ("ai_startup_space", "Supports AI founders and events in the Seattle ecosystem through workspace access, community programming, and investor connections."),
    "0d852be7-bbfa-44a6-b1c2-f44a4a20255a": ("venture", "Invests in and supports high-growth technology startups, with AI and infrastructure among core investment themes."),
    "8f35e3b8-c458-4a62-b5c4-75326e267433": ("accelerator", "Runs startup cohorts and investor-facing programming for Berkeley-connected and global startups."),
    "ba4fce8e-f49b-415c-9397-e8d3b5548500": ("bioscience_ecosystem", "Supports bioscience and agtech startups while strengthening the St. Louis innovation ecosystem through programs and partnerships."),
    "3f92e640-a8c5-4192-91e7-ec2a9885516c": ("academic_hospital", "Conducts pediatric clinical care and translational research in diagnostics, therapeutics, data science, and child health."),
    "cee3105d-1be6-4a92-a542-d94eec298b65": ("robotics_company", "Develops and deploys commercial robots for inspection, mobility, manipulation, and warehouse automation use cases."),
    "03917781-15a0-4958-91c4-1245a5328869": ("ai_talent", "Runs AI training and career-access programming for undergraduate students through Cornell Tech and partner institutions."),
    "a143b729-5742-4df9-950b-e34f0c917e4d": ("ai_talent", "Runs AI training and career-access programming for undergraduate students through Cornell Tech and partner institutions."),
    "aa550587-df8d-4d23-8fe7-a5fbdcb79056": ("climate_venture", "Invests in companies developing technologies intended to reduce greenhouse gas emissions across major energy and industrial systems."),
    "34651f8b-3b1b-44f6-b36d-c720ad0901eb": ("academic_hospital", "Provides advanced clinical care and conducts translational biomedical research across major disease and therapeutic areas."),
    "76523e11-ee12-47a3-aad9-5f9476cf26a9": ("geoscience", "Conducts University of Texas applied geoscience research supporting energy, water, carbon storage, and mineral-resource decisions."),
    "5d0e0553-2823-4275-a281-5a12d93209bf": ("grid_operator", "Operates California wholesale electricity markets and grid-balancing functions while integrating large volumes of renewable generation."),
    "85488087-e3bf-4693-b50d-37cb8404b719": ("environment_regulator", "Develops and implements California air quality and climate regulations affecting vehicles, fuels, industry, and emissions markets."),
    "2b019c6e-e591-422e-8d37-4faee1676106": ("ag_agency", "Runs state agriculture programs covering crop protection, food safety, conservation incentives, markets, and farmer support."),
    "d67324ab-5ade-4147-9e4b-cc6b52cbc99f": ("green_chem_policy", "Implements California safer-product and green-chemistry policy work focused on reducing hazardous chemical exposures."),
    "e43f5e9b-2173-4e37-bc86-fde1f2a55819": ("water_agency", "Manages California water resources programs and supports infrastructure, flood, drought, and climate-resilience planning."),
    "a4567705-6060-47e8-9acb-b79c54229776": ("energy_agency", "Leads California energy planning and clean-energy programs, including efficiency, grid modernization, fuels, and technology deployment support."),
    "e43cbbcd-9a27-4d63-96e5-bfae8b125cfe": ("grid_operator", "Operates California wholesale electricity markets and grid-balancing functions while integrating large volumes of renewable generation."),
    "b3e3bb33-0891-4680-abde-f06169a3d2a1": ("university_science", "Conducts frontier research and education across science and engineering fields, including AI, energy, climate, materials, and life sciences."),
    "f5d8dec7-e47f-479f-bcbf-d5ff06b5738e": ("water_operator", "Operates major California water conveyance and storage infrastructure serving municipal, agricultural, and environmental water needs."),
    "3b1ab64a-09a1-46ee-90cb-aac66834f763": ("water_policy_board", "Implements California water quality and water rights programs through statewide and regional regulatory boards."),
    "ef328bd5-77be-4b29-b447-00e955032b9b": ("ai_lab", "Conducts Caltech research and education in AI, machine learning, algorithms, and computational methods for scientific and engineering problems."),
    "afef0ef5-1e3d-4a22-9ac9-7a3427c3fde9": ("sustainability_institute", "Supports Caltech sustainability research and translation across energy, climate, water, materials, and environmental systems."),
    "24ed7d2a-2392-4a3f-a177-5c74f5d57c40": ("computer_science_school", "Conducts Carnegie Mellon research and education across AI, robotics, software, cybersecurity, engineering, and technology commercialization."),
    "d876514a-aa12-446f-8dad-543b7bb2cc3e": ("catalysis", "Conducts catalysis and reaction engineering research for energy innovation, including renewable fuels and chemical conversion pathways."),
    "fd2ade11-56ac-4fdd-800d-7963c24d84f7": ("catalysis", "Conducts University of Delaware catalysis and reaction-engineering research with relevance to energy, chemicals, and sustainable manufacturing."),
    "6b317a41-4a02-4a6e-acd9-c8d03702a53a": ("watershed_center", "Conducts UC Davis watershed research and applied analysis for water management, ecosystems, climate adaptation, and policy decisions."),
    "00aa13dc-14c2-4ff1-a336-38dfb2ec171b": ("water_operator", "Delivers Colorado River water through Arizona canal infrastructure and supports conservation, reliability, and drought-response programs."),
    "2795f685-1324-456e-a836-3027b1d86726": ("fertilizer_company", "Operates nitrogen fertilizer and ammonia production assets while pursuing efficiency and lower-carbon production pathways where commercially viable."),
    "f1cca5a8-d32e-44bf-bbdb-172739fc1528": ("specialty_chemicals", "Produces specialty chemical and materials products while supporting process improvement, applications development, and responsible product stewardship."),
    "75034186-c4c7-4193-8461-db1300c59cd2": ("petrochemicals", "Develops and operates petrochemical and polymer production assets serving packaging, industrial, energy, and materials markets."),
    "efccca07-4811-4544-a4fd-66cb8a4974a8": ("petrochemicals", "Serves as a major Chevron Phillips Chemical manufacturing site for petrochemical production and related plant operations."),
    "6832646a-9929-4941-b5e2-69302c9ff047": ("commodity_exchange", "Supports price discovery and hedging for agricultural commodities through exchange infrastructure now associated with CME Group."),
    "e3b7946c-14b8-4c3d-a3c4-92d28a611cf8": ("climate_research", "Conducts environmental and climate research linking the University of Colorado Boulder with federal earth-system science programs."),
    "98a50f29-78b8-4e82-91db-cd136c93b8c6": ("academic_hospital", "Provides advanced clinical care and conducts translational research across major disease areas and patient-care technologies."),
    "7dbdad03-d5c9-4918-b945-a0f73fd61db5": ("healthcare_innovation", "Commercializes Cleveland Clinic innovations through licensing, startup support, partnerships, and product-development pathways."),
    "f9a12ae5-d8ce-4d95-bcd9-ff5f95882f8a": ("steel_company", "Operates mining and steel production assets serving automotive, infrastructure, manufacturing, and industrial materials markets."),
    "b6ea9748-974d-4fe7-ad89-3ac52eff6435": ("clinical_research_hospital", "Supports NIH intramural clinical studies by providing patient care, protocol execution, and translational research infrastructure."),
    "8786f32e-8d20-4a10-9502-8e0f8ce66450": ("commodity_exchange", "Runs global derivatives marketplace infrastructure, including agricultural, energy, metals, interest-rate, equity, and financial contracts."),
    "4d365fee-22f5-469e-9a1f-21c3b872a87a": ("ai_engineering", "Develops AI engineering practices and applied research for building, evaluating, and deploying dependable AI-enabled systems."),
    "cdd7e43f-e72d-4d3e-bc7e-30a0f3f75836": ("cybersecurity", "Conducts Carnegie Mellon cybersecurity and privacy research while engaging partners on secure technology development and workforce needs."),
    "841d0acf-7891-4ff0-a3d7-3bb10bae2955": ("cybersecurity", "Conducts cybersecurity research with relevance to AI-enabled systems, privacy, resilience, and secure digital infrastructure."),
    "bd276510-4c3f-4367-99c5-3c9e690cb75e": ("machine_learning", "Conducts machine learning research and education across AI methods, theory, systems, and applications."),
    "09bdae02-d495-412b-b16e-fca237305b97": ("robotics_institute", "Conducts robotics research and education across autonomy, perception, manipulation, field robotics, and human-robot interaction."),
    "102ac9fa-4a89-43a4-9f3e-ef775184e209": ("computer_science_school", "Conducts Carnegie Mellon computer science research and education across AI, robotics, systems, security, and human-centered computing."),
    "a36e2798-d3c5-42c2-b4a8-5dacc00a1fad": ("ag_college", "Conducts UC Davis agriculture and environmental research and education linked to crop systems, sustainability, food, water, and climate adaptation."),
    "5eb46257-622e-4730-9126-b4144c87cd4a": ("ag_college", "Conducts University of Illinois agricultural, food, environmental, and life-science research and education."),
    "4ce6ad1e-64c0-4310-b927-64baecf5dd97": ("ag_college", "Conducts Cornell agriculture and life-science research, education, and extension across food, crops, animals, environment, and biotechnology."),
    "4c0a347a-0500-4669-a569-77e5f3f0f174": ("ag_college", "Conducts Texas A&M agriculture and life-science research, teaching, and outreach supporting crop, animal, food, and resource systems."),
    "d138dfd2-00ac-482f-b122-1aac44a706b6": ("state_energy_office", "Implements Colorado clean-energy and climate programs supporting efficiency, electrification, renewable energy, and community energy projects."),
    "2123801c-750c-4785-891c-4451c94fbc4d": ("mining_department", "Conducts mining engineering research and education at Colorado School of Mines with relevance to critical minerals and resource operations."),
    "c048f214-1965-4ee5-8a0d-2c62d5993e18": ("university_science", "Conducts research and education spanning climate resilience, water, agriculture, health, engineering, and environmental systems."),
    "971072d6-8e4e-4056-b563-3544b75702e3": ("watershed_center", "Supports Colorado State University water research, education, and engagement across hydrology, watersheds, policy, and resilience."),
    "2e365753-e9a4-4282-910c-f1da584ac295": ("water_policy_board", "Leads Colorado water planning, conservation, flood mitigation, watershed health, and drought-related public programs."),
    "781015c4-7c4a-4364-b9f8-c8628420524b": ("energy_policy_center", "Produces energy policy analysis and convenes experts on energy markets, security, climate, and technology transition issues."),
    "9cb90ded-8a67-4693-a93f-599d2a164b73": ("climate_school", "Conducts Columbia climate research, education, and engagement across earth systems, adaptation, sustainability, and climate policy."),
    "9da5c119-58ce-4f5a-bb4a-5fb3dbba499b": ("data_science", "Supports Columbia data science research and education across AI, analytics, health, climate, urban systems, and social-impact domains."),
    "076667b0-4dd5-4477-897b-2bb38cfb2988": ("academic_hospital", "Provides clinical care and conducts biomedical and translational research through Columbia University medical programs."),
    "4cd76ef6-b34c-4f54-ae1c-a6a2506440ed": ("medical_school", "Conducts medical education and biomedical research tied to Columbia clinical and translational health programs."),
    "f29800c7-aa0e-4945-829b-a84f2947a274": ("upstream_energy", "Operates upstream oil and gas assets while applying subsurface, operations, and emissions-management technologies across its portfolio."),
    "55c397bd-1a7a-4cb6-85c0-dc38c99f05e1": ("agritech_center", "Conducts Cornell agricultural research and extension from the AgriTech campus, with emphasis on specialty crops, food, and applied plant systems."),
    "89ee8c55-0fad-47f8-a500-49528bc62c6a": ("ai_initiative", "Supports Cornell-wide AI research and education by connecting faculty, students, programs, and applied AI initiatives."),
    "29acca5c-2cd8-4d99-a845-6b5ed5b89fcd": ("ai_initiative", "Supports Cornell-wide AI research and education by connecting faculty, students, programs, and applied AI initiatives."),
    "b6af3f17-1aa5-42ef-a0ec-af8a2564e476": ("tech_transfer", "Manages Cornell technology transfer activities, including invention disclosures, licensing, startup support, and commercialization partnerships."),
    "a3edee14-a96d-4402-aeb5-eca830ab5480": ("extension", "Delivers Cornell extension programming that translates research into practical guidance for farms, communities, families, and local organizations."),
    "d2a0d6cd-3fa9-4429-963e-626d1f9208bc": ("dairy_research", "Supports Cornell dairy research and applied validation for production, animal health, nutrition, and environmental management questions."),
    "9329e6dd-498a-4592-ac15-cac1f21c5d45": ("food_pilot", "Supports pilot-scale food processing and product-development work for Cornell researchers, students, and external partners."),
    "683433a2-6977-42f3-9cb0-aa47a7f15bba": ("horticulture", "Conducts Cornell horticulture research and education supporting specialty crops, production systems, plant management, and grower guidance."),
    "b122c8be-71b0-44ab-80f8-976d6f519211": ("soil_lab", "Provides soil health research, testing, interpretation, and applied guidance for agricultural systems and field validation."),
    "0a90acaf-2458-4af2-bc52-1327f66835c9": ("cornell_tech", "Operates Cornell Tech programs in New York City focused on applied technology, AI, entrepreneurship, and industry-connected education."),
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
    for name in applied[:80]:
        print(f"APPLIED|{name}")
    for name, reason in skipped[:20]:
        print(f"SKIP|{name}|{reason}")


if __name__ == "__main__":
    main()
