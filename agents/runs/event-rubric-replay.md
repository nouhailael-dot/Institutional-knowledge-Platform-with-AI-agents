# Event Rubric Stored-Page Evaluation

Status: incomplete

This distribution is not suitable for calibration: parser validation rejected recoverable
responses before the follow-up fix, and Anthropic then rejected the remaining analysis and
rerank calls because the account credit balance was too low.

Run: `7e1d35c9-abd0-42f8-aa72-433dd6f3304d`
Run date: `2026-09-15`
Model: `claude-sonnet-5`
Prompt version: `event_rubric_record_v2`
Pages: 21
Analysis cache hits: 0
Analysis failures: 18
Evaluation cost: $0.411433

| Outcome | Count | Proportion |
| --- | ---: | ---: |
| auto_high | 1 | 4.8% |
| review | 0 | 0.0% |
| auto_low | 2 | 9.5% |
| analysis_failed | 18 | 85.7% |
| attendable | 1 | 4.8% |
| minable | 1 | 4.8% |

| Score | Band | Qualification | Rerank | Event | URL | Reason |
| ---: | --- | --- | ---: | --- | --- | --- |
| 0.950 | auto_high | attendable, minable | 1 | 2027 ARPA-E Energy Innovation Summit | https://www.arpae-summit.com/Home | stored-page event rubric evaluation |
| 0.000 | auto_low | none | 2 | Summit 2026 | https://cmforum.org/summit2026 | stored-page event rubric evaluation |
| 0.000 | auto_low | none | 3 | U.S. Chamber of Commerce Critical Minerals Summit 2026 | https://events.uschamber.com/USChamberofCommerceCriticalMineralsSummit2026 | stored-page event rubric evaluation |
|  | analysis_failed | none |  | missing title | https://www.unep.org/events/conference/global-framework-chemicals-first-international-conference | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | stored://7e1d35c9-abd0-42f8-aa72-433dd6f3304d/27a97625127326ea1db3ecea075fc861fc65b5a57e035e9c2d922c7c839c5836.html | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://events.newsweek.com/ai-health-nyc-2026 | event rubric analysis failed: event rubric extraction must return separate rubric and record objects |
|  | analysis_failed | none |  | missing title | https://events.nyas.org/aihealth26 | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://www.arpae-summit.com/Summit-Info/About-the-Summit | event rubric analysis failed: event rubric extraction must return separate rubric and record objects |
|  | analysis_failed | none |  | missing title | https://events.nyas.org/aihealth26/11552812 | event rubric analysis failed: event rubric item 'single_discrete_event' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://www.arpae-summit.com/Agenda | event rubric analysis failed: event rubric item 'named_speakers' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://www.arpae-summit.com/Agenda/Summit-Agenda-Preview | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://events.mountsinaihealth.org/event/the-new-wave-of-ai-in-healthcare-2026 | event rubric analysis failed: event rubric extraction must return separate rubric and record objects |
|  | analysis_failed | none |  | missing title | https://tethys.pnnl.gov/events/2026-arpa-e-energy-innovation-summit | event rubric analysis failed: event rubric item 'open_external_registration' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://www.multi-statesalinitycoalition.com/mssc-summit/ | event rubric analysis failed: event rubric item 'named_speakers' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://www.awwa.org/event/watersmart-innovations/ | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | stored://7e1d35c9-abd0-42f8-aa72-433dd6f3304d/d21b2112fa9faaa378208550447cbfc4dc196adc6fce5074f683c8a0169f420e.html | event rubric analysis failed: event rubric item 'date_within_window' must use null evidence when absent |
|  | analysis_failed | none |  | missing title | https://icca-chem.org/event/first-international-conference-of-the-global-framework-on-chemicals/ | event rubric analysis failed: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vMyV7kQLyUF9CruS8S'} |
|  | analysis_failed | none |  | missing title | https://rare-earth-mining.com/critical-minerals-summit-indonesia/ | event rubric analysis failed: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vNU1MyL7jvvcEVq8uu'} |
|  | analysis_failed | none |  | missing title | https://brownandcaldwell.com/2026/02/multi-state-salinity-coalition-2026-annual-salinity-summit/ | event rubric analysis failed: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vNbJuE7Xv6JpJT5Ltm'} |
|  | analysis_failed | none |  | missing title | https://www.criticalmineralsnorthamerica.com | event rubric analysis failed: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vNnzrqLQDyr81Zp7PG'} |
|  | analysis_failed | none |  | missing title | stored://7e1d35c9-abd0-42f8-aa72-433dd6f3304d/f75492db598bbd5f9240938fde2beebbe20da4325691887d63def1bf9b79818c.html | event rubric analysis failed: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vNsbgRESE1wNtq9hnh'} |

Rerank attention: event rerank failed for group starting 1: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'Your credit balance is too low to access the Anthropic API. Please go to Plans & Billing to upgrade or purchase credits.'}, 'request_id': 'req_011Cf7vNvfEWQ5r2KkT5NBkg'}
