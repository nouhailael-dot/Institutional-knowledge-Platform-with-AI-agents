# Source Diagnostics

## Conclusions

### climate_week

- Reachability: `https://www.climateweeknyc.org/event-search` returned HTTP 200 through the robots-aware fetch layer.
- Server-rendered event data: yes. The page contains one `.hubdb-listing` container and 428 `article.event-card` rows.
- Selector to use: listing container `.hubdb-listing`; event rows `article.event-card`.
- Pagination conclusion: the page includes the server-side marker `event listing: total=428 fetched=428 pages_needed=5 max_pages=10`. Parsed rows equal displayed/fetched total, so the 5.1 MB page currently contains every event, with MixItUp pagination applied client-side. No additional request is needed right now.
- Fix applied: add a configured floor of 400 rows and a displayed-total guard. If rows parsed drop below the floor or displayed total exceeds parsed rows, the run closes as `attention`.

### unga_programme

- Reachability: `https://www.un.org/en/ga/81/meetings/` returned HTTP 200 with the configured browser-like User-Agent. The earlier 404/non-browser behavior is avoided by the current User-Agent path.
- Server-rendered event data: yes. The relevant content is inside `div#content`, under `h3` text `Provisional Schedule`, in the following `ul`.
- Selector to use: page container `div#content`; provisional schedule rows are the first `ul > li` after `Provisional Schedule`.
- Event count: 9 provisional schedule rows.
- Fix applied: use a deterministic `unga_programme` extractor for that schedule list instead of relying on Claude to find rows after the long navigation/header section.

### unga_guide

- Reachability: `https://ungaguide.com/` returned HTTP 200 with the robots-aware fetch layer. The zero-byte manual `curl` was not reproduced here; diagnostics show no Cloudflare/interstitial page and no redirect problem. The most likely cause was the earlier curl/User-Agent/request setup rather than site unavailability.
- Server-rendered event data: yes. The root page contains 12 `article.unga_event` rows inside `div.articles-wrapper`.
- Full listing location: the root page plus `/page/2/` through `/page/11/`. The root page displays `Search through 124 events`, and diagnostics found 124 `article.unga_event` rows across 11 fetched pages.
- Selector to use: listing container `div.articles-wrapper`; event rows `article.unga_event`; rich event facts are also present in `script[type="application/ld+json"]`.
- Fix applied: discover the full `/page/N/` range and extract deterministically from JSON-LD plus article metadata, keeping the coming-soon guard for future empty states.

## climate_week
- Requested URL: `https://www.climateweeknyc.org/event-search`
- Final URL: `https://www.climateweeknyc.org/event-search`
- HTTP status: `200`
- Byte count: `5179993`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\climate_week\01_www.climateweeknyc.org_event-search.html`
- Listing selector: `.hubdb-listing`
- Listing selector matches: `1`
- Item selector: `article.event-card`
- Item selector matches: `428`

First item element snippets:
```html
<article class="event-card mix date-20260927 public in-person theme-built-environment theme-environmental-justice theme-cities" data-title="day 2: climate innovation, energy &amp; community garden tours with lungs" data-name="Day 2: Climate Innovation, Energy &amp; Community Garden Tours with LUNGS">

                    <a href="/event-search/day-2-climate-innovation-energy-community-garden-tours-with-lungs?hsLang=en" class="event-card__link" target="_blank" rel="noopener noreferrer">

    ... [truncated]
```
```html
<article class="event-card mix date-20260927 public in-person theme-cities" data-title="free central park bike tour for climate week nyc 9/27 - 11:00am" data-name="Free Central Park Bike Tour for Climate Week NYC 9/27 - 11:00AM">

                    <a href="/event-search/free-central-park-bike-tour-for-climate-week-nyc-927-1100am?hsLang=en" class="event-card__link" target="_blank" rel="noopener noreferrer">

                        <div class="event-card__image" data-image-id-url="" data-i... [truncated]
