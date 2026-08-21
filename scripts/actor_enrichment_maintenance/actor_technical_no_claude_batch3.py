"""Third no-Claude actor technical refinement pass."""

from __future__ import annotations

import argparse
import sys
from copy import deepcopy
from pathlib import Path
from uuid import UUID

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from actor_technical_no_claude_batch2 import TEMPLATES, rec  # noqa: E402
from sqlalchemy import func, select, text  # noqa: E402
from src.db.models import Actor  # noqa: E402
from src.db.session import SessionLocal  # noqa: E402


TEMPLATES.update(
    {
        "health_system": rec(
            "Clinical care, biomedical research, digital health, diagnostics, therapeutics, care delivery, and translational medicine.",
            "Combines hospital operations, clinical trials, patient data, specialty care, research programs, and commercialization partnerships.",
            "Clinical IP may include patents, software, devices, diagnostics, therapeutics, datasets, and licenses under strict patient-data governance.",
            "Constraints include patient safety, reimbursement, privacy, regulatory review, clinical workflow fit, trial recruitment, and adoption risk.",
            "validation",
        ),
        "clean_energy_agency": rec(
            "Clean energy deployment, climate programs, building decarbonization, renewable energy, grid modernization, and clean-tech market growth.",
            "Uses grants, financing, technical assistance, market development, policy support, and public-private partnerships to move technologies into use.",
            "Primary assets are programs, funding mechanisms, data, standards, and partnerships; technology IP usually stays with grantees or vendors.",
            "Progress depends on public funding, permitting, grid capacity, consumer adoption, workforce capacity, equity goals, and policy stability.",
            "scaling",
        ),
        "medical_device": rec(
            "Medical devices, implants, surgical tools, diagnostics-adjacent systems, sensors, digital health, and regulated healthcare technology.",
            "Uses product engineering, clinical evidence, quality systems, regulatory submissions, manufacturing, and physician/customer feedback.",
            "Likely IP includes patents, device designs, software, clinical data, manufacturing know-how, regulatory files, and trade secrets.",
            "Constraints include clinical validation, FDA and global regulation, reimbursement, safety, manufacturing quality, and hospital adoption.",
            "deployment",
        ),
        "software_ai_cloud": rec(
            "Cloud computing, enterprise software, AI platforms, productivity tools, developer infrastructure, cybersecurity, and data systems.",
            "Combines large-scale software engineering, cloud infrastructure, AI research, product integration, partner ecosystems, and enterprise deployment.",
            "Likely IP includes software, models, cloud infrastructure, patents, datasets, security methods, and trade secrets.",
            "Constraints include cybersecurity, reliability, regulatory pressure, compute cost, enterprise trust, interoperability, and talent competition.",
            "deployment",
        ),
        "hydrogen_hub": rec(
            "Clean hydrogen production, transport, storage, industrial use, heavy transport, power systems, and regional energy infrastructure.",
            "Coordinates project developers, utilities, industrial users, public funding, engineering, permitting, offtake, and infrastructure planning.",
            "IP generally sits with member companies and technology suppliers; the hub contributes project coordination, data, agreements, and implementation pathways.",
            "Constraints include offtake, hydrogen cost, permitting, infrastructure buildout, safety, public funding milestones, and emissions accounting.",
            "deployment",
        ),
        "metallurgy_department": rec(
            "Metallurgical engineering, mineral processing, extractive metallurgy, materials performance, recycling, and critical minerals.",
            "Combines laboratory experiments, process modeling, pilot work, field data, industry partnerships, and engineering education.",
            "Outputs include publications, process methods, datasets, prototypes, patents, and workforce training.",
            "Constraints include scale-up, ore variability, safety, environmental rules, capital intensity, field validation, and industry adoption.",
            "discovery",
        ),
        "ai_media_lab": rec(
            "Human-centered technology, AI, media systems, design, interaction, sensing, creativity tools, and interdisciplinary prototypes.",
            "Combines exploratory research, prototypes, design studios, computing, sensors, user studies, and industry-sponsored projects.",
            "Outputs include prototypes, software, publications, design methods, patents, datasets, and startup ideas.",
            "Constraints include reproducibility, productization, sponsor fit, ethical review, data governance, hardware reliability, and long-term maintenance.",
            "discovery",
        ),
        "cancer_center": rec(
            "Cancer research, oncology care, clinical trials, precision medicine, diagnostics, immunotherapy, and translational therapeutics.",
            "Combines clinical oncology, laboratory research, patient data, trials, genomics, biobanks, and partnerships for cancer translation.",
            "IP may include therapeutics, diagnostics, biomarkers, software, trial data, patents, and licensed inventions under clinical governance.",
            "Constraints include trial recruitment, safety, tumor heterogeneity, regulatory review, reimbursement, privacy, and manufacturing or partner readiness.",
            "validation",
        ),
        "space_lab": rec(
            "Robotic space missions, Earth science, spacecraft systems, autonomy, remote sensing, instruments, and mission operations.",
            "Uses systems engineering, spacecraft design, sensors, autonomy software, simulation, mission operations, and federal research programs.",
            "Outputs include mission data, instruments, software, prototypes, patents, and mission-specific engineering know-how.",
            "Constraints include mission risk, launch schedules, reliability, federal funding, radiation and space environment limits, and long development cycles.",
            "validation",
        ),
        "hpc_center": rec(
            "High-performance computing, scientific computing, AI/modeling infrastructure, data-intensive research, and advanced simulation.",
            "Provides supercomputing systems, user support, software, data services, workflows, and research partnerships for computational science.",
            "Outputs include software, datasets, workflows, publications, benchmarks, operational know-how, and sometimes university or lab-managed IP.",
            "Constraints include compute capacity, power and cooling, cybersecurity, user support, funding, procurement cycles, and data governance.",
            "validation",
        ),
        "standards_lab": rec(
            "Measurement science, standards, reference materials, biosystems, cybersecurity, manufacturing, and technology validation.",
            "Uses metrology, reference methods, test protocols, datasets, interlaboratory studies, and stakeholder standards development.",
            "Core assets are standards, reference data, methods, testbeds, publications, and calibration or validation capabilities rather than commercial products.",
            "Constraints include measurement uncertainty, consensus building, data quality, technology pace, funding, and adoption by regulators or industry.",
            "validation",
        ),
        "robotics_engineering_center": rec(
            "Applied robotics, autonomous systems, field robotics, manipulation, perception, mobility, and defense or industrial robot deployment.",
            "Uses systems engineering, prototypes, field testing, perception, controls, software, hardware integration, and sponsor-driven projects.",
            "Outputs include prototypes, software, datasets, patents, test results, and applied robotics know-how.",
            "Constraints include safety, field reliability, hardware cost, sponsor requirements, integration complexity, and transition to deployable products.",
            "validation",
        ),
        "mining_association": rec(
            "Mining industry policy, critical minerals, permitting, workforce, environmental stewardship, and regional mining-sector coordination.",
            "Uses advocacy, member coordination, education, data, public engagement, and policy analysis to support mining-sector development.",
            "IP emphasis is low; core assets are member networks, policy positions, datasets, guidance, and convening authority.",
            "Impact depends on member alignment, commodity cycles, public trust, permitting policy, environmental performance, and workforce availability.",
            "scaling",
        ),
        "grower_association": rec(
            "Specialty crop marketing, grower coordination, quality standards, crop promotion, supply-chain support, and agricultural policy.",
            "Uses member programs, market development, education, data, advocacy, and partnerships with growers, researchers, and buyers.",
            "IP emphasis is low; assets include brands, market data, grower networks, promotion materials, and production guidance.",
            "Impact depends on grower participation, crop quality, weather, disease pressure, consumer demand, labor, and supply-chain reliability.",
            "scaling",
        ),
        "city_climate_office": rec(
            "City climate policy, emissions reduction, resilience, environmental justice, building decarbonization, and urban sustainability programs.",
            "Uses policy design, implementation plans, public programs, data, agency coordination, community engagement, and reporting frameworks.",
            "Core assets are plans, datasets, policy tools, public programs, procurement channels, and implementation partnerships rather than proprietary IP.",
            "Constraints include budget, legal authority, agency coordination, equity goals, building-stock complexity, public adoption, and climate risk.",
            "validation",
        ),
        "city_ai_economic": rec(
            "Urban AI strategy, digital economy development, startup support, workforce, governance, and responsible public-sector technology adoption.",
            "Uses economic-development programs, reports, public-private partnerships, workforce initiatives, policy coordination, and ecosystem convening.",
            "Core assets are strategies, datasets, public programs, procurement pathways, partner networks, and convening authority rather than technology IP.",
            "Impact depends on city procurement, talent pipelines, startup density, data governance, regulation, funding, and public trust.",
            "scaling",
        ),
        "ai_model_company": rec(
            "AI models, foundation models, generative AI, safety, product AI, developer platforms, and applied machine learning systems.",
            "Combines large-scale model training, evaluation, safety research, product engineering, developer tooling, infrastructure, and deployment partnerships.",
            "Likely IP includes models, training methods, software, evaluations, safety methods, datasets, infrastructure, patents, and trade secrets.",
            "Constraints include compute cost, safety, data governance, reliability, regulation, misuse risk, competition, and enterprise adoption.",
            "deployment",
        ),
        "forestry_college": rec(
            "Forestry, wood products, forest ecology, wildfire, carbon, natural resources, and sustainable land management.",
            "Combines field research, laboratories, extension, education, modeling, industry partnerships, and public-agency collaboration.",
            "Outputs include publications, datasets, models, wood-product methods, decision tools, patents, and extension guidance.",
            "Impact depends on field access, forest disturbance, climate variability, landowner adoption, funding, and policy or market uptake.",
            "discovery",
        ),
        "ag_biotech_startup": rec(
            "Agricultural biotechnology, biological nitrogen, microbial products, crop inputs, soil biology, and sustainable fertilizer alternatives.",
            "Uses strain development, field trials, agronomy, formulation, regulatory work, manufacturing, and grower commercialization.",
            "Likely IP includes microbial strains, formulations, field datasets, patents, production processes, trademarks, and trade secrets.",
            "Constraints include field performance variability, farmer ROI, regulatory review, manufacturing scale-up, distribution, and seasonal adoption cycles.",
            "demonstration",
        ),
        "applied_research_campus": rec(
            "Applied research infrastructure, engineering testbeds, workforce training, agriculture, mobility, defense-adjacent systems, and technology demonstration.",
            "Provides campus infrastructure, labs, field sites, education programs, partner access, and applied testing for university and industry projects.",
            "IP generally remains with university researchers, companies, or agencies; the campus contributes facilities, data, and implementation support.",
            "Impact depends on partner demand, funding, facility utilization, workforce pipelines, data governance, and transition from testbed to operations.",
            "validation",
        ),
        "apparel_materials": rec(
            "Performance apparel, footwear materials, biomechanics, manufacturing, product design, sustainability, and consumer product innovation.",
            "Uses materials R&D, athlete testing, design, supply-chain engineering, manufacturing partners, data, and brand-driven commercialization.",
            "Likely IP includes patents, materials, designs, trademarks, manufacturing know-how, performance data, and trade secrets.",
            "Constraints include consumer demand, supply-chain execution, sustainability targets, manufacturing cost, product safety, and brand risk.",
            "deployment",
        ),
        "defense_aerospace": rec(
            "Defense aerospace, autonomous systems, sensors, space systems, AI-enabled mission systems, cybersecurity, and advanced manufacturing.",
            "Uses systems engineering, classified and unclassified R&D, prototyping, testing, program execution, and government customer integration.",
            "Likely IP includes patents, software, systems designs, manufacturing know-how, mission data, and protected technical information.",
            "Constraints include procurement cycles, security requirements, export controls, reliability, certification, cost, and mission-specific validation.",
            "deployment",
        ),
        "enzyme_biotech": rec(
            "Industrial enzymes, microbial technologies, fermentation, bio-based ingredients, agricultural biologicals, and bioprocessing.",
            "Uses strain development, enzyme screening, fermentation, formulation, application testing, manufacturing, and customer qualification.",
            "Likely IP includes strains, enzymes, pathways, formulations, process know-how, patents, datasets, and trade secrets.",
            "Constraints include yield, cost, stability, regulatory acceptance, customer qualification, feedstock variability, and manufacturing scale.",
            "deployment",
        ),
        "ai_hardware": rec(
            "GPU computing, AI accelerators, model software, data-center systems, simulation, robotics platforms, and developer tooling.",
            "Combines chip design, systems software, AI research, hardware platforms, cloud partnerships, and developer ecosystems.",
            "Likely IP includes chips, architectures, software stacks, models, patents, drivers, libraries, and trade secrets.",
            "Constraints include semiconductor supply chains, power demand, compute cost, export controls, software compatibility, and customer capacity planning.",
            "deployment",
        ),
    }
)


