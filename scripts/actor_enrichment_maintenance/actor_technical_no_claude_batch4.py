"""Fourth no-Claude actor technical refinement pass."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from actor_technical_no_claude_batch3 import TEMPLATES, rec  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TEMPLATES.update(
    {
        "carbon_research": rec(
            "Carbon management, carbon materials, carbon utilization, industrial decarbonization, chemical conversion, and energy-transition systems.",
            "Combines academic research, industry partnerships, materials science, chemical engineering, systems analysis, and translational project design.",
            "Outputs may include publications, datasets, process concepts, materials, patents, licenses, and partner-specific technical know-how.",
            "Constraints include scale-up cost, feedstock variability, emissions accounting, industrial partner fit, permitting, and market demand.",
            "validation",
        ),
        "farming_systems_trial": rec(
            "Long-term farming systems, soil health, nutrient cycling, crop rotations, water, climate resilience, and sustainable agriculture.",
            "Uses long-term field trials, soil and crop measurements, data analysis, grower engagement, and agroecosystem comparisons.",
            "Outputs are mainly datasets, protocols, publications, field guidance, decision tools, and applied methods rather than proprietary IP.",
            "Impact depends on long monitoring periods, field variability, funding, weather, management continuity, and grower adoption.",
            "validation",
        ),
        "water_utility": rec(
            "Municipal water supply, wastewater, reuse, conservation, infrastructure operations, drought planning, and water quality.",
            "Uses utility operations, engineering, treatment systems, planning, customer programs, asset management, and regulatory compliance.",
            "IP emphasis is low; core assets are infrastructure, operating data, treatment methods, plans, permits, and utility know-how.",
            "Constraints include drought, water rights, infrastructure age, treatment cost, regulation, rate affordability, and climate variability.",
            "deployment",
        ),
        "electric_utility": rec(
            "Electric power delivery, grid modernization, distributed energy, storage, wildfire or resilience planning, and customer-scale deployment.",
            "Uses utility planning, engineering, grid operations, procurement, pilots, customer programs, and regulatory filings.",
            "Core assets include grid infrastructure, operational data, programs, interconnection workflows, and engineering know-how rather than standalone IP.",
            "Constraints include reliability, regulation, capital planning, wildfire or weather risk, interconnection queues, customer adoption, and affordability.",
            "deployment",
        ),
        "software_engineering": rec(
            "Software engineering, cybersecurity, AI assurance, systems resilience, secure development, and mission-critical software practices.",
            "Uses applied research, methods, tools, assessments, training, standards, and government or industry partnerships.",
            "Outputs include software, methods, reports, datasets, evaluation frameworks, training materials, and protected technical know-how.",
            "Constraints include sponsor requirements, security, legacy systems, adoption in production workflows, verification difficulty, and talent needs.",
            "validation",
        ),
        "space_company": rec(
            "Launch systems, spacecraft, propulsion, satellite deployment, manufacturing, mission operations, and aerospace systems engineering.",
            "Uses vehicle engineering, manufacturing, testing, launch operations, software, supply chains, and iterative hardware development.",
            "Likely IP includes vehicle designs, propulsion systems, software, manufacturing methods, patents, test data, and trade secrets.",
            "Constraints include launch safety, certification, capital intensity, supply chains, reliability, regulation, and mission assurance.",
            "deployment",
        ),
        "consumer_solar": rec(
            "Residential solar, battery storage, distributed energy, customer acquisition, financing, installation, and grid services.",
            "Combines project finance, rooftop installation, software, customer operations, storage integration, and utility interconnection workflows.",
            "IP is mainly software, customer data, financing structures, installation processes, partner networks, and operational know-how.",
            "Constraints include interest rates, policy incentives, interconnection rules, customer acquisition cost, equipment supply, and regulatory changes.",
            "deployment",
        ),
        "bioengineering": rec(
            "Bioengineering, biomedical devices, synthetic biology, tissue engineering, diagnostics, computational biology, and translational health technology.",
            "Combines engineering design, wet-lab research, computation, clinical partnerships, prototypes, and technology transfer.",
            "Outputs include publications, prototypes, software, biological materials, devices, patents, and university-managed licenses.",
            "Constraints include biological complexity, clinical validation, regulatory review, manufacturing, funding, and partner readiness.",
            "discovery",
        ),
        "engineering_school": rec(
            "Engineering, AI, robotics, materials, energy, computing, infrastructure, bioengineering, and applied technology research.",
            "Combines faculty-led research, laboratories, prototypes, education, industry partnerships, and technology transfer.",
            "Outputs include publications, software, prototypes, datasets, patents, licenses, and startups through university commercialization channels.",
            "Translation depends on research funding, lab infrastructure, partner demand, student talent, safety, and commercialization support.",
            "discovery",
        ),
        "un_children_development": rec(
            "Child health, nutrition, education, water and sanitation, protection, humanitarian response, and development implementation.",
            "Uses country programs, procurement, data, grants, technical assistance, advocacy, partnerships, and emergency response systems.",
            "Core assets are programs, data, guidance, procurement channels, partnerships, and field implementation capacity rather than proprietary technology IP.",
            "Impact depends on country access, funding, conflict or disaster conditions, local capacity, procurement, data quality, and partner coordination.",
            "scaling",
        ),
        "un_environment": rec(
            "Environmental policy, climate, biodiversity, pollution, resource efficiency, environmental monitoring, and international implementation support.",
            "Uses assessments, conventions support, policy guidance, data, capacity-building, convening, and country-level technical assistance.",
            "Core assets are assessments, datasets, policy frameworks, implementation guidance, and convening authority rather than proprietary technology IP.",
            "Influence depends on member-state support, funding, data quality, treaty processes, partner capacity, and implementation follow-through.",
            "validation",
        ),
        "un_science_education": rec(
            "Education, science, culture, communication, information policy, knowledge systems, capacity-building, and international cooperation.",
            "Uses standards, programs, research networks, technical assistance, country support, convening, and policy guidance.",
            "Core assets are frameworks, reports, data, networks, guidance, and convening authority rather than proprietary technology IP.",
            "Impact depends on member-state alignment, funding, national implementation capacity, data quality, and cross-sector coordination.",
            "validation",
        ),
        "un_industrial_development": rec(
            "Industrial development, manufacturing capacity, clean industry, standards, SME upgrading, energy efficiency, and technology transfer.",
            "Uses technical cooperation, policy advice, pilot projects, capacity-building, convening, and public-private partnerships.",
            "IP emphasis is low; value lies in implementation methods, standards, project data, partnerships, and technical assistance capacity.",
            "Impact depends on country demand, financing, industrial partner capacity, policy alignment, data quality, and project execution.",
            "scaling",
        ),
    }
)


ACTORS: dict[str, tuple[str, str]] = {
    "f2ee547b-96e3-43e0-9f0e-e6aad2f5acda": ("innovation_district", "Supports UIUC-linked startups, corporate R&D tenants, entrepreneurship programs, and research commercialization at Research Park."),
    "bc762eff-0bac-48e6-a002-5cae6955602c": ("innovation_district", "Operates Research Triangle Park as a regional innovation district for companies, universities, research organizations, and technology workers."),
    "69b3aba5-c2fa-4cf1-a26f-e31072c7ff93": ("energy_policy_center", "Produces Rice Baker Institute energy analysis on markets, geopolitics, technology, and policy for energy-transition decisions."),
    "a48a5c50-4aef-4c37-b750-122f83be0e1a": ("materials_chemicals", "Conducts Rice materials science research across nanomaterials, polymers, energy materials, characterization, and device-relevant systems."),
    "5c7867c5-d156-4e2a-9983-a29023d36f63": ("carbon_research", "Conducts Rice Carbon Hub research on carbon materials, hydrocarbons, industrial decarbonization, and carbon-management pathways."),
    "8637c318-8d83-4fb0-9252-23ff6b90af8e": ("catalysis", "Conducts Rice chemical and biomolecular engineering research across reaction engineering, materials, catalysis, and bioprocessing."),
    "617e540e-5acd-4b83-9c86-41d055e3b2a5": ("materials_chemicals", "Conducts Rice Smalley-Curl Institute research in nanoscience, materials, chemistry, energy, and molecular-scale systems."),
    "d92e7aed-1630-4d7d-90b5-7f82057acf76": ("energy_policy_center", "Produces Rice Baker Institute energy research and convening on energy markets, transition pathways, geopolitics, and technology policy."),
    "a67225f1-e808-4374-82d5-5ae91fc9915c": ("catalysis", "Supports Rice chemical and biomolecular engineering research groups working on catalysis, processes, materials, and molecular systems."),
    "8018d81c-51f8-4f40-bdec-baa1a4993285": ("chemical_department", "Conducts Rice chemistry research and education across molecular science, materials, catalysis, synthesis, and chemical biology."),
    "7151a5f0-d363-4a8b-a270-8f4d98aef2e2": ("chemical_department", "Conducts Rice chemistry research and education across molecular science, materials, catalysis, synthesis, and chemical biology."),
    "70d44699-de94-4d85-9a68-adeb8137b10e": ("critical_minerals_company", "Operates Rio Tinto U.S. mining and mineral processing activities linked to copper, critical minerals, industrial materials, and resource systems."),
    "68787ab7-1da5-412d-aac3-88f60f9f7d2c": ("critical_minerals_company", "Operates Rio Tinto Kennecott copper mining, smelting, refining, resource management, and environmental operations in Utah."),
    "f35f9537-dc08-4bee-be30-8529a373c704": ("farming_systems_trial", "Runs UC Davis long-term farming systems trials comparing sustainable agriculture practices, soil health, crop performance, and water use."),
    "300d6c74-49af-4079-87a8-d641c23f4986": ("farming_systems_trial", "Provides UC Davis sustainable agriculture field infrastructure for long-term trials, soil health, nutrient cycling, and crop-system research."),
    "1599ed9e-9b56-4122-b3eb-af4aa51eb0ca": ("water_utility", "Operates San Antonio water, wastewater, reuse, conservation, and drought-management programs for municipal customers."),
    "de2f31e8-c2c8-4594-8bec-e53d1e733300": ("venture", "Invests in and supports venture-backed technology companies across AI, software, enterprise, consumer, healthcare, and frontier sectors."),
    "0123da7c-a098-44d2-b358-daba421d7b78": ("upstream_energy", "Operates energy, fuels, chemicals, trading, and lower-carbon technology activities across global energy systems."),
    "d8c11a3e-1133-409e-b1bf-a96fd398d1e7": ("petrochemicals", "Operates Shell Deer Park chemical manufacturing assets with petrochemical production, process operations, logistics, and safety systems."),
    "514476f0-b224-4a6c-bbc5-2a32c82c4c88": ("ai_lab", "Conducts UC Berkeley Sky Computing Lab research on cloud computing, distributed systems, AI infrastructure, and data-intensive platforms."),
    "e9e3cd06-0fa0-4352-a7d0-344e32bfe48f": ("software_engineering", "Conducts CMU SEI applied research and transition work in software engineering, cybersecurity, AI assurance, and mission-critical systems."),
    "d9a1af68-d7bc-45d2-b89d-819e045d1828": ("electric_utility", "Operates Southern California Edison electric utility services while supporting grid modernization, distributed energy, and resilience programs."),
    "bed39bbf-11f5-46cf-933a-6e8ab5aa9db8": ("space_company", "Develops and operates launch vehicles, spacecraft, satellites, propulsion systems, manufacturing, and mission operations."),
    "8df493b4-d9e3-4ed5-954d-86bd496cd7b8": ("venture", "Connects St. Louis bioscience startups with venture capital, commercialization support, and regional life-science investor networks."),
    "fd605987-b56b-4d6c-b2e1-f2a4e022fa04": ("ai_lab", "Conducts Stanford AI Lab research in machine learning, robotics, vision, language, reasoning, and AI systems."),
    "cf7544bf-73fb-419e-ae70-197acbaecf8d": ("chemical_department", "Conducts Stanford chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "6804ea7c-cf93-4063-9637-861a6c55a2e6": ("chemical_department", "Conducts Stanford chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "d4999d3b-4bd5-4bc7-a1e9-4f53410de0d5": ("climate_school", "Conducts Stanford sustainability research and education across climate, energy, water, food, ecosystems, and environmental justice."),
    "8dc384ba-4944-4a2c-a5f9-003c83c9d2a0": ("ai_lab", "Conducts Stanford HAI research, education, and policy engagement on human-centered, trustworthy, and socially beneficial AI."),
    "d1349c98-13ef-40dd-81ea-3ac8ad4a2c0c": ("materials_chemicals", "Conducts Stanford materials science research across materials discovery, characterization, energy materials, semiconductors, and nanotechnology."),
    "614514b1-c26b-4ced-a8e8-ccf8049d07b6": ("materials_chemicals", "Conducts Stanford materials science and engineering research across materials discovery, processing, characterization, and energy-relevant systems."),
    "1cec9180-ce76-40e1-9129-a9b9e8bbe0c6": ("medical_school", "Conducts Stanford Medicine clinical care, biomedical research, education, diagnostics, therapeutics, and digital health translation."),
    "6ec4e01e-5342-4daa-ac6b-34944d2d9a12": ("renewable_energy_research", "Conducts Stanford energy research and convening through the Precourt Institute across clean energy, markets, and technology pathways."),
    "fe30ec78-e6c1-4e7a-9fdb-e85e620f95a6": ("renewable_energy_research", "Conducts Stanford energy research and convening through the Precourt Institute across clean energy, markets, and technology pathways."),
    "576b65be-b073-406f-aac5-b86576d56083": ("medical_school", "Conducts Stanford School of Medicine research, education, clinical translation, and biomedical innovation across health domains."),
    "9666cc89-91dd-49c1-9431-398897490421": ("university_science", "Conducts Stanford research and education across AI, medicine, engineering, sustainability, materials, chemistry, and entrepreneurship."),
    "25ee9ed0-0672-441d-9530-6b085dd14efb": ("catalysis", "Conducts Stanford chemical engineering research and education across reaction engineering, catalysis, transport, materials, and biotechnology."),
    "ba354a1e-a26e-4bec-a461-6b3a530346e4": ("chemical_department", "Conducts Stanford chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "1e415a33-7bb3-4b17-a93f-1130fe16c6dc": ("watershed_center", "Conducts Stanford water research and policy engagement on western water management, climate resilience, allocation, and ecosystems."),
    "3f7243ab-898c-4cf8-b149-5cff29290a2c": ("climate_school", "Conducts Stanford environmental research and policy engagement through the Woods Institute across water, climate, ecosystems, and sustainability."),
    "ea32909f-9afb-452f-a9f6-70fce3dd9957": ("water_policy_board", "Implements California water quality and water rights programs through statewide and regional water regulatory functions."),
    "346d9ffa-b4a3-4116-9ba1-3fbae3e4bbbd": ("consumer_solar", "Deploys residential solar, battery storage, financing, customer operations, and distributed energy services."),
    "0f3204ac-bd23-4cb4-954f-83c8cf11c413": ("ag_science_company", "Develops and commercializes crop protection, seeds, biologicals, traits, and digital agriculture technologies for growers."),
    "222cd170-e13f-4b86-a27a-4168e633c9c8": ("automotive", "Develops and manufactures electric vehicles, batteries, energy storage, charging systems, software, and clean-energy products."),
    "6474391c-6c5e-4245-bd3a-e9d4bf4ef608": ("extension", "Delivers Texas A&M AgriLife extension programs translating agricultural, food, natural-resource, and community research into practice."),
    "7e634887-5df5-4ead-a3fd-a7c2b59323c5": ("extension", "Supports UC Agriculture and Natural Resources research and extension across farms, natural resources, food systems, and communities."),
    "2a5007c0-0f02-4ef1-b49b-bbe26e7c3f23": ("university_science", "Conducts UC Berkeley research and education across AI, chemistry, materials, energy, climate, life sciences, and public policy."),
    "c33c2f61-bfa3-496b-aba7-4f9f0a41fdfd": ("bioengineering", "Conducts UC Berkeley bioengineering research and education across biomedical devices, synthetic biology, computation, and translational health."),
    "9bf2dc3c-e417-40ab-a9c2-35c2401cfc8a": ("chemical_department", "Conducts UC Berkeley chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "321f944a-5566-41e6-9706-272afd9a1e96": ("chemical_department", "Conducts UC Berkeley chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "f9e3bae2-0f25-43f0-b749-cf7fe52b5b58": ("energy_policy_center", "Conducts UC Berkeley Energy and Resources Group research across energy systems, sustainability, resource economics, and policy."),
    "be79b670-9ce7-422d-94b3-e48a1bbc800b": ("energy_policy_center", "Conducts UC Berkeley ERG research across energy systems, sustainability, resource economics, and policy."),
    "eeca0dba-12fe-40ec-9577-88228ca72dba": ("materials_chemicals", "Conducts UC Berkeley materials science research across materials discovery, processing, characterization, energy materials, and devices."),
    "2e3cbdca-533e-4fe7-8f6f-4025b8418ebb": ("materials_chemicals", "Conducts UC Berkeley materials science and engineering research across materials discovery, processing, characterization, and devices."),
    "27052c49-0e74-4be4-9da0-5a7eedf309bc": ("watershed_center", "Supports UC Berkeley water research and education across hydrology, water quality, climate resilience, and water policy."),
    "a57da596-9644-497f-bfc9-316b57f38efc": ("watershed_center", "Conducts UC Davis watershed research and applied analysis for water management, ecosystems, climate adaptation, and policy decisions."),
    "6ba81874-b3bc-400d-9c3e-6f4c52c570c3": ("crop_science", "Conducts UC Davis plant sciences research and education across crops, plant physiology, breeding, agronomy, and sustainable production."),
    "6b122dad-edc0-4b4f-b589-b7bb75614cee": ("environmental_studies", "Conducts UCLA environment and sustainability research and education across climate, ecosystems, urban systems, and environmental policy."),
    "55af96de-1f54-46d5-a63e-c4ff38e140b3": ("robotics_institute", "Conducts UCLA robotics and intelligent systems research across autonomy, perception, control, mobility, and human-robot interaction."),
    "69682d45-7aad-40c2-a341-bbd6c1253e28": ("engineering_school", "Conducts UCLA Samueli engineering research and education across AI, robotics, materials, energy, infrastructure, and bioengineering."),
    "1ab90303-c5ab-48f3-a02f-d3ff0046dfb5": ("medical_school", "Conducts UCSF biomedical research, clinical education, patient-care translation, diagnostics, therapeutics, and health technology work."),
    "a2f91135-d31f-4923-843d-bd1801221420": ("medical_school", "Conducts UCSF School of Medicine education, biomedical research, clinical translation, and healthcare innovation."),
    "1e6f28cf-21ed-4ad2-8acd-831664b2165f": ("catalysis", "Conducts UIUC catalysis research across reactions, materials, energy, chemicals, and sustainable process systems."),
    "6afa85a9-cd19-4c72-baac-be636667c749": ("un_policy_body", "Leads UN coordination and country support on gender equality, womens empowerment, policy norms, and implementation programs."),
    "1faa4ae9-cbd4-4c79-9e52-d35a2e7f47ab": ("university_science", "Conducts UNC Chapel Hill research and education across health, chemistry, data, public policy, life sciences, and applied sciences."),
    "a67b187b-ccb0-489e-8bee-5a7657c68ea8": ("chemical_department", "Conducts UNC chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "1f8aa204-3711-4e61-9697-9d190edf37dd": ("un_policy_body", "Deliberates on UN economic, financial, development, climate, and sustainability issues through General Assembly policy processes."),
    "937a55fc-b3b0-4676-ab59-ea6bf505f6ac": ("un_industrial_development", "Supports inclusive and sustainable industrial development through technical cooperation, policy support, standards, and capacity-building."),
    "c167d971-2b77-4d48-a4d6-5a286ec89d57": ("un_science_education", "Connects higher education institutions with UN goals through academic networks, outreach, and sustainable development engagement."),
    "13b0587b-747c-4074-857b-f321360d436c": ("un_children_development", "Supports child health, nutrition, education, water, protection, and humanitarian programs through country-level implementation."),
    "bbd3cd69-cee9-413b-9cc4-142b140500d7": ("development_finance", "Supports development projects, policy advice, capacity-building, climate action, governance, and SDG implementation across countries."),
    "d235353a-6020-49da-897a-3f4db90c0086": ("un_science_education", "Supports international cooperation in education, science, culture, communication, information, and knowledge systems."),
    "476e2152-4ba4-4e60-826f-6dc8304fdee0": ("un_environment", "Sets global environmental agenda, supports climate and biodiversity policy, monitors conditions, and helps countries implement environmental action."),
    "d3ada823-87c5-41fb-82c6-8ad962cd5f19": ("un_policy_body", "Delivers UN training, learning, research, and capacity-development programs for sustainable development, peace, and governance priorities."),
    "6c719b6b-e199-44d1-a592-753dd14510d4": ("un_policy_body", "Conducts independent UN research on the social dimensions of development, policy change, inequality, and sustainability."),
    "305ae59b-5a7f-43b6-bc45-8af0f13f7f74": ("un_policy_body", "Advances youth priorities across the UN system through policy coordination, participation mechanisms, advocacy, and implementation support."),
    "b3fedc90-c71d-4daf-a5ee-3249e111fd58": ("mining_department", "Conducts University of Arizona mining and geological engineering research and education in mineral extraction, geoscience, and resource systems."),
    "cf6b950d-07bf-45f7-a9f8-366f10d346c1": ("watershed_center", "Conducts University of Arizona water resources research and engagement across hydrology, policy, conservation, and arid-region water systems."),
    "7682e2c5-8230-4a4d-91dc-0b543cc2008d": ("catalysis", "Conducts UC Berkeley chemical and biomolecular engineering research across catalysis, biotechnology, transport, materials, and process systems."),
    "e9eda74b-9bd5-4b1e-a022-accce9b519df": ("chemical_department", "Conducts UC Berkeley chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "0505b9e5-6c7d-4824-bc0c-bd46a4aaa736": ("catalysis", "Conducts UC Davis chemical engineering research and education across catalysis, reaction engineering, materials, and process systems."),
    "d53bbcad-6ec3-4d5e-9c13-b8442d84c9b8": ("chemical_department", "Conducts UC Davis chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "965af128-4ecd-4716-a253-61e345f57cf1": ("ag_college", "Conducts UC Davis research and education across agriculture, life sciences, food systems, water, climate, veterinary medicine, and engineering."),
    "41f93e5d-dc3d-4dac-b998-da21cc6941e0": ("engineering_school", "Conducts UCLA research and education across AI, engineering, medicine, sustainability, materials, public policy, and applied sciences."),
    "32203b82-8dc7-45f9-b460-abf14f5f024c": ("health_system", "Provides academic medical care and conducts clinical research, biomedical translation, diagnostics, therapeutics, and health innovation."),
    "a351b388-f122-4e3e-8dfa-a1706c39d70a": ("university_science", "Conducts CU Boulder research and education across climate, space, engineering, materials, computing, environmental science, and policy."),
    "497ce45d-5a3b-4889-bc7b-9a830053a69e": ("catalysis", "Conducts University of Delaware chemical and biomolecular engineering research across catalysis, reaction engineering, materials, and biotechnology."),
    "f23b73bd-84ee-4a46-8c76-814aa5947fff": ("catalysis", "Conducts University of Delaware chemical engineering research across catalysis, reaction engineering, materials, and process systems."),
    "a0cbf67d-8dd9-40ae-8cc7-93c1d2ea651e": ("chemical_department", "Conducts University of Delaware chemistry research and education across molecular science, catalysis, materials, and chemical biology."),
    "7bbe145a-8e71-49f1-8a3f-73163fc7c50d": ("catalysis", "Conducts University of Houston chemical and biomolecular engineering research across catalysis, process systems, materials, and energy."),
    "7cf64e7c-cb3f-40ef-ac6c-dc4dae7909f9": ("catalysis", "Supports University of Houston chemical and biomolecular engineering research labs in catalysis, processes, materials, and energy systems."),
    "eaa90016-1cf7-4c5d-9ed6-db422fbe0356": ("chemical_department", "Conducts University of Houston chemistry research and education across molecular science, catalysis, materials, and chemical biology."),
    "abc71126-8512-4859-91d8-b0d310a5cf0f": ("university_science", "Conducts UIUC research and education across agriculture, engineering, chemistry, materials, computing, health, and sustainability."),
    "a6e85807-3ae9-4884-af66-2f8b6e0d3545": ("catalysis", "Conducts UIUC chemical and biomolecular engineering research across catalysis, materials, reaction engineering, and bioprocessing."),
    "4cae1632-d40b-4410-ad4d-073004dd98e1": ("chemical_department", "Conducts UIUC chemistry research and education across molecular science, catalysis, materials, synthesis, and chemical biology."),
    "45a76517-b142-4ce8-b4df-08b67c817e28": ("medical_school", "Conducts University of Maryland medical education, biomedical research, clinical translation, and health-science programs."),
    "10332624-6fbb-4b5a-971c-f4edc6eb7765": ("chemical_department", "Conducts University of Michigan chemistry research and education across molecular science, catalysis, materials, and chemical biology."),
    "53c1e16e-7066-4a63-b32a-ced3eb66ca1f": ("renewable_energy_research", "Supports University of Michigan energy research across batteries, grid systems, fuels, materials, buildings, and sustainability."),
    "62eff4b2-b044-4282-a22a-50d54dc263d7": ("health_system", "Provides clinical care and conducts biomedical research and translational health innovation through University of Michigan Health."),
    "39b7dfb8-854b-446e-9a81-a488187b78d8": ("watershed_center", "Conducts University of Michigan water research across Great Lakes systems, water quality, policy, hydrology, and resilience."),
    "7513f7c7-8ddb-4ecf-8dbb-792db0adbc69": ("catalysis", "Conducts University of Minnesota chemical engineering and materials science research across catalysis, materials, polymers, and processes."),
    "27f822ab-1781-4537-9920-7144ffb5805a": ("chemical_department", "Conducts University of Minnesota chemistry research and education across molecular science, catalysis, materials, and chemical biology."),
    "5646eb07-f3ba-4b15-8969-703628a30f0e": ("ag_college", "Conducts University of Missouri research and education across agriculture, plant science, life sciences, engineering, and sustainability."),
    "8ead653e-603a-4c45-abff-8479e57c3a1b": ("crop_science", "Conducts University of Missouri plant sciences research and education across crops, plant biology, breeding, agronomy, and field systems."),
    "8937fa71-ae8f-4818-8bc2-f3a32feb2d2f": ("materials_chemicals", "Conducts University of Pennsylvania materials science and electrochemical systems research across energy materials, devices, and interfaces."),
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
    for name in applied[:140]:
        print(f"APPLIED|{name}")
    for name, reason in skipped[:20]:
        print(f"SKIP|{name}|{reason}")


if __name__ == "__main__":
    main()