```
First 1500 body characters:
```html
<!--  Added by GoogleTagManager integration -->
<noscript><iframe src="https://www.googletagmanager.com/ns.html?id=GTM-WTJLKM4" height="0" width="0" style="display:none;visibility:hidden"></iframe></noscript>

<!-- /Added by GoogleTagManager integration -->


    <div class="body-wrapper fd-light-active   hs-content-id-354562384077 hs-site-page page ">

      
      <div data-global-resource-path="strutoCX Theme - Climate Group/templates/partials/climate-week-nyc-header.html"><header class="header">

  <div class="container-fluid">
<div class="row-fluid-wrapper">
<div class="row-fluid">
<div class="span12 widget-span widget-type-cell " style="" data-widget-type="cell" data-x="0" data-w="12">

<div class="row-fluid-wrapper row-depth-1 row-number-1 dnd-section header-row-0-padding header-row-0-force-full-width-section">
<div class="row-fluid ">
<div class="span12 widget-span widget-type-custom_widget dnd-module" style="" data-widget-type="custom_widget" data-x="0" data-w="12">
<div id="hs_cos_wrapper_header-module-1" class="hs_cos_wrapper hs_cos_wrapper_widget hs_cos_wrapper_type_module" style="" data-hs-cos-general-type="widget" data-hs-cos-type="module">








<!-- Main Menu -->
<header class="ap-header-main-section ap-header-main-section-header-module-1 header__primary-header">
  
  <!-- Top Container -->
  <div class="ap-header-main-container ap-header-top-container">
    <div class="ap-header-main-menu-wrap">
      
      <div class="ap-main-menu-desktop-content">

     ... [truncated]
```
Top class attribute values:
- `event-card__link`: 428
- `event-card__image`: 428
- `event-card__content`: 428
- `event-card__title`: 428
- `event-card__meta`: 428
- `event-card__meta-list`: 428
- `event-card__meta-item event-card__meta-item--date`: 428
- `event-card__meta-item event-card__meta-item--format`: 428
- `event-card__meta-item event-card__meta-item--type`: 406
- `event-card__meta-item event-card__meta-item--location`: 389

## unga_programme
- Requested URL: `https://www.un.org/en/ga/81/meetings/`
- Final URL: `https://www.un.org/en/ga/81/meetings/`
- HTTP status: `200`
- Byte count: `29526`
- Content type: `text/html`
- Saved page: `agents\diagnostics\unga_programme\01_www.un.org_en_ga_81_meetings.html`
- Listing selector: `div#content`
- Listing selector matches: `1`
- Item selector: `li`
- Item selector matches: `109`

First listing element snippets:
```html
<div id="content" class="col-xs-12 col-md-9"> 
    <h2>High-level Meetings of the 81st Session</h2>
    <h3>Provisional Schedule</h3>
    <ul>
      <li><strong>Opening of the 81st session</strong>: 8 September 2026 | <a aria-label="official document, in PDF" href="https://undocs.org/en/A/INF/81/1">A/INF/81/1</a>&nbsp;<img src="/common/images/icons/ico_pdf.gif" alt="PDF"></li>
      <li><strong>Sustainable Development Goals (SDG) Moment</strong>: 18 September 2026 | <a aria-label="official ... [truncated]
```
First item element snippets:
```html
<li><a href="#site-main-menu">Skip to main navigation</a></li>
```
```html
<li><a href="#content">Skip to content</a></li>
```

## unga_guide
- Requested URL: `https://ungaguide.com/`
- Final URL: `https://ungaguide.com/`
- HTTP status: `200`
- Byte count: `75354`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\01_ungaguide.com.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9560 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-art-culture unga_event_category-climate-environment unga_event_category-data-tech unga_event_category-government unga_event_category-sustainable-development">
    <header>
        <time datetime="2026-09-10">
            <span class="date">Thu, Sep 10</span>
            <span class="time">Multi-Day Event</span>
        </ti... [truncated]
