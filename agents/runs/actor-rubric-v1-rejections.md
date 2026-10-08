# Open-Web Rejections: 74e2ef0f-2adf-4f4d-a58e-649d121b309c

Status: **failed**

Rejected candidates: **247**

Run reason: (psycopg2.OperationalError) server closed the connection unexpectedly
	This probably means the server terminated abnormally
	before or while processing the request.
server closed the connection unexpectedly
	This probably means the server terminated abnormally
	before or while processing the request.

[SQL: SELECT h.hub_id::text AS hub_id, h.name, h.primary_city, h.state, h.country, h.region, count(a.actor_id) AS actor_count FROM hub h LEFT JOIN hub_actor ha ON ha.hub_id = h.hub_id LEFT JOIN actor a ON a.actor_id = ha.actor_id AND a.merged_into_actor_id IS NULL AND (a.actor_type IS NULL OR lower(a.actor_type) <> 'aggregate') WHERE h.name <> 'Mining Hubs' GROUP BY h.hub_id, h.name, h.primary_city, h.state, h.country, h.region ORDER BY count(a.actor_id) ASC, h.name]
(Background on this error at: https://sqlalche.me/e/20/e3q8)

## A listing/directory page of member organizations, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | baltimorecity.gov | Member Organizations \| Baltimore City | https://www.baltimorecity.gov/health/about/lhic/local-health-improvement-coalition/about/member-organizations | organization health Baltimore |

## A university extension publication/directory listing multiple labs, not a single org's own page (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | extension.arizona.edu | Microbiological Water Quality Testing Labs in Arizona \| UA Cooperative Extension | https://extension.arizona.edu/publication/microbiological-water-quality-testing-labs-arizona | university lab water Phoenix Arizona |

## Academic research paper on a third-party repository, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | arxiv.org | Synergy in the Knowledge Base of U.S. Innovation Systems at National, State, and Regional Levels: The Contributions of High-Tech Manufacturing and Knowledge-Intensive Services | https://arxiv.org/pdf/1710.11017 | federal research system specialty chemicals Bay Area |

## actor already in database (41)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | azwaterinnovation.asu.edu | Home \| AZ Water Innovation Initiative | https://azwaterinnovation.asu.edu | university lab water Phoenix Arizona |
| n/a | actor | cmu.edu | Pittsburgh Deploys the Future of AI - News - Carnegie Mellon University | https://www.cmu.edu/news/stories/archives/2025/september/pittsburgh-deploys-the-future-of-ai | national research lab AI Pittsburgh Pennsylvania |
| n/a | actor | colorado.edu | Jonathan Koehn | https://www.colorado.edu/cwa/jonathan-koehn | government agency sustainability Boulder Colorado |
| n/a | actor | criticalminerals.mst.edu | About the Tech Hub - Critical Minerals - Missouri S&T | https://criticalminerals.mst.edu/techhub | organization critical minerals St. Louis Missouri |
| n/a | actor | criticalminerals.mst.edu | Consortium Members - Critical Minerals - Missouri S&T | https://criticalminerals.mst.edu/consortium-members | organization critical minerals St. Louis Missouri |
| n/a | actor | criticalminerals.mst.edu | Critical Minerals - Missouri S&T | https://criticalminerals.mst.edu | organization critical minerals St. Louis Missouri |
| n/a | actor | criticalminerals.utah.edu | Institute for Critical and Strategic Minerals – Building the future of critical minerals | https://criticalminerals.utah.edu | university critical minerals Utah |
| n/a | actor | dnr.mo.gov | Critical Minerals \| Missouri Department of Natural Resources | https://dnr.mo.gov/land-geology/geology/rocks-minerals-fossils/critical | organization critical minerals St. Louis Missouri |
| n/a | actor | dornsife.usc.edu | USC Wrigley Institute for Environment and Sustainability | https://dornsife.usc.edu/wrigley | national research center sustainability California |
| n/a | actor | edc.nyc | AI in NYC \| NYCEDC | https://edc.nyc/ai-nyc | venture capital AI New York City |
| n/a | actor | energy.gov | Critical Minerals and Materials Accelerator \| Department of Energy | https://www.energy.gov/cmei/ammto/critical-minerals-and-materials-accelerator-0 | accelerator critical minerals Reno Nevada |
| n/a | actor | energy.gov | DOE’s Office of Critical Minerals and Energy Innovation Launches Regional Consortia To Bolster Domestic Critical Minerals Supply Chain \| Department of Energy | https://www.energy.gov/cmei/articles/does-office-critical-minerals-and-energy-innovation-launches-regional-consortia | accelerator critical minerals Reno Nevada |
| n/a | actor | energy.gov | Pennsylvania Conversation on Industrial Decarbonization \| Department of Energy | https://www.energy.gov/hgeo/articles/pennsylvania-conversation-industrial-decarbonization | industrial partner critical minerals Pittsburgh Pennsylvania |
| n/a | actor | energy.gov | Texas \| Department of Energy | https://www.energy.gov/media/299775 | government agency energy Texas |
| n/a | actor | glc.org | Great Lakes Coastal Wetlands Consortium: Coastal Wetlands Investigations - Great Lakes Commission | https://www.glc.org/library/2002-coastal-wetlands-consortium | consortium water Great Lakes |
| n/a | actor | glisa.umich.edu | 2019 GLISA Small Grant: Calumet Connect: Modernizing the Calumet River Industrial Corridor \| GLISA | https://glisa.umich.edu/project/calumet-connect-modernizing-the-calumet-river-industrial-corridor | project developer sustainability Great Lakes Industrial Corridor |
| n/a | actor | ioes.ucla.edu | California Center for Sustainable Communities | https://www.ioes.ucla.edu/ccsc | national research center sustainability California |
| n/a | actor | ioes.ucla.edu | UCLA IoES — Moving science to action | https://www.ioes.ucla.edu | national research center sustainability California |
| n/a | actor | its.ucdavis.edu | Research Centers \| Institute of Transportation Studies | https://its.ucdavis.edu/research/research-centers | national research center sustainability California |
| n/a | actor | mass.gov | Massachusetts Department of Energy Resources \| Mass.gov | https://www.mass.gov/orgs/massachusetts-department-of-energy-resources | government energy Boston Massachusetts |
| n/a | actor | mass.gov | Massachusetts Energy Data \| Mass.gov | https://www.mass.gov/massachusetts-energy-data | government energy Boston Massachusetts |
| n/a | actor | mass.gov | Renewable and Alternative Energy Division \| Mass.gov | https://www.mass.gov/orgs/renewable-and-alternative-energy-division | government energy Boston Massachusetts |
| n/a | actor | news.asu.edu | Securing America's critical minerals supply \| ASU News | https://news.asu.edu/20251210-local-national-and-global-affairs-securing-americas-critical-minerals-supply | corporate R&D lab critical minerals Phoenix Arizona |
| n/a | actor | nyc.gov | GreeNYC - Mayor's Office of Sustainability | https://www.nyc.gov/site/sustainability/onenyc/greenyc.page | government sustainability New York City |
| n/a | actor | nyc.gov | NYC Sustainability (MOS) | https://www.nyc.gov/site/housingrecovery/resources/greenyc.page | government sustainability New York City |
| n/a | actor | nyc.gov | On Earth Day, Mamdani Administration Releases NYCHA Sustainability Agenda and Marks Environmental Progress Across City Government - NYC Mayor's Office | https://www.nyc.gov/mayors-office/news/2026/04/on-earth-day--mamdani-administration-releases-nycha-sustainabili | government sustainability New York City |
| n/a | actor | nyc.gov | PlaNYC: Getting Sustainability Done | https://www.nyc.gov/content/climate/pages/planyc-getting-sustainabilty-done | government sustainability New York City |
| n/a | actor | nyc.gov | Publications - Mayor's Office of Sustainability | https://www.nyc.gov/site/sustainability/about/reports-publications.page | government sustainability New York City |
| n/a | actor | nyc.gov | Sustainability - Buildings | https://www.nyc.gov/site/buildings/codes/sustainability.page | government sustainability New York City |
| n/a | actor | nyc.gov | Sustainability - Department of City Planning - DCP | https://www.nyc.gov/content/planning/pages/planning/sustainability | government sustainability New York City |
| n/a | actor | nyc.gov | Urban Sustainability - Mayor's Office of Sustainability | https://www.nyc.gov/site/sustainability/initiatives/urban-sustainability.page | government sustainability New York City |
| n/a | actor | price.utah.edu | U Announces New Institute for Critical and Strategic Minerals - The John and Marcia Price College of Engineering at the University of Utah | https://www.price.utah.edu/2026/04/14/u-announces-new-institute-for-critical-and-strategic-minerals | university critical minerals Utah |
| n/a | actor | pubmed.ncbi.nlm.nih.gov | Silicon Valley's vision to transform healthcare - PubMed | https://pubmed.ncbi.nlm.nih.gov/27078911 | government health Silicon Valley |
| n/a | actor | sustainabilitysolutions.usc.edu | USC Center for Sustainability Solutions | https://sustainabilitysolutions.usc.edu | national research center sustainability California |
| n/a | actor | unr.edu | A meeting of the mines: The Lithium Loop, Nevada’s Silicon Valley of energy \| University of Nevada, Reno | https://www.unr.edu/nevada-today/news/2025/a-meeting-of-the-mines | accelerator critical minerals Reno Nevada |
| n/a | actor | usc.edu | Sustainability Research - USC | https://www.usc.edu/sustainability/research | national research center sustainability California |
| n/a | actor | usgs.gov | USGS Earth MRI invests in Colorado critical mineral mapping \| U.S. Geological Survey | https://www.usgs.gov/news/state-news-release/usgs-earth-mri-invests-colorado-critical-mineral-mapping | state agency critical minerals Golden Colorado |
| n/a | actor | uwyo.edu | UW SER Critical Minerals AI Proposal Selected to Build Wyoming-Idaho-Nevada Coalition | https://www.uwyo.edu/news/2026/07/uw-ser-critical-minerals-ai-proposal-selected-to-build-wyoming-idaho-nevada-coalition.html | accelerator critical minerals Reno Nevada |
| n/a | actor | water.ca.gov | Directory - California Department of Water Resources - CA.gov | https://water.ca.gov/Contact/Directory | state agency water Northern California Davis |
| n/a | actor | watershed.ucdavis.edu | State Water Resources Control Board \| Center for Watershed Sciences | https://watershed.ucdavis.edu/org/state-water-resources-control-board | state agency water Northern California Davis |
| n/a | actor | wet.asu.edu | Water and Environmental Technology (WET) Center – ASU Engineering | https://wet.asu.edu | university lab water Phoenix Arizona |

## already in raw_document; Phase 1 does not fetch pages to recompute content hash (8)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | boston.gov | Boston Energy Saver \| Boston.gov | https://www.boston.gov/departments/environment/boston-energy-saver | government energy Boston Massachusetts |
| n/a | actor | coenergycrossroads.org | About \| Colorado Energy Crossroads | https://www.coenergycrossroads.org/about-4 | consortium energy Denver Colorado |
| n/a | actor | coloradocollaboratory.org | Collaborative Research - coloradocollaboratory | https://www.coloradocollaboratory.org/collaborative-research | consortium energy Denver Colorado |
| n/a | actor | cres-energy.org | Colorado Renewable Energy Society - Home | https://www.cres-energy.org | consortium energy Denver Colorado |
| n/a | actor | denvergov.org | City & County of Denver and Xcel Energy Partnership - City and County of Denver | https://denvergov.org/Government/Agencies-Departments-Offices/Agencies-Departments-Offices-Directory/Department-of-Transportation-and-Infrastructure/Denver-Xcel-Partnership | consortium energy Denver Colorado |
| n/a | actor | member.changechemistry.org | Resources for Startups - Change Chemistry | https://member.changechemistry.org/resources-for-startups | startup specialty chemicals Wilmington |
| n/a | actor | sec.state.ma.us | Energy | https://www.sec.state.ma.us/divisions/cis/guide/energy.htm | government energy Boston Massachusetts |
| n/a | actor | startupintros.com | Chemours, Inc: Funding, Team & Investors | https://startupintros.com/orgs/chemours-inc | startup specialty chemicals Wilmington |

## Appears to be a directory/listing page of AI jobs, startups, and companies rather than an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | greater-seattle.com | Seattle AI \| Jobs, Startups, Companies in Greater Seattle | https://greater-seattle.com/ai | organization AI Greater Seattle |

## Appears to be a news/press article on an investment agency site, not the actor's own substantive profile page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | investwindsoressex.com | Great Lakes region positions itself as a unified economy on the global stage - Invest WindsorEssex | https://www.investwindsoressex.com/great-lakes-region-positions-itself-as-a-unified-economy-on-the-global-stage | project developer sustainability Great Lakes Industrial Corridor |

## Bizapedia is a third-party business directory/registry listing, not the organisation's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | bizapedia.com | HOUSTON SPECIALTY CHEMICALS LLC in Houston, TX \| Company Info | https://www.bizapedia.com/tx/houston-specialty-chemicals-llc.html | government specialty chemicals Houston |

## blocked domain: axios.com (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | axios.com | SPONSORED The Bay Area pioneered AI — Seattle is scaling it | https://www.axios.com/local/san-francisco/sponsored/the-bay-area-pioneered-ai-seattle-is-scaling-it | organization AI Greater Seattle |

## blocked domain: crunchbase.com (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | crunchbase.com | List of top Venture Capital Investors with Investments in Raleigh, North Carolina - Crunchbase Hub Profile | https://www.crunchbase.com/hub/venture-capital-investors-investments-in-raleigh-north-carolina- | venture capital specialty chemicals Raleigh |

## blocked domain: en.wikipedia.org (32)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | en.wikipedia.org | Alfa Aesar | https://en.wikipedia.org/wiki/Alfa_Aesar | company specialty chemicals Boston |
| n/a | actor | en.wikipedia.org | Baltimore City Health Department | https://en.wikipedia.org/wiki/Baltimore_City_Health_Department | organization health Baltimore |
| n/a | actor | en.wikipedia.org | Boulder Reservoir | https://en.wikipedia.org/wiki/Boulder_Reservoir | federal agency water Boulder Colorado |
| n/a | actor | en.wikipedia.org | Cabot Corporation | https://en.wikipedia.org/wiki/Cabot_Corporation | company specialty chemicals Boston |
| n/a | actor | en.wikipedia.org | College of Agricultural, Consumer and Environmental Sciences | https://en.wikipedia.org/wiki/College_of_Agricultural,_Consumer_and_Environmental_Sciences | government agriculture Urbana |
| n/a | actor | en.wikipedia.org | Colorado Geological Survey | https://en.wikipedia.org/wiki/Colorado_Geological_Survey | state agency critical minerals Golden Colorado |
| n/a | actor | en.wikipedia.org | Colorado Water Conservation Board | https://en.wikipedia.org/wiki/Colorado_Water_Conservation_Board | federal agency water Boulder Colorado |
| n/a | actor | en.wikipedia.org | Colorado Water Quality Control Division | https://en.wikipedia.org/wiki/Colorado_Water_Quality_Control_Division | federal agency water Boulder Colorado |
| n/a | actor | en.wikipedia.org | Crompton Corporation | https://en.wikipedia.org/wiki/Crompton_Corporation | company specialty chemicals Boston |
| n/a | actor | en.wikipedia.org | Denver Energy Center | https://en.wikipedia.org/wiki/Denver_Energy_Center | consortium energy Denver Colorado |
| n/a | actor | en.wikipedia.org | DuPont Central Research | https://en.wikipedia.org/wiki/DuPont_Central_Research | research organization specialty chemicals Delaware |
| n/a | actor | en.wikipedia.org | GFS Chemicals | https://en.wikipedia.org/wiki/GFS_Chemicals | federal agency specialty chemicals Illinois |
| n/a | actor | en.wikipedia.org | Government of Los Angeles | https://en.wikipedia.org/wiki/Government_of_Los_Angeles | government AI Los Angeles |
| n/a | actor | en.wikipedia.org | Great Lakes Health System | https://en.wikipedia.org/wiki/Great_Lakes_Health_System | industry association health Great Lakes Medical Corridor |
| n/a | actor | en.wikipedia.org | Health Valley | https://en.wikipedia.org/wiki/Health_Valley | government health Silicon Valley |
| n/a | actor | en.wikipedia.org | Illinois Department of Agriculture | https://en.wikipedia.org/wiki/Illinois_Department_of_Agriculture | government agriculture Urbana |
| n/a | actor | en.wikipedia.org | Justsystem Pittsburgh Research Center | https://en.wikipedia.org/wiki/Justsystem_Pittsburgh_Research_Center | national research lab AI Pittsburgh Pennsylvania |
| n/a | actor | en.wikipedia.org | Ministry of Agriculture, Food and Agribusiness | https://en.wikipedia.org/wiki/Ministry_of_Agriculture,_Food_and_Agribusiness | government agriculture Urbana |
| n/a | actor | en.wikipedia.org | National Center for Ecological Analysis and Synthesis | https://en.wikipedia.org/wiki/National_Center_for_Ecological_Analysis_and_Synthesis | national research center sustainability California |
| n/a | actor | en.wikipedia.org | National Energy Technology Laboratory | https://en.wikipedia.org/wiki/National_Energy_Technology_Laboratory | national research lab AI Pittsburgh Pennsylvania |
| n/a | actor | en.wikipedia.org | Robert A. Welch Foundation | https://en.wikipedia.org/wiki/Robert_A._Welch_Foundation | government specialty chemicals Houston |
| n/a | actor | en.wikipedia.org | San Francisco Bay National Estuarine Research Reserve | https://en.wikipedia.org/wiki/San_Francisco_Bay_National_Estuarine_Research_Reserve | federal research system specialty chemicals Bay Area |
| n/a | actor | en.wikipedia.org | Sigma-Aldrich | https://en.wikipedia.org/wiki/Sigma-Aldrich | company specialty chemicals Boston |
| n/a | actor | en.wikipedia.org | Solenis | https://en.wikipedia.org/wiki/Solenis | startup specialty chemicals Wilmington \| research organization specialty chemicals Delaware |
| n/a | actor | en.wikipedia.org | Strem Chemicals | https://en.wikipedia.org/wiki/Strem_Chemicals | company specialty chemicals Boston |
| n/a | actor | en.wikipedia.org | Sustainable Seattle | https://en.wikipedia.org/wiki/Sustainable_Seattle | startup sustainability Seattle |
| n/a | actor | en.wikipedia.org | The Engine (organization) | https://en.wikipedia.org/wiki/The_Engine_(organization) | accelerator health Boston Cambridge |
| n/a | actor | en.wikipedia.org | USC Wrigley Institute for Environmental Studies | https://en.wikipedia.org/wiki/USC_Wrigley_Institute_for_Environmental_Studies | national research center sustainability California |
| n/a | actor | en.wikipedia.org | Upstate Niagara Cooperative | https://en.wikipedia.org/wiki/Upstate_Niagara_Cooperative | nonprofit agriculture Upstate New York |
| n/a | actor | en.wikipedia.org | Urbana, Illinois | https://en.wikipedia.org/wiki/Urbana,_Illinois | government agriculture Urbana |
| n/a | actor | en.wikipedia.org | Vantage Specialty Chemicals | https://en.wikipedia.org/wiki/Vantage_Specialty_Chemicals | industry association specialty chemicals Chicago \| federal agency specialty chemicals Illinois |
| n/a | actor | en.wikipedia.org | Woodland Davis Clean Water Agency | https://en.wikipedia.org/wiki/Woodland_Davis_Clean_Water_Agency | state agency water Northern California Davis |

## blocked domain: facebook.com (2)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | facebook.com | Boulder County Climate (@BoulderCountyClimate) | https://www.facebook.com/BoulderCountyClimate | government agency sustainability Boulder Colorado |
| n/a | actor | facebook.com | Great Lakes Water Safety Consortium (@GLWaterSafety) | https://www.facebook.com/GLWaterSafety | consortium water Great Lakes |

## blocked domain: linkedin.com (5)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | linkedin.com | Affinity Research Chemicals, Inc \| LinkedIn | https://www.linkedin.com/company/affinitychem | research organization specialty chemicals Delaware |
| n/a | actor | linkedin.com | Colorado Energy Research Collaboratory \| LinkedIn | https://www.linkedin.com/company/co-energy-research-collaboratory | consortium energy Denver Colorado |
| n/a | actor | linkedin.com | Great Lakes Health Connect \| LinkedIn | https://www.linkedin.com/company/great-lakes-health-connect | industry association health Great Lakes Medical Corridor |
| n/a | actor | linkedin.com | Great Lakes Water Safety Consortium | https://www.linkedin.com/company/glwatersafety | consortium water Great Lakes |
| n/a | actor | linkedin.com | The Chemours Company \| LinkedIn | https://www.linkedin.com/company/chemours | startup specialty chemicals Wilmington |

## blocked domain: prnewswire.com (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | prnewswire.com | Great Lakes Impact Investment Platform nears $4 billion in sustainability projects | https://www.prnewswire.com/news-releases/great-lakes-impact-investment-platform-nears-4-billion-in-sustainability-projects-301375204.html | project developer sustainability Great Lakes Industrial Corridor |

## blocked domain: techcrunch.com (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | techcrunch.com | There Are No More “Tech Issues” | https://techcrunch.com | government health Silicon Valley |

## Blog post listing multiple VC firms, a third-party compilation. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | every.io | List Of Venture Capital Firms In North Carolina | https://www.every.io/blog-post/venture-capital-firms-north-carolina | venture capital specialty chemicals Raleigh |

## Category/tag listing page on a news outlet site, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | missouribusinessalert.com | Critical Minerals \| missouribusinessalert.com | https://www.missouribusinessalert.com/critical_minerals | organization critical minerals St. Louis Missouri |

## D&B business directory category listing, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | dnb.com | Basic Chemical Manufacturing companies in Illinois, ... | https://www.dnb.com/business-directory/company-information.basic_chemical_manufacturing.us.illinois.html | federal agency specialty chemicals Illinois |

## Data/statistics category page on a research indicators site, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | siliconvalleyindicators.org | Quality of Health | https://siliconvalleyindicators.org/data/society/quality-of-health | government health Silicon Valley |

## Directory listing page aggregating multiple suppliers, not a single organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | thomasnet.com | Specialty Chemicals in or near Northern California (CA) on Thomasnet | https://www.thomasnet.com/suppliers/northern-california/all-cities/specialty-chemicals-13900758 | federal research system specialty chemicals Bay Area |

## Directory/listing page of multiple accelerators, not a single organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | nvsmallbiz.org | Accelerators \| Nevada SSBCI | https://nvsmallbiz.org/accelerators | accelerator critical minerals Reno Nevada |

## Directory/listing page of multiple organizations, not an actor's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | ncbiotech.org | Venture Capital and Angel Investor Groups \| North Carolina Biotechnology Center | https://www.ncbiotech.org/venture-capital-firms-and-angel-investor-organizations | venture capital specialty chemicals Raleigh |

## Directory/listing page of multiple VC firms, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | aivclist.com | Series A Venture Capital Firms in New York \| AI VC List – Active AI & Machine Learning Investors | https://aivclist.com/pages/series-a-new-york | venture capital AI New York City |

## EurekAlert is a third-party press release distribution site, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | eurekalert.org | University of Utah announces new Institute for Critical and Strategic Minerals \| EurekAlert! | https://www.eurekalert.org/news-releases/1124156 | university critical minerals Utah |

## Glassdoor is a third-party directory/listing site, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | glassdoor.com | Top Chemical Manufacturing Companies in Chicago \| Glassdoor | https://www.glassdoor.com/Explore/top-chemical-manufacturing-companies-chicago_II.4,26_IIND200068_IL.37,44_IM167.htm | industry association specialty chemicals Chicago |

## Government database search/directory page listing multiple labs, not a single organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | ells-lab-search.azdhs.gov | Arizona Department of Health Services Licensed Commercial Drinking Water Laboratories | https://ells-lab-search.azdhs.gov/DrinkingWaterTestingLabs/drinkingwatersearchcontentpage | university lab water Phoenix Arizona |

## Government directory listing of venture capital funds/banks, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | raleighnc.gov | Venture Capital Funds and Banks \| Raleighnc.gov | https://raleighnc.gov/doing-business/venture-capital-funds-and-banks | venture capital specialty chemicals Raleigh |

## Government document rendition link, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | pcb.illinois.gov | Illinois | https://pcb.illinois.gov/documents/dsweb/Get/Rendition-49040/index.htm | federal agency specialty chemicals Illinois |

## Government legislative transcript, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | legis.state.pa.us | Critical Minerals in Pennsylvania: Context and Opportunities Pete Rozelle | https://www.legis.state.pa.us/WU01/LI/TR/Transcripts/2022_0002_0004_TSTMNY.pdf | industrial partner critical minerals Pittsburgh Pennsylvania |

## Government patent database document, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | image-ppubs.uspto.gov | Data processing system for providing an efficient market for specialty chemicals | https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/8008081 | federal research system specialty chemicals Bay Area |

## Government report PDF, not an organisation's own substantive profile page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | osc.ny.gov | report 13 2026 | https://www.osc.ny.gov/files/reports/osdc/pdf/report-13-2026.pdf | venture capital AI New York City |

## Government trade site listing multiple industry associations, a third-party directory page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | trade.gov | SelectUSA Chemicals Industry Associations | https://www.trade.gov/selectusa-chemicals-industry-associations | industry association specialty chemicals Chicago |

## GuideStar is a third-party nonprofit directory/profile aggregator, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | guidestar.org | GREAT LAKES WATER SAFETY CONSORTIUM - GuideStar Profile | https://www.guidestar.org/profile/81-2812105 | consortium water Great Lakes |

## Indeed career advice article listing multiple companies is third-party editorial content, not an org's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | indeed.com | Learn About 15 Chemical Companies in Houston, Texas \| Indeed.com | https://www.indeed.com/career-advice/finding-a-job/chemical-companies-in-houston-tx | government specialty chemicals Houston |

## max_candidates_triaged cap hit before LLM triage (27)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | affinitychem.com | For All Your Chemistry Needs \| Affinity Research Chemicals | https://www.affinitychem.com | research organization specialty chemicals Delaware |
| n/a | actor | bmc.org | Health Equity Accelerator \| Boston Medical Center | https://www.bmc.org/health-equity-accelerator | accelerator health Boston Cambridge |
| n/a | actor | bostonstartupsguide.com | Boston Startup Accelerators, Incubators, & Support Programs - Boston Startups Guide | https://bostonstartupsguide.com/guide/every-boston-startup-accelerator-incubator | accelerator health Boston Cambridge |
| n/a | actor | britannica.com | Delaware - Chemicals, Agriculture, Manufacturing \| Britannica | https://www.britannica.com/place/Delaware-state/Industry | research organization specialty chemicals Delaware |
| n/a | actor | capitol.texas.gov | BILL ANALYSIS | https://capitol.texas.gov/tlodocs/74R/analysis/html/HB03086S.htm | government agency energy Texas |
| n/a | actor | catskillmountainkeeper.org | Farm/Food Organizations - Catskill Mountainkeeper | https://www.catskillmountainkeeper.org/farm_food_organizations | nonprofit agriculture Upstate New York |
| n/a | actor | causeiq.com | Agricultural organizations in New York \| Cause IQ | https://www.causeiq.com/directory/agricultural-organizations-list/new-york-state | nonprofit agriculture Upstate New York |
| n/a | actor | causeiq.com | Rochester, NY food and agriculture nonprofits \| Cause IQ | https://www.causeiq.com/directory/food-and-agriculture-nonprofits-list/rochester-ny-metro | nonprofit agriculture Upstate New York |
| n/a | actor | comptroller.texas.gov | Local Government Energy Program - Texas Comptroller | https://comptroller.texas.gov/programs/seco/programs/local | government agency energy Texas |
| n/a | actor | comptroller.texas.gov | State Energy Conservation Office - Texas Comptroller | https://comptroller.texas.gov/programs/seco | government agency energy Texas |
| n/a | actor | delawareacs.org | About \| ACS \| Delaware Section | https://delawareacs.org/about | research organization specialty chemicals Delaware |
| n/a | actor | eia.gov | Texas Electricity Profile 2024 - U.S. Energy Information Administration (EIA) | https://www.eia.gov/electricity/state/texas | government agency energy Texas |
| n/a | actor | frontiersciencepartnerships.com | About Us - Frontier Science Partnerships | https://frontiersciencepartnerships.com/about-us | research organization specialty chemicals Delaware |
| n/a | actor | glo.texas.gov | Energy \| Texas General Land Office | https://www.glo.texas.gov/energy | government agency energy Texas |
| n/a | actor | masslifesciences.com | Incubators, Accelerators, & Co-Working Spaces - MLSC | https://www.masslifesciences.com/resources/incubators | accelerator health Boston Cambridge |
| n/a | actor | mehi.masstech.org | MassChallenge HealthTech \| MeHI | https://mehi.masstech.org/mass-digital-health-programs/masschallenge-healthtech | accelerator health Boston Cambridge |
| n/a | actor | nal.usda.gov | Urban Agriculture \| National Agricultural Library | https://www.nal.usda.gov/farms-and-agricultural-production-systems/urban-agriculture | government agriculture Urbana |
| n/a | actor | nofany.org | NOFA-NY \| Northeast Organic Farming Association of New York | https://nofany.org | nonprofit agriculture Upstate New York |
| n/a | actor | nylcvef.org | New York State Knows Sustainable Farming - NEW YORK LEAGUE OF CONSERVATION VOTERS | https://nylcvef.org/citizens-toolkit/sustainable-farming-in-upstate-new-york | nonprofit agriculture Upstate New York |
| n/a | actor | puc.texas.gov | Public Utility Commission of Texas | https://www.puc.texas.gov/Default.aspx | government agency energy Texas |
| n/a | actor | purecatskills.com | Buy Local Products - Pure Catskills | https://purecatskills.com/local-products | nonprofit agriculture Upstate New York |
| n/a | actor | rocksteadyfarm.com | Rock Steady Farm | https://www.rocksteadyfarm.com | nonprofit agriculture Upstate New York |
| n/a | actor | techstars.com | Techstars Boston Accelerator \| Techstars Accelerators \| Techstars | https://www.techstars.com/accelerators/boston | accelerator health Boston Cambridge |
| n/a | actor | tfc.texas.gov | OFFICE of ENERGY MANAGEMENT - Texas Facilities Commission | https://www.tfc.texas.gov/divisions/facilities/prog/fmd/EnergyManagement.html | government agency energy Texas |
| n/a | actor | upstatecurious.com | American Farmland Trust's New York Farmland Access Fund | https://www.upstatecurious.com/farm | nonprofit agriculture Upstate New York |
| n/a | actor | usda.gov | Urban Agriculture and Innovative Production \| USDA | https://www.usda.gov/farming-and-ranching/agricultural-education-and-outreach/urban-agriculture-and-innovative-production | government agriculture Urbana |
| n/a | actor | watt-watchers.com | About the State Energy Conservation Office - Watt Watchers of Texas | https://www.watt-watchers.com/about/about-the-state-energy-conservation-office | government agency energy Texas |

## News article from a local news outlet, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | northernnvnow.com | Northern NV Now, gener8tor, and Kiln Convene Investors, Founders, and Regional Partners in Reno for Electrify Nevada Accelerator Showcase - Northern NV Now | https://northernnvnow.com/edawn-gener8tor-and-kiln-convene-investors-founders-and-regional-partners-in-reno-for-electrify-nevada-accelerator-showcase | accelerator critical minerals Reno Nevada |

## News article from a media outlet (gazette.com), not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | gazette.com | Federal biotech commission examines Colorado’s role in critical minerals production | https://gazette.com/2026/07/30/federal-biotech-commission-examines-colorados-role-in-critical-minerals-production | state agency critical minerals Golden Colorado |

## News article from a media outlet, not the organisation's own page. (3)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | chicago.suntimes.com | Citing Southeast Side Calumet industrial corridor ‘legacy of environmental racism,’ Alliance for the Great Lakes report urges City Hall to consider residents’ health in land-use plans - Chicago Sun-Times | https://chicago.suntimes.com/2021/2/5/22266912/southeast-side-calumet-industrial-corridor-pollutants-alliance-great-lakes-general-iron | project developer sustainability Great Lakes Industrial Corridor |
| n/a | actor | greatlakesnow.org | Consortium of Great Lakes universities and tech companies gets $15M to seek ways to clean wastewater - Great Lakes Now | https://www.greatlakesnow.org/2024/01/30/ap-consortium-of-great-lakes-universities-and-tech-companies-gets-15m-to-seek-ways-to-clean-wastewater | consortium water Great Lakes |
| n/a | actor | thecentersquare.com | A $40B critical mineral supply chain could start in Pennsylvania \| Pennsylvania \| thecentersquare.com | https://www.thecentersquare.com/pennsylvania/article_f0a98eac-45ee-11ef-928c-332fe6bb1968.html | industrial partner critical minerals Pittsburgh Pennsylvania |

## News article from a third-party media outlet, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | statescoop.com | Generative AI creeps into Los Angeles city government \| StateScoop | https://statescoop.com/los-angeles-maryland-google-gemini-ai | government AI Los Angeles |

## News article from public radio station, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | kbia.org | Amid trade wars, Missouri’s mining industry digs deep \| KBIA | https://www.kbia.org/kbia-news/2026-03-16/amid-trade-wars-missouris-mining-industry-digs-deep | organization critical minerals St. Louis Missouri |

## News article on a third-party media outlet about a startup, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | technical.ly | Wilmington startup Lectrolyst transforms carbon dioxide into brand new resources | https://technical.ly/startups/lectrolyst-carbon-dioxide | startup specialty chemicals Wilmington |

## News listing page, not a substantive organisation page about a specific entity. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | greater-seattle.com | News - Greater Seattle Partners | https://greater-seattle.com/news | organization AI Greater Seattle |

## News magazine taxonomy/tag listing page, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | homecaremag.com | Great Lakes Home Medical Services Association \| HomeCare Magazine | https://www.homecaremag.com/taxonomy/term/13831 | industry association health Great Lakes Medical Corridor |

## news or press page on own domain (21)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | bmc.org | How Boston Medical Center’s health equity accelerator is fast-tracking clinical improvements \| Boston Medical Center | https://www.bmc.org/news/how-boston-medical-centers-health-equity-accelerator-fast-tracking-clinical-improvements | accelerator health Boston Cambridge |
| n/a | actor | boston.gov | New Boston Community Choice Electricity Rates, Providing Energy Savings to Residents and Small Businesses \| Boston.gov | https://www.boston.gov/news/new-boston-community-choice-electricity-rates-providing-energy-savings-residents-and-small | government energy Boston Massachusetts |
| n/a | actor | boston.gov | Utility Resources \| Boston.gov | https://www.boston.gov/news/utility-resources | government energy Boston Massachusetts |
| n/a | actor | codedistrict.com | Top 10 AI Companies in Boston for 2026 (Compared by Experts) | https://codedistrict.com/blog/best-ai-companies-in-boston | industrial partner AI Greater Boston |
| n/a | actor | dakota.com | Top 10 Private Equity Firms in Raleigh: 2026 Guide | https://www.dakota.com/resources/blog/top-10-private-equity-firms-in-raleigh-2025-guide | venture capital specialty chemicals Raleigh |
| n/a | actor | foxla.com | California launches ‘Ask CA’ AI tool to help residents access government services \| FOX 11 Los Angeles | https://www.foxla.com/news/california-launches-ask-ca-ai-tool-help-residents-access-government-services | government AI Los Angeles |
| n/a | actor | kleinmanenergy.upenn.edu | A Long Time Coming: Biden Administration Advances Domestic Critical Minerals Development in Pennsylvania | https://kleinmanenergy.upenn.edu/commentary/blog/a-long-time-coming-biden-administration-advances-domestic-critical-minerals-development-in-pennsylvania | industrial partner critical minerals Pittsburgh Pennsylvania |
| n/a | actor | lionssg.com | Top Chemical Companies in Delaware \| Trusted Suppliers | https://lionssg.com/blog/top-chemical-companies-in-delaware-leading-manufacturers-and-suppliers | research organization specialty chemicals Delaware |
| n/a | actor | news.engineering.arizona.edu | Symposium Explores Path to Producing More Critical Minerals in US | https://news.engineering.arizona.edu/news/symposium-explores-path-producing-more-critical-minerals-us | corporate R&D lab critical minerals Phoenix Arizona |
| n/a | actor | newsroom.bluecrossma.com | Healthbox and Blue Cross Blue Shield of Massachusetts Host Boston Innovation Day | https://newsroom.bluecrossma.com/2012-11-09-Healthbox-and-Blue-Cross-Blue-Shield-of-Massachusetts-Host-Boston-Innovation-Day | accelerator health Boston Cambridge |
| n/a | actor | psu.edu | Critical minerals and materials workshop fosters collaboration, partnerships \| Penn State University | https://www.psu.edu/news/earth-and-mineral-sciences/story/critical-minerals-and-materials-workshop-fosters-collaboration | industrial partner critical minerals Pittsburgh Pennsylvania |
| n/a | actor | standard.net | University of Utah is poised to support the state’s critical minerals ambitions with new institute \| News, Sports, Jobs - Standard-Examiner | https://www.standard.net/news/2026/apr/15/university-of-utah-is-poised-to-support-the-states-critical-minerals-ambitions-with-new-institute | university critical minerals Utah |
| n/a | actor | steel-technology.com | US Strategic Metals Signs MOU With Stillwater Critical Minerals | https://www.steel-technology.com/news/us-strategic-metals-signs-mou-with-stillwater-critical-minerals | organization critical minerals St. Louis Missouri |
| n/a | actor | stlmag.com | Fire and fury in Fredericktown, but lithium-ion plant prepares to rebuild \| St. Louis Magazine | https://www.stlmag.com/news/fredericktown-lithium-ion-plant-fire-critical-mineral-recovery | organization critical minerals St. Louis Missouri |
| n/a | actor | tech.co | 10 Seattle Startups That Are Preserving Mother Earth | https://tech.co/news/green-startups-seattle-mother-earth-2016-11 | startup sustainability Seattle |
| n/a | actor | techstars.com | Meet the Techstars Boston Class of 2023 | https://www.techstars.com/newsroom/meet-the-techstars-boston-class-of-2023 | accelerator health Boston Cambridge |
| n/a | actor | techstars.com | Techstars Boston Accelerator | https://www.techstars.com/blog/techstars-boston-accelerator | accelerator health Boston Cambridge |
| n/a | actor | timesunion.com | Gift economy takes root at upstate New York farm | https://www.timesunion.com/news/article/gift-economy-takes-root-upstate-new-york-farm-21116652.php | nonprofit agriculture Upstate New York |
| n/a | actor | visible.vc | Top NYC Venture Capital Firms: The 2026 Founder's List - Visible.vc | https://visible.vc/blog/venture-capital-firms-in-nyc | venture capital AI New York City |
| n/a | actor | walnutcapital.com | The Future of AI in Pittsburgh \| Walnut Capital Blog | https://www.walnutcapital.com/blog/the-future-of-ai-in-pittsburgh | national research lab AI Pittsburgh Pennsylvania |
| n/a | actor | waveup.com | Top Venture Capital Firms in NYC — 2026 Guide \| Waveup | https://waveup.com/blog/venture-capital-firms-nyc | venture capital AI New York City |

## News outlet article about a partnership, not an organisation's own page (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | marylandmatters.org | Partnership seeks to make Montgomery County ‘the Silicon Valley of health computing’ - Maryland Matters | https://marylandmatters.org/2022/11/12/partnership-seeks-to-make-montgomery-county-the-silicon-valley-of-health-computing | government health Silicon Valley |

## News/insights article by a bank about the NYC AI ecosystem, not the organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | svb.com | Empire State of AI: New York’s dynamic AI community | https://www.svb.com/startup-insights/vc-relations/empire-state-of-ai | venture capital AI New York City |

## News/journalism site article, not the organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | circleofblue.org | Chicago Prepares Development Plan For Industrial Zone With Priority for Water and Wetland | https://www.circleofblue.org/2025/great-lakes/chicago-prepares-development-plan-for-industrial-zone-with-priority-for-water-and-wetland | project developer sustainability Great Lakes Industrial Corridor |

## News/media publication article, not an organisation's own page (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | medicaleconomics.com | Silicon Valley’s vision to transform healthcare \| Medical Economics | https://www.medicaleconomics.com/view/silicon-valleys-vision-transform-healthcare | government health Silicon Valley |

## Nextdoor is a third-party social/directory platform, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | nextdoor.com | Specialty Chemical Products - South Houston, TX - Nextdoor | https://nextdoor.com/pages/specialty-chemical-products-south-houston-tx | government specialty chemicals Houston |

## obvious non-content URL pattern: /tag/ (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | hmenews.com | Great Lakes Home Medical Services Association \| HME News | https://www.hmenews.com/tag/great-lakes-home-medical-services-association | industry association health Great Lakes Medical Corridor |

## PDF appears to be a third-party directory listing of multiple laboratories, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | arizonaag.com | analytical-laboratories-for-plant-soil-and-water-testing.pdf | https://arizonaag.com/wp-content/uploads/2013/06/analytical-laboratories-for-plant-soil-and-water-testing.pdf | university lab water Phoenix Arizona |

## Salt Lake Magazine is a third-party news/magazine outlet, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | saltlakemagazine.com | University of Utah is Poised to Support the State’s Critical Minerals Ambitions • Salt Lake Magazine | https://saltlakemagazine.com/institute-for-critical-and-strategic-minerals | university critical minerals Utah |

## State economic development site listing multiple companies by industry, a category/directory page not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | choosedelaware.com | Science and Biotech Companies \| Delaware Prosperity Partnership | https://www.choosedelaware.com/key-industries/delaware-biotech-science-technology | startup specialty chemicals Wilmington \| research organization specialty chemicals Delaware |

## Sub-category data page on an indicators site, not an actor's own organisational page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | siliconvalleyindicators.org | Health Care | https://siliconvalleyindicators.org/data/society/quality-of-health/health-care | government health Silicon Valley |

## Third-party business directory/profile page, not the organisation's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | zoominfo.com | Great Lakes Home Medical Services Association - Overview, News & Similar companies \| ZoomInfo.com | https://www.zoominfo.com/c/great-lakes-home-medical-services-association/369684562 | industry association health Great Lakes Medical Corridor |

## Third-party category listing page aggregating multiple companies, not a single organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | builtinboston.com | Top Boston, MA Chemical Companies 2026 \| Built In | https://www.builtinboston.com/companies/type/chemical-companies | company specialty chemicals Boston |

## Third-party consortium-style listicle aggregating multiple startups, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | startus-insights.com | 5 Top Startups providing Specialty Chemicals \| StartUs Insights | https://www.startus-insights.com/innovators-guide/specialty-chemicals-startups | startup specialty chemicals Wilmington |

## Third-party directory listing of hospitals/clinics, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | causeiq.com | Baltimore health organizations \| Cause IQ | https://www.causeiq.com/directory/hospitals-and-clinics-list/baltimore-columbia-towson-md-metro | organization health Baltimore |

## Third-party directory listing of multiple funded companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | growthlist.co | 500+ NYC AI Startups 2026 \| Funded Companies & Verified Leads - Growth List | https://growthlist.co/nyc-ai-startups | venture capital AI New York City |

## Third-party directory listing of organisations, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | causeiq.com | Baltimore organizations supporting a health care nonprofit \| Cause IQ | https://www.causeiq.com/directory/organizations-supporting-a-health-care-nonprofit-list/baltimore-columbia-towson-md-metro | organization health Baltimore |

## Third-party directory listing of VC firms, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | openvc.app | Top Venture Capital Firms and Investors in New York City [2026] | https://www.openvc.app/investor-lists/venture-capital-firms-investors-new-york-city | venture capital AI New York City |

## Third-party directory listing page, not an organisation's own page. (3)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | causeiq.com | Agricultural organizations in Missouri \| Cause IQ | https://www.causeiq.com/directory/agricultural-organizations-list/missouri-state | nonprofit agriculture Missouri |
| n/a | actor | causeiq.com | Food and agriculture nonprofits in Missouri \| Cause IQ | https://www.causeiq.com/directory/food-and-agriculture-nonprofits-list/missouri-state | nonprofit agriculture Missouri |
| n/a | actor | causeiq.com | Kansas City agricultural organizations \| Cause IQ | https://www.causeiq.com/directory/agricultural-organizations-list/kansas-city-mo-ks-metro | nonprofit agriculture Missouri |

## Third-party directory listing VC firms by location, not an org's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | growthmentor.com | Venture Capital Firms in Raleigh For Early-Stage Startups \| GrowthMentor | https://www.growthmentor.com/location/raleigh/venture-capital | venture capital specialty chemicals Raleigh |

## Third-party directory/category listing of companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | builtinchicago.org | Top Chicago, IL Energy Companies 2026 \| Built In | https://www.builtinchicago.org/companies/type/energy-companies | organization energy Chicago |

## Third-party directory/category listing page of environmental innovation startups. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | seattle.startups-list.com | Environmental innovation Companies in Seattle • • Seattle Startups List | https://seattle.startups-list.com/startups/environmental_innovation | startup sustainability Seattle |

## Third-party directory/category listing page of sustainability startups. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | seattle.startups-list.com | Sustainability Companies in Seattle • • Seattle Startups List | https://seattle.startups-list.com/startups/sustainability | startup sustainability Seattle |

## Third-party directory/consortium-listing page, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | causeiq.com | Organizations supporting multiple food and agriculture nonprofits in Missouri \| Cause IQ | https://www.causeiq.com/directory/organizations-supporting-multiple-food-and-agriculture-nonprofits-list/missouri-state | nonprofit agriculture Missouri |

## Third-party directory/listicle of startups, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | startupsavant.com | 22 Top Seattle Startups to Watch in 2026 \| TRUiC | https://startupsavant.com/startups-to-watch/seattle | startup sustainability Seattle |

## Third-party directory/listing page of multiple companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | glassdoor.com | Top Chemical Manufacturing Companies in Boston \| Glassdoor | https://www.glassdoor.com/Explore/top-chemical-manufacturing-companies-boston_II.4,26_IIND200068_IL.37,43_IM109.htm | company specialty chemicals Boston |

## Third-party directory/listing site ranking companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | zippia.com | Best Manufacturing Companies To Work For In Wilmington, DE - Zippia | https://www.zippia.com/company/best-manufacturing-companies-in-wilmington-de | startup specialty chemicals Wilmington |

## Third-party directory/search listing of companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | seamless.ai | List of $100M - $500M Chemical Companies in Chicago, Illinois \| Seamless.AI | https://seamless.ai/search-companies | industry association specialty chemicals Chicago |

## Third-party educational nonprofit's encyclopedia entry about a topic, not the agency's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | watereducation.org | State Water Project - Water Education Foundation | https://www.watereducation.org/aquapedia/state-water-project | state agency water Northern California Davis |

## Third-party guide/listicle article about multiple startups, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | seattle-beautiful.com | A Guide to Seattle's Most Innovative Startups - Seattle Beautiful | https://seattle-beautiful.com/a-guide-to-seattles-most-innovative-startups | startup sustainability Seattle |

## Third-party informational article about regulations, not the federal agency's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | eldoradosprings.com | Colorado Drinking Water Regulations | https://www.eldoradosprings.com/colorado-impact/colorado-drinking-water-regulations | federal agency water Boulder Colorado |

## Third-party job listing aggregator page, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | ziprecruiter.com | Artificial Intelligence Government Jobs in Los Angeles, CA | https://www.ziprecruiter.com/Jobs/Artificial-Intelligence-Government/-in-Los-Angeles,CA | government AI Los Angeles |

## Third-party market research report, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | researchnester.com | U.S. Specialty Chemicals Market Size & Share, Growth Trends 2036 | https://www.researchnester.com/reports/united-states-specialty-chemicals-market/8392 | federal research system specialty chemicals Bay Area |

## Third-party market research/resource page on funding trends, not an org's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | netzeroinsights.com | 2025 Specialty Chemicals Funding Explained | https://netzeroinsights.com/resources/2025-specialty-chemicals-funding | venture capital specialty chemicals Raleigh |

## Third-party news article from a media outlet, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | cities-today.com | Los Angeles to equip entire city workforce with Google AI - Cities Today | https://cities-today.com/los-angeles-to-equip-entire-city-workforce-with-google-ai | government AI Los Angeles |

## Third-party news site article about the topic, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | blueskypit.com | Pittsburgh Is Poised to Lead the Next Generation of AI - Blue Sky News | https://blueskypit.com/pittsburgh-is-poised-to-lead-the-next-generation-of-ai | national research lab AI Pittsburgh Pennsylvania |

## Third-party news site reporting on the story, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | bigenergynews.com | University of Arizona Receives $20 Million for Critical Minerals Mining Lab · Big Energy | https://bigenergynews.com/2026/09/university-of-arizona-receives-20-million-for-critical-minerals-mining-lab | corporate R&D lab critical minerals Phoenix Arizona |

## Third-party news/business publication article, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | nevadabusiness.com | The New Era of Mining in America: Development & Critical Minerals | https://nevadabusiness.com/2026/06/the-new-era-of-mining-in-america-governors-office-economic-development-critical-minerals | accelerator critical minerals Reno Nevada |

## Third-party nonprofit directory listing, not the organisation's own site (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | idealist.org | caa70554a8cc450fb893c72fc979370a the health trust of silicon valley san jose | https://www.idealist.org/en/nonprofit/caa70554a8cc450fb893c72fc979370a-the-health-trust-of-silicon-valley-san-jose | government health Silicon Valley |

## Third-party substack commentary/news post, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | drpippa.substack.com | Pittsburgh PA - Atomic Forge: Pennsylvania is Using AI to Script the Materials Revolution of the 21st Century | https://drpippa.substack.com/p/pittsburgh-pa-atomic-forge-pennsylvania | national research lab AI Pittsburgh Pennsylvania |

## Third-party trade publication article, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | siteselection.com | GREAT LAKES: A Legacy Constantly in the Making – Site Selection Magazine | https://siteselection.com/great-lakes-a-legacy-constantly-in-the-making | project developer sustainability Great Lakes Industrial Corridor |

## This is a chamber of commerce category listing page, not a single organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | cca.bayareahouston.com | Specialty Chemicals - Houston, TX | https://cca.bayareahouston.com/Specialty-Chemicals-__5005239_category.aspx | government specialty chemicals Houston |

## This is a chamber of commerce member directory listing page, not the organisation's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | denverchamber.org | CORE Electric Cooperative - Denver Metro Chamber of Commerce | https://denverchamber.org/members/core-electric-cooperative | consortium energy Denver Colorado |

## This is a directory listing page, not the organisation's own substantive content page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | edgewaterenvironmentalcoalition.org | Directory \| EEC | https://www.edgewaterenvironmentalcoalition.org/directory | organization energy Chicago |

## This is a directory/listing publication of multiple labs, not an org's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | extension.arizona.edu | Laboratories Conducting Soil, Plant, Feed or Water Testing \| UA Cooperative Extension | https://extension.arizona.edu/publication/laboratories-conducting-soil-plant-feed-or-water-testing | university lab water Phoenix Arizona |

## This is a news article about a third-party company's expansion, not the organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | greater-seattle.com | AI Startup Gamer Republic Chooses Greater Seattle for Global Expansion | https://greater-seattle.com/2025/09/16/ai-startup-gamer-republic-chooses-greater-seattle-for-global-expansion | organization AI Greater Seattle |

## This is a news article from Colorado Public Radio, third-party journalism rather than the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | cpr.org | Colorado looks to secure its place in the critical minerals industry with expanding partnership | https://www.cpr.org/2026/05/12/mines-national-laboratory-of-the-rockies-critical-minerals-partnership | state agency critical minerals Golden Colorado |

## This is a news/media outlet article, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | boulderweekly.com | Below our feet - Boulder Weekly | https://boulderweekly.com/climate/groundwater | federal agency water Boulder Colorado |

## This is a news/roundup page listing investments and developments across multiple organisations, not one organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | greater-seattle.com | Latest Artificial Intelligence Investments, Developments, Programs, Grants, in Greater Seattle | https://greater-seattle.com/artificial-intelligence-investments | organization AI Greater Seattle |

## This is a partner listing page on a different organisation's site, not the consortium's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | safeboatingcampaign.com | Great Lakes Water Safety Consortium | https://safeboatingcampaign.com/become-a-partner/partners/great-lakes-water-safety-consortium-ann-arbor-michigan-48113 | consortium water Great Lakes |

## This is a press release page on a Senate committee site, third-party coverage rather than the actor's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | biotech.senate.gov | Colorado Biotech Unlocking Critical Minerals for U.S. National Security - Biotech | https://www.biotech.senate.gov/press-releases/colorado-biotech-unlocking-critical-minerals-for-u-s-national-security | state agency critical minerals Golden Colorado |

## This is a third-party association's member directory listing, not the organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | hanys.org | Great Lakes Health System of Western New York - Directory of HANYS Members \| HANYS | https://www.hanys.org/member_directory | industry association health Great Lakes Medical Corridor |

## This is a third-party database/directory listing page for Colorado, not an organisation's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | database.aceee.org | Colorado \| ACEEE | https://database.aceee.org/state/colorado | consortium energy Denver Colorado |

## This is a third-party directory listing category page, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | thomasnet.com | Research & Testing Laboratories in or near Arizona (AZ) on Thomasnet | https://www.thomasnet.com/suppliers/arizona/all-cities/research-testing-laboratories-42631200 | corporate R&D lab critical minerals Phoenix Arizona |

## This is a third-party directory/category listing of multiple companies, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | builtinchicago.org | Top Chicago, IL Renewable Energy Companies 2026 \| Built In | https://www.builtinchicago.org/companies/type/renewable-energy-companies | organization energy Chicago |

## This is a third-party grant directory/category listing page, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | missouri.grantwatch.com | Agriculture Grants (2026) \| Farming Funding in Missouri, Kansas City, St. Louis, Springfield, Independence, Columbia - GrantWatch | https://missouri.grantwatch.com/cat/51/farming-and-agriculture-grants.html | nonprofit agriculture Missouri |

## This is a third-party jobs/directory listing profile page, not the organization's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | builtinboston.com | AI Technology Partners Boston Office: Careers, Perks + Culture \| Built In Boston | https://www.builtinboston.com/company/ai-technology-partners | industrial partner AI Greater Boston |

## This is a third-party listicle/directory of multiple companies, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | shadhinlab.com | Top AI Development Companies in Boston: Innovators Leading the AI Revolution - Shadhin Lab LLC \| Cloud Based AI Automation Partner | https://shadhinlab.com/top-ai-development-companies-in-boston | industrial partner AI Greater Boston |

## This is a third-party news article on an industry media site, not the organization's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | aibusiness.com | Boston Dynamics, Google DeepMind Partner on Industrial AI | https://aibusiness.com/generative-ai/boston-dynamics-google-partner-industrial-ai | industrial partner AI Greater Boston |

## This is a third-party news/media article about Missouri agriculture, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | farmflavor.com | An Overview of Missouri Agriculture - Farm Flavor | https://farmflavor.com/missouri/missouri-crops-livestock/missouri-agriculture | nonprofit agriculture Missouri |

## This is a third-party report/news page about multiple federal labs, not an organisation's own substantive page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | ccst.us | California's Federal Labs & Research Centers: A 2021 Impact Report for State Leaders - California Council on Science & Technology (CCST) | https://ccst.us/reports/californias-federal-labs-research-centers-a-2021-impact-report-for-state-leaders | federal research system specialty chemicals Bay Area |

## This is an industry report/aggregated content page, not a specific organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | greater-seattle.com | Greater Seattle Technology & AI Industry Report 2025: Workforce, Investment, and Market Trends | https://greater-seattle.com/greater-seattle-technology-ai-industry-report-2025 | organization AI Greater Seattle |

## ThomasNet is a third-party business directory listing, not the organisation's own site. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | thomasnet.com | Houston Specialty Chemicals LLC: Houston, TX 77056 | https://www.thomasnet.com/company/houston-specialty-chemicals-llc-31011536/profile | government specialty chemicals Houston |

## Thomasnet is a third-party directory/category listing, not an organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | thomasnet.com | Specialty Chemicals in or near Illinois (IL) on Thomasnet | https://www.thomasnet.com/suppliers/illinois/all-cities/specialty-chemicals-13900758 | federal agency specialty chemicals Illinois |

## Tucson.com is a third-party news site republishing a press release, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | tucson.com | University of Utah announces new Institute for Critical and Strategic Minerals | https://tucson.com/online_features/press_releases/article_03993406-e110-51cc-986a-a6f89c756faa.html | university critical minerals Utah |

## University department affiliations listing page, not the organisation's own page and functions as a directory of third-party affiliates. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | medicine.buffalo.edu | Hospital and Research Institution Affiliations - Department of Biomedical Informatics - University at Buffalo | https://medicine.buffalo.edu/departments/biomedical-informatics/about/affiliations.html | industry association health Great Lakes Medical Corridor |

## Utah News Dispatch is a third-party news outlet, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | utahnewsdispatch.com | University of Utah is poised to support the state’s critical minerals ambitions with new institute • Utah News Dispatch | https://utahnewsdispatch.com/briefs/university-of-utah-pursuing-new-critical-minerals-institute | university critical minerals Utah |

## Yelp is a third-party directory/review site, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | yelp.com | SPECIALTY CHEMICAL PRODUCTS - Updated August 2026 - 1407 Pennsylvania St, South Houston, Texas - Phone Number - Yelp | https://www.yelp.com/biz/specialty-chemical-products-south-houston | government specialty chemicals Houston |

## Yelp is a third-party review/directory site, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | yelp.com | IAS LABS - Updated June 2026 - 21 Photos - 2515 E University Dr, Phoenix, Arizona - Environmental Testing - Phone Number - Yelp | https://www.yelp.com/biz/ias-labs-phoenix | university lab water Phoenix Arizona |

## ZoomInfo is a third-party business data directory, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | zoominfo.com | Great Lakes Water Safety Consortium - Overview, News & Similar companies \| ZoomInfo.com | https://www.zoominfo.com/c/great-lakes-water-safety-consortium/461329586 | consortium water Great Lakes |

## ZoomInfo is a third-party business directory/profile aggregator, not the organisation's own page. (1)

| Score | Entity | Domain | Title | URL | Query |
| ---: | --- | --- | --- | --- | --- |
| n/a | actor | zoominfo.com | Chemours - Overview, News & Similar companies \| ZoomInfo.com | https://www.zoominfo.com/c/the-chemours-co/368294277 | startup specialty chemicals Wilmington |