ACTORS: dict[str, tuple[str, str]] = {
    "c7d38571-dbf7-46e2-bf18-32c8034bbc14": ("health_system", "Provides integrated hospital care, biomedical research, digital health work, and clinical innovation across the Mass General Brigham system."),
    "44be9ef6-2a98-46c4-9865-452ac1dce59a": ("health_system", "Coordinates Mass General Brigham research programs spanning clinical trials, biomedical discovery, data science, and translational medicine."),
    "d1b6b9a3-01a1-4d73-9544-3080473de91f": ("clean_energy_agency", "Supports Massachusetts clean-energy market development through funding, programs, workforce support, and commercialization assistance."),
    "a3e09832-22a5-4fa7-80b7-7c93b7eae4f5": ("health_system", "Provides advanced hospital care and conducts academic medical research through Massachusetts General Hospital programs."),
    "dfc40676-ed68-4b99-a85d-f6811d19ccc5": ("university_science", "Conducts MIT research and education across AI, engineering, computing, chemistry, energy, climate, health, and entrepreneurship."),
    "884415a0-5250-4656-a3ab-6abcb1be662c": ("clean_energy_agency", "Leads Massachusetts energy and environmental policy programs across climate, conservation, clean energy, and environmental protection."),
    "793fdc9d-0f12-4e7b-94e9-e153191b6683": ("health_system", "Provides clinical care and conducts translational biomedical research, diagnostics, therapeutics, and digital health work through Mayo Clinic."),
    "0ced16f2-663e-47c4-9ba3-628e46c7144a": ("health_system", "Conducts Mayo Clinic research across clinical trials, translational medicine, diagnostics, therapeutics, and patient-care innovation."),
    "26e9f684-bd7b-46b5-a41b-ae8119f2dd2d": ("medical_school", "Conducts UTHealth Houston medical education and biomedical research linked to clinical care and Texas Medical Center translation."),
    "365333cb-1073-4380-a4dc-84ef124854d7": ("cancer_center", "Conducts cancer care, oncology research, clinical trials, diagnostics, and translational therapeutics at MD Anderson Cancer Center."),
    "fcc60b65-064e-4f5e-9296-6635640f4446": ("medical_device", "Develops and commercializes medical devices, implants, surgical tools, digital health systems, and regulated healthcare technologies."),
    "4e8af629-2370-4411-8bb3-fe6eab090beb": ("corporate_ai_lab", "Conducts Meta AI research and develops AI technologies for models, ranking, language, vision, safety, and product integration."),
    "17624748-10f5-440a-83a5-ae2253b92558": ("cancer_center", "Conducts Weill Cornell cancer research and translation focused on oncology, clinical trials, biomarkers, and precision medicine."),
    "2af2a40a-77e5-414a-bc42-ef229f3bf6dd": ("renewable_energy_research", "Supports University of Michigan energy research across batteries, grid systems, fuels, materials, buildings, and sustainability."),
    "1fbc17a2-ba9c-4521-906d-4b8f37d14d19": ("materials_chemicals", "Supports University of Michigan materials-focused energy research relevant to batteries, materials discovery, and clean-energy systems."),
    "2020e38b-b435-4da8-833f-e81c43dd5665": ("university_science", "Conducts Michigan State research and education across agriculture, life sciences, materials, energy, health, and sustainability."),
    "f7ff01c0-335c-43c8-b873-be2789c303b7": ("health_system", "Supports University of Michigan translational health research by connecting clinical studies, data, investigators, and implementation partners."),
    "ed0e2ecf-5824-4ccf-b99a-dfbaa705f028": ("software_ai_cloud", "Develops cloud, enterprise software, AI, developer tools, cybersecurity, and productivity platforms at global commercial scale."),
    "d12a1b10-8dfb-4443-8ebd-01467fb8113d": ("software_ai_cloud", "Develops Microsoft AI engineering and Azure AI infrastructure for cloud services, enterprise deployment, and developer platforms."),
    "77b4480a-1afd-4237-9106-02b332868ada": ("hydrogen_hub", "Coordinates Midwest clean hydrogen hub development across production, infrastructure, offtake, public funding, and regional partners."),
    "bebfb2b6-02a8-4b53-a61f-7812c0a3c7d1": ("hydrogen_hub", "Coordinates Midwest hydrogen hub activity linking clean production, distribution, end users, and energy-transition infrastructure."),
    "944c0cdd-74b5-4a12-ae6f-aa1e713a1154": ("earth_sciences_school", "Conducts Colorado School of Mines earth and environmental systems research linked to water, mining, geology, and sustainability."),
    "567ffffa-92c1-4a78-892a-fad1b2c1a9c3": ("mining_department", "Conducts Mines mining engineering research and education focused on extraction, safety, critical minerals, and mine systems."),
    "874abeab-56bc-47a4-a45e-49392279b132": ("environment_regulator", "Manages Missouri natural resource and environmental programs including water, land, mining, energy, and environmental protection."),
    "6022d40e-cb01-473d-82ca-6785f7306123": ("metallurgy_department", "Conducts Missouri S&T metallurgical engineering research and education in metals, mineral processing, materials, and extractive systems."),
    "fb9060e9-adba-4ef0-bda0-c1d634ee2e29": ("mining_department", "Conducts Missouri S&T mining engineering research and education tied to mine systems, safety, mineral extraction, and critical minerals."),
    "c3e99524-981d-4472-b766-ce9629f39750": ("earth_sciences_school", "Conducts Missouri S&T research and education across engineering, mining, materials, energy, computing, and applied sciences."),
    "c1e3880d-8db5-437d-88f6-10eeab4b6cb5": ("catalysis", "Conducts MIT chemical engineering research and education across catalysis, reaction engineering, biotechnology, materials, and process systems."),
    "f56f2de4-8944-4e1d-8df9-5691eb7ff1b6": ("climate_venture", "Coordinates MIT-industry collaboration on climate and sustainability technologies, pathways, and implementation priorities."),
    "a85d8dfe-0db3-4cff-9654-38168c8c19c7": ("ai_lab", "Conducts MIT CSAIL research across AI, computer science, machine learning, robotics, systems, and human-computer interaction."),
    "8df2c7f0-9277-466a-912c-a4313825e3aa": ("chemical_department", "Conducts MIT chemistry research and education across molecular science, synthesis, catalysis, materials, and chemical biology."),
    "abc927da-6ee9-4038-b95e-d2acbaf2fa41": ("renewable_energy_research", "Coordinates MIT energy research, education, industry engagement, and technology analysis across power, fuels, storage, and climate systems."),
    "d91974aa-a839-42f6-b19c-0b6515b48e40": ("renewable_energy_research", "Supports MIT energy research at the materials interface, including storage, conversion, catalysis, and low-carbon industrial pathways."),
    "b6e73476-5936-4efd-ae90-af21dcc5fbcf": ("cancer_center", "Conducts MIT integrative cancer research linking biology, engineering, materials, imaging, immunology, and translational oncology."),
    "343bff45-7e71-4b9b-9be1-621a14dfa2fd": ("ai_media_lab", "Conducts interdisciplinary MIT Media Lab research in human-centered computing, AI, design, sensing, media, and creative technologies."),
    "92472244-b69c-4b6b-bb06-9d7b61d8d960": ("ai_media_lab", "Conducts MIT Media Lab research applying AI across design, media, interaction, sensing, learning, and creative technology domains."),
    "3e0522c2-22ec-4176-bcba-cd1afaf5c9ed": ("computer_science_school", "Coordinates MIT computing education and research across AI, computer science, data systems, ethics, and interdisciplinary computing."),
    "8b16ecee-bf58-4980-a8c5-a9c148fb9122": ("biopharma", "Develops mRNA medicines and vaccines through platform biology, clinical development, manufacturing, and regulatory pathways."),
    "b7c483a7-5541-4ad1-bda7-593d3ca94bab": ("national_lab", "Provides LBNL nanoscience user-facility capabilities for materials synthesis, characterization, theory, and nanoscale device research."),
    "fb1eb911-da9d-4841-a992-af3b4ccbb7c5": ("critical_minerals_company", "Operates the Morenci copper mine with large-scale extraction, processing, resource management, and environmental operations."),
    "765848f0-7801-4ecb-b09b-5ac5d5bf35fa": ("health_system", "Provides clinical care and conducts biomedical research through Mount Sinai Health System hospitals and affiliated academic programs."),
    "bdb48273-a310-4d65-9e3c-5d4b31cfcd8c": ("space_lab", "Applies JPL AI and autonomy capabilities to robotic space missions, Earth science, mission planning, and remote-sensing systems."),
    "e82fe889-6aab-4784-92f9-b84d0013fb91": ("space_lab", "Develops and operates robotic space and Earth-science missions through JPL systems engineering, instruments, and mission operations."),
    "6adebab5-0671-4fb0-b1a7-0d6a0082dab5": ("climate_research", "Conducts atmospheric and Earth-system science research through NCAR models, observations, data, and community research infrastructure."),
    "f1075ee6-d4bd-49ab-9207-edd2e6d27d9b": ("hpc_center", "Provides UIUC supercomputing, data, AI, and modeling infrastructure for research and industry-facing computational science projects."),
    "f7894a87-17a2-4387-86f5-b69ab884c072": ("hpc_center", "Provides DOE high-performance computing resources, data systems, software support, and scientific computing services through NERSC."),
    "40bd7f04-9b85-48b1-90ef-5d34ae798965": ("standards_lab", "Develops NIST measurement science and standards for biosystems, technology validation, manufacturing, cybersecurity, and regulated innovation."),
    "83cbf8bc-2e2f-4a17-bbec-45b7c897d9af": ("renewable_energy_research", "Conducts national renewable energy and energy-efficiency research across solar, wind, grid, storage, buildings, hydrogen, and mobility."),
    "a74b1cf9-472f-4ccb-86cc-60108abd4bbe": ("renewable_energy_research", "Conducts NREL research linking clean energy systems with materials, minerals, supply chains, and technology deployment questions."),
    "5e854aa4-250e-45fd-8e85-21a6adf8987c": ("robotics_engineering_center", "Develops and validates applied robotics systems for field, industrial, defense, autonomy, perception, and manipulation use cases."),
    "bc9dcdec-0406-4dae-ac58-b5c7cd1d4e51": ("chemical_department", "Conducts NC State chemistry research and education across molecular science, catalysis, materials, and chemical biology."),
    "412bcb92-26ad-4381-a1ca-f39ce9b06886": ("ag_college", "Conducts NC State agriculture and life-science research, education, and extension across crops, food, animals, and environmental systems."),
    "1baf3bcb-534b-4466-bc14-db6efb26a5c1": ("climate_research", "Conducts atmospheric and Earth-system science research through NCAR models, observations, data, and community infrastructure."),
    "8402b82f-9fcb-4453-b5d2-bf5c9a65e8ae": ("hpc_center", "Provides NCSA AI, modeling, data, and supercomputing capabilities for scientific and applied research projects."),
    "e69f67cf-6342-4d4f-a4ee-ed93f5c0a8a9": ("geoscience", "Conducts Nevada geologic mapping, mineral-resource assessment, geologic hazards, and applied earth-science research and data services."),
    "15db3a38-203b-40c8-97e2-1feaf59ec952": ("mining_association", "Represents Nevada mining interests and supports policy, workforce, public education, and responsible mining-sector coordination."),
    "b22c26d1-8acd-489a-838d-a5f9f5a3b615": ("grower_association", "Supports New York apple growers through promotion, market development, consumer education, and industry coordination."),
    "e5054f89-575a-4dce-99f0-8ce0840c76ba": ("ag_agency", "Supports New York climate-resilient farming and climate-smart agriculture through conservation programs and farm-facing implementation."),
    "917b79b4-3cf7-4629-bb8c-2941fd939026": ("ag_agency", "Runs New York agriculture and markets programs covering food, farms, plant health, markets, and agricultural policy."),
    "b12ebc9a-badf-4c43-b860-83c3801c7eb0": ("grower_association", "Supports New York wine and grape growers through promotion, market development, education, and industry coordination."),
    "d252a32e-1c5e-44fc-bc23-a5d928de0827": ("critical_minerals_company", "Operates gold and copper mining assets with mineral processing, resource development, environmental management, and operational execution."),
    "a8585b24-67c8-4b81-8864-b1be68703ed5": ("health_system", "Provides New York hospital care and supports academic medical research and clinical translation with affiliated universities."),
    "3d4a5306-13a6-49dc-959f-489db5e99242": ("clinical_research_hospital", "Conducts NIH intramural biomedical research through federal laboratories, clinical protocols, investigators, and translational programs."),
    "b7c3ad44-c8f1-4a93-91cb-f75da1921611": ("apparel_materials", "Develops and commercializes performance footwear, apparel, materials, design systems, and consumer product technologies."),
    "74f36fbe-6647-4b45-95d2-7e415ec3e9b2": ("climate_research", "Conducts NOAA Earth-system research involving weather, climate, atmospheric chemistry, carbon cycle, and environmental observations."),
    "f16311a2-57d7-4670-b841-6b5f0e4e437b": ("water_program", "Conducts NOAA Great Lakes environmental research on water quality, ecosystems, hydrology, forecasting, and regional climate impacts."),
    "87b7ec28-8612-4c6f-a5ed-6e3a8fe857ef": ("climate_research", "Conducts NOAA physical sciences research on weather, climate variability, hydrology, atmospheric processes, and Earth-system prediction."),
    "0771b5e1-a839-4035-b7d7-0f425eedf758": ("defense_aerospace", "Develops aerospace, defense, space, autonomous, cyber, and AI-enabled mission systems for government and security customers."),
    "2bf6a175-c720-47fb-b3b4-18f895e86ae3": ("catalysis", "Conducts Northwestern catalysis and surface-science research relevant to materials, reactions, energy, and sustainable chemistry."),
    "74a0ea6e-0067-4df6-a722-4fd802d3e754": ("renewable_energy_research", "Supports Northwestern sustainability and energy research across climate, materials, energy systems, and industrial transition."),
    "61fd209f-49a7-40ae-838e-e7803a9d165c": ("materials_chemicals", "Supports Northwestern materials research through characterization, synthesis, device, and interdisciplinary materials-science programs."),
    "0c17f76c-47a0-4ca7-a7c8-ef5942f98520": ("health_system", "Provides clinical care and conducts healthcare research and translation through Northwestern Medicine programs."),
    "9ae11791-dc3e-4d8b-a0a7-6bc1db08e071": ("chemical_department", "Conducts Northwestern chemistry research and education across catalysis, materials, synthesis, chemical biology, and molecular science."),
    "9d0e85ca-4273-4216-9fa3-d3e78babbf76": ("catalysis", "Conducts Northwestern chemical and biological engineering research across catalysis, reaction engineering, biotechnology, and materials."),
    "18156051-007e-42a6-8390-ca2ab918c158": ("chemical_department", "Conducts Northwestern chemistry research and education across catalysis, materials, synthesis, chemical biology, and molecular science."),
    "09188ef4-8641-4b0d-ace8-6378a4ee4729": ("environmental_studies", "Conducts Northwestern environmental engineering research and education in water, sustainability, treatment systems, and environmental resilience."),
    "9e644c46-ae06-4d47-b4a9-bf0115714f0d": ("enzyme_biotech", "Develops industrial enzymes and microbial technologies for bio-based products, agriculture, food, materials, and industrial processing."),
    "bfc97a22-39db-4257-bd67-dcab250b5684": ("renewable_energy_research", "Conducts national renewable energy and energy-efficiency research across solar, wind, grid, storage, buildings, hydrogen, and mobility."),
    "3b4ad039-7af7-4e3d-833e-4d318b6b5183": ("ai_hardware", "Develops GPU computing, AI accelerators, software platforms, data-center systems, simulation tools, and developer ecosystems."),
    "12e9fbac-c66c-44cb-9d67-299167297432": ("ai_hardware", "Conducts NVIDIA AI research and platform development around accelerated computing, models, simulation, robotics, and AI software."),
    "7fd4787f-405c-4f19-af6c-2b3751899a0a": ("city_ai_economic", "Supports NYC AI economic-development strategy, startup activity, workforce planning, and public-private ecosystem coordination."),
    "b7c08807-e170-496c-9f52-3eb79e7f4f44": ("health_system", "Operates New York City's public health system while supporting care delivery, population health, data, and clinical service innovation."),
    "42fc6473-6b45-441c-a143-10ccc7140d8b": ("city_climate_office", "Develops and implements New York City climate policy programs covering emissions, resilience, buildings, and environmental priorities."),
    "b15eaf20-41c5-480a-bd4c-5dc813784d0f": ("city_ai_economic", "Supports New York City AI strategy work through reports, ecosystem coordination, policy framing, and economic-development planning."),
    "958193c6-c539-412d-9495-103c6c323f80": ("city_climate_office", "Leads New York City climate and environmental justice programs across resilience, emissions reduction, and equitable implementation."),
    "181c5080-c251-4764-bbda-21c10752debe": ("data_science", "Conducts NYU data science research and education across AI, machine learning, statistics, computation, and applied domains."),
    "1bdcaec5-2e06-4f0a-9a5e-7dab3f4b3776": ("medical_school", "Conducts NYU Grossman medical education, biomedical research, clinical translation, and health-science training."),
    "a5f4bae6-30d3-42bc-b950-117f33555816": ("health_system", "Provides clinical care and supports biomedical research, digital health, and translational medicine through NYU Langone Health."),
    "32509414-27b6-4e31-9d87-699729e84b6a": ("health_system", "Conducts NYU Langone research across clinical trials, biomedical science, digital health, diagnostics, and patient-care innovation."),
    "8e05e527-b8fc-46fb-a6ab-5360dd84164a": ("energy_policy_center", "Conducts NYU Stern research and engagement on sustainable business, climate strategy, finance, and corporate sustainability practices."),
    "1a2119ca-f939-4cf4-8c29-7a541b543704": ("un_policy_body", "Coordinates UN work on digital cooperation and emerging technologies through policy advice, convening, and multistakeholder dialogue."),
    "f3f552b2-2dd5-4220-8660-3b7b57ab974b": ("un_policy_body", "Advises UN leadership and member states on Africa's development priorities, partnerships, peace, security, and sustainable development."),
    "54275561-3072-42b0-a858-c03503c49249": ("ai_model_company", "Develops and deploys AI models, developer platforms, safety methods, and AI products for consumer and enterprise use."),
    "74012496-0306-4325-b73e-e3146b8a8744": ("ai_model_company", "Conducts AI research on foundation models, safety, evaluation, reasoning, multimodal systems, and model deployment methods."),
    "5aacadf9-a754-44fc-9c8f-ca50bccb3535": ("forestry_college", "Conducts Oregon State forestry research and education across forest ecosystems, wood products, wildfire, carbon, and natural resources."),
    "31fead28-e95e-4661-ae01-7257e009cc2b": ("earth_sciences_school", "Conducts Penn State earth and mineral sciences research and education across energy, mining, geoscience, climate, and materials."),
    "f4e977c8-5132-45d6-9e9f-e0a8b6d9bde2": ("renewable_energy_research", "Supports Penn State energy research across fuels, power, storage, materials, carbon management, and industrial transition."),
    "03ead3ce-3345-4416-a238-df512320b360": ("mining_department", "Conducts Penn State mining engineering research and education focused on mineral extraction, mine systems, safety, and critical resources."),
    "c2258e0d-60e7-45bc-ac0e-6e25637bd206": ("environment_regulator", "Manages Pennsylvania environmental protection programs covering air, water, energy, mining, waste, permits, and compliance."),
    "49100a07-16a3-41af-aba7-60200861e45f": ("biopharma", "Supports Pfizer Cambridge research and development in biopharmaceutical discovery, clinical translation, and therapeutic platforms."),
    "1c625083-7f0b-4098-83e4-24b77642e423": ("ag_biotech_startup", "Develops microbial nitrogen and crop-input products intended to reduce fertilizer dependence and improve field performance."),
    "dc820428-77c4-40a4-9fa5-0b27e7b51630": ("catalysis", "Supports polymer reaction engineering research focused on polymerization, process design, materials, and scale-up questions."),
    "c0ee0020-d355-49e3-9136-2f93dab29c26": ("port_authority", "Manages Port Houston infrastructure, shipping channel activity, cargo movement, industrial logistics, and port resilience programs."),
    "b2f3bebe-aa33-4f1b-9864-214133634fe4": ("university_science", "Conducts Portland State research and education across urban systems, sustainability, engineering, public affairs, and applied sciences."),
    "35793744-4a41-4573-bd88-36f288a8daa1": ("renewable_energy_research", "Supports Purdue energy research across power, fuels, storage, efficiency, materials, and industrial transition technologies."),
    "07640eaa-4c86-41d7-8ee0-177d5d724f1a": ("life_science_incubator", "Supports life-science startups with incubation, commercialization programs, facilities access, and Bay Area biotech networks."),
    "9eaf09a9-671b-47c4-817e-4d2127a3bb5f": ("applied_research_campus", "Supports Texas A&M applied research, testing, workforce, and partner projects through the RELLIS campus environment."),
    "abe34d4a-967f-4b76-9eee-3a6f62ae9d1a": ("applied_research_campus", "Provides Texas A&M RELLIS campus infrastructure for applied research, testing, education, and industry or agency partnerships."),
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