```
First item element snippets:
```html
<article class="post-9560 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-art-culture unga_event_category-climate-environment unga_event_category-data-tech unga_event_category-government unga_event_category-sustainable-development">
    <header>
        <time datetime="2026-09-10">
            <span class="date">Thu, Sep 10</span>
            <span class="time">Multi-Day Event</span>
        </time>
    </header>
    <div class="body">
    <h2 class="u... [truncated]
```
```html
<article class="post-9561 unga_event type-unga_event status-publish hentry unga_event_category-health">
    <header>
        <time datetime="2026-09-14">
            <span class="date">Mon, Sep 14</span>
            <span class="time">9:00am - 5:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/c3-davos-of-healthcare-nyc-summit/">C3 Davos of Healthcare™ NYC Summit</a></h2>
                <p class="unga-event_... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/2/`
- Final URL: `https://ungaguide.com/page/2/`
- HTTP status: `200`
- Byte count: `73029`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\02_ungaguide.com_page_2.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9885 unga_event type-unga_event status-publish hentry">
    <header>
        <time datetime="2026-09-20">
            <span class="date">Sun, Sep 20</span>
            <span class="time">5:30pm - 7:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/network-social/">Network Social</a></h2>
                <p class="unga-event__organize... [truncated]
```
First item element snippets:
```html
<article class="post-9885 unga_event type-unga_event status-publish hentry">
    <header>
        <time datetime="2026-09-20">
            <span class="date">Sun, Sep 20</span>
            <span class="time">5:30pm - 7:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/network-social/">Network Social</a></h2>
                <p class="unga-event__organizer">Rani</p>
                </div>
</article>
```
```html
<article class="post-9639 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment unga_event_category-economic-development">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">All Day Event</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/accelerating-business-leadership-on-air-pollution-roundtable/">Ac... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/3/`
- Final URL: `https://ungaguide.com/page/3/`
- HTTP status: `200`
- Byte count: `73713`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\03_ungaguide.com_page_3.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9862 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">9:00am - 12:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/solving-food-waste-is-a-key-solution-to-the-cl... [truncated]
```
First item element snippets:
```html
<article class="post-9862 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">9:00am - 12:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/solving-food-waste-is-a-key-solution-to-the-climate-crisis/">Solving Food Waste is a Key Solution to th... [truncated]
```
```html
<article class="post-9640 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">9:30am - 12:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/ceo-water-mandates-corporate-water-stewardship-half-day/">CEO Water Mandate&#8217;s Corporate Water Ste... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/4/`
- Final URL: `https://ungaguide.com/page/4/`
- HTTP status: `200`
- Byte count: `82578`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\04_ungaguide.com_page_4.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9904 unga_event type-unga_event status-publish hentry unga_event_category-gender unga_event_category-health">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">3:30pm - 6:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/sustaining-action-for-women-and-g... [truncated]
```
First item element snippets:
```html
<article class="post-9904 unga_event type-unga_event status-publish hentry unga_event_category-gender unga_event_category-health">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">3:30pm - 6:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/sustaining-action-for-women-and-girls/">Sustaining Action for Women and Girls</a></h2>
   ... [truncated]
```
```html
<article class="post-9927 unga_event type-unga_event status-publish hentry unga_event_category-health">
    <header>
        <time datetime="2026-09-21">
            <span class="date">Mon, Sep 21</span>
            <span class="time">4:00pm - 6:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/crisis-in-preparedness-laboratories-frontline-readiness-in-the-time-of-ebola/">Crisis in preparedness: laboratories &... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/5/`
- Final URL: `https://ungaguide.com/page/5/`
- HTTP status: `200`
- Byte count: `75837`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\05_ungaguide.com_page_5.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9910 unga_event type-unga_event status-publish hentry unga_event_category-government">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">Multi-Day Event</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/unga81-high-level-week-general-debate/">UNGA81 High-Leve... [truncated]
```
First item element snippets:
```html
<article class="post-9910 unga_event type-unga_event status-publish hentry unga_event_category-government">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">Multi-Day Event</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/unga81-high-level-week-general-debate/">UNGA81 High-Level Week / General Debate</a></h2>
                <p class... [truncated]
```
```html
<article class="post-9692 unga_event type-unga_event status-publish hentry unga_event_category-economic-development unga_event_category-government unga_event_category-human-rights">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">All Day Event</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/ungps-at-15-business-leadership-on-human-... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/6/`
- Final URL: `https://ungaguide.com/page/6/`
- HTTP status: `200`
- Byte count: `75683`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\06_ungaguide.com_page_6.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9660 unga_event type-unga_event status-publish hentry unga_event_category-health unga_event_category-sustainable-development">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">9:30am - 11:00am</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/the-health-syst... [truncated]
```
First item element snippets:
```html
<article class="post-9660 unga_event type-unga_event status-publish hentry unga_event_category-health unga_event_category-sustainable-development">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">9:30am - 11:00am</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/the-health-system-stress-test-why-kidney-health-matters-for-uhc/">The He... [truncated]
```
```html
<article class="post-9556 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">10:00am - 12:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/how-do-we-create-meaningful-climate-action-in-an-increasingly-authoritarian-usa-2/">How Do We Create M... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/7/`
- Final URL: `https://ungaguide.com/page/7/`
- HTTP status: `200`
- Byte count: `87737`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\07_ungaguide.com_page_7.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9897 unga_event type-unga_event status-publish hentry unga_event_category-education unga_event_category-youth">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">2:00pm - 3:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/in-the-shadow-of-tomorrow-nurtu... [truncated]
```
First item element snippets:
```html
<article class="post-9897 unga_event type-unga_event status-publish hentry unga_event_category-education unga_event_category-youth">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">2:00pm - 3:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/in-the-shadow-of-tomorrow-nurturing-human-thriving-in-a-polycrisis-world/">In the Shadow... [truncated]
```
```html
<article class="post-9907 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-data-tech">
    <header>
        <time datetime="2026-09-22">
            <span class="date">Tue, Sep 22</span>
            <span class="time">2:00pm - 6:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/navigating-power-trust-and-cooperation-in-an-era-of-strategic-competition/">Navigating Powe... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/8/`
- Final URL: `https://ungaguide.com/page/8/`
- HTTP status: `200`
- Byte count: `78044`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\08_ungaguide.com_page_8.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9888 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-data-tech unga_event_category-gender unga_event_category-government unga_event_category-human-rights unga_event_category-sustainable-development unga_event_category-youth">
    <header>
        <time datetime="2026-09-23">
            <span class="date">Wed, Sep 23</span>
            <span class="time">10:00am - 4:00pm</spa... [truncated]
```
First item element snippets:
```html
<article class="post-9888 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-data-tech unga_event_category-gender unga_event_category-government unga_event_category-human-rights unga_event_category-sustainable-development unga_event_category-youth">
    <header>
        <time datetime="2026-09-23">
            <span class="date">Wed, Sep 23</span>
            <span class="time">10:00am - 4:00pm</span>
        </time>
    </header>
    <div class="body">
 ... [truncated]
```
```html
<article class="post-9552 unga_event type-unga_event status-publish hentry unga_event_category-art-culture">
    <header>
        <time datetime="2026-09-23">
            <span class="date">Wed, Sep 23</span>
            <span class="time">11:00am - 2:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/rewear-the-revolution-street-event/">ReWear the Revolution (Street Event)</a></h2>
                <p class="un... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/9/`
- Final URL: `https://ungaguide.com/page/9/`
- HTTP status: `200`
- Byte count: `77088`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\09_ungaguide.com_page_9.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9840 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment unga_event_category-data-tech unga_event_category-economic-development">
    <header>
        <time datetime="2026-09-24">
            <span class="date">Thu, Sep 24</span>
            <span class="time">8:00am - 2:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https... [truncated]
```
First item element snippets:
```html
<article class="post-9840 unga_event type-unga_event status-publish hentry unga_event_category-climate-environment unga_event_category-data-tech unga_event_category-economic-development">
    <header>
        <time datetime="2026-09-24">
            <span class="date">Thu, Sep 24</span>
            <span class="time">8:00am - 2:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/climate-solutions-investing-a-sys... [truncated]
```
```html
<article class="post-9726 unga_event type-unga_event status-publish hentry unga_event_category-sustainable-development">
    <header>
        <time datetime="2026-09-24">
            <span class="date">Thu, Sep 24</span>
            <span class="time">8:00am - 1:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/united-nations-global-compact-network-usa-annual-summit-the-room-where-it-happens-shaping-the-next-e... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/10/`
- Final URL: `https://ungaguide.com/page/10/`
- HTTP status: `200`
- Byte count: `77355`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\10_ungaguide.com_page_10.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `12`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9548 unga_event type-unga_event status-publish hentry unga_event_category-health">
    <header>
        <time datetime="2026-09-25">
            <span class="date">Fri, Sep 25</span>
            <span class="time">8:00am - 7:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/new-approaches-summit-nyc-2026-5th-annual-date/">New Approac... [truncated]
```
First item element snippets:
```html
<article class="post-9548 unga_event type-unga_event status-publish hentry unga_event_category-health">
    <header>
        <time datetime="2026-09-25">
            <span class="date">Fri, Sep 25</span>
            <span class="time">8:00am - 7:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/new-approaches-summit-nyc-2026-5th-annual-date/">New Approaches Summit: NYC 2026 &#8211; 5th Annual Date</a></h2>
   ... [truncated]
```
```html
<article class="post-9549 unga_event type-unga_event status-publish hentry unga_event_category-gender unga_event_category-health">
    <header>
        <time datetime="2026-09-25">
            <span class="date">Fri, Sep 25</span>
            <span class="time">9:00am</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/2026-women-in-nephrology-leadership-conference/">2026 Women in Nephrology Leadership Conference</a>... [truncated]
```

## unga_guide
- Requested URL: `https://ungaguide.com/page/11/`
- Final URL: `https://ungaguide.com/page/11/`
- HTTP status: `200`
- Byte count: `59193`
- Content type: `text/html; charset=UTF-8`
- Saved page: `agents\diagnostics\unga_guide\11_ungaguide.com_page_11.html`
- Listing selector: `div.articles-wrapper`
- Listing selector matches: `1`
- Item selector: `article.unga_event`
- Item selector matches: `4`

First listing element snippets:
```html
<div class="container articles-wrapper">
                <article class="post-9571 unga_event type-unga_event status-publish hentry unga_event_category-art-culture unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-26">
            <span class="date">Sat, Sep 26</span>
            <span class="time">10:00am - 1:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/the-importance... [truncated]
```
First item element snippets:
```html
<article class="post-9571 unga_event type-unga_event status-publish hentry unga_event_category-art-culture unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-26">
            <span class="date">Sat, Sep 26</span>
            <span class="time">10:00am - 1:00pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/the-importance-of-artists-and-art-making-in-the-climate-movement/">The ... [truncated]
```
```html
<article class="post-9570 unga_event type-unga_event status-publish hentry unga_event_category-ai unga_event_category-climate-environment">
    <header>
        <time datetime="2026-09-26">
            <span class="date">Sat, Sep 26</span>
            <span class="time">1:30pm - 3:30pm</span>
        </time>
    </header>
    <div class="body">
    <h2 class="unga-event__title"><a href="https://ungaguide.com/events/ai-and-the-climate-crisis-who-benefits-who-bears-the-environmental-costs/">AI and... [truncated]
```
