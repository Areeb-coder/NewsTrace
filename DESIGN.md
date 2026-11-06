# NewsTrace — Editorial Design System

## Direction

**The Digital News Chronicle**: a newspaper from the 1920s–1950s reimagined as a modern source-led news-intelligence product.

The site is not a dashboard wearing a paper texture. The newspaper metaphor shapes the masthead, navigation, story hierarchy, columns, metadata, section dividers, image treatment and motion. Modern interactions remain focused on research tasks: investigate a publication, inspect coverage, review journalists, search records and export evidence.

## Research references and what was adapted

These references informed the design principles. NewsTrace does not copy their identity, assets or page layouts.

| Reference | Observed principle | NewsTrace adaptation |
|---|---|---|
| [The Economist](https://www.economist.com/) | Recognisable masthead, concise issue/date information, strong subject navigation and restrained red accent | Oversized serif wordmark, edition strip, section navigation and oxblood editorial accent |
| [The Guardian — Interactive](https://www.theguardian.com/interactive) | Visual journalism and dedicated interactive-storytelling areas | Coverage analysis remains a distinct workspace rather than being buried in a generic dashboard |
| [The Pudding](https://pudding.cool/) | Visual essays that turn data and research into an explorable story | Lead-report hierarchy, article relationships and a more narrative presentation of collected coverage |
| [The Public Domain Review](https://publicdomainreview.org/) | Carefully curated archival imagery, essay metadata and category-led browsing | Archive-like image treatment, section/byline/date hierarchy and editorial story groupings |
| [Public Domain Image Archive](https://pdimagearchive.org/) | Browsing/filtering image collections through useful facets | Searchable archive and section filter retained in the dataset view |
| [Library of Congress — Historical Newspapers](https://guides.loc.gov/united-states-newspapers/historical-newspapers) | Research-guide navigation and archive-oriented information organization | Clear issue context, source provenance and research-focused archive navigation |
| [Awwwards — Magazine / Newspaper / Blog](https://www.awwwards.com/websites/magazine-newspaper-blog/) | Editorial grids and variation in content scale | Asymmetric lead story with ruled multi-column story rows |
| [Awwwards — Storytelling](https://www.awwwards.com/websites/storytelling/) | Staged content entrances and intentional motion | Short masthead reveal and restrained hover transitions |
| [Awwwards — Typography](https://www.awwwards.com/websites/typography/) | Typography as the central visual system | Display serif, readable sans-serif and compact monospaced metadata |

## Visual tokens

| Token | Value | Purpose |
|---|---|---|
| Paper | #F2EBDD | Main canvas |
| Light paper | #F8F3E9 | Inputs and raised reading surfaces |
| Deep paper | #E5D9C5 | Secondary surfaces |
| Ink | #29231D | Headlines and primary text |
| Soft ink | #5B5145 | Body copy and secondary labels |
| Faint ink | #827665 | Metadata |
| Oxblood | #852F2A | Editorial accent, links and primary actions |
| Deep oxblood | #67231F | Hover state |
| Olive | #4F5947 | Quiet secondary data accent |

### Typography

- **Cormorant Garamond** — masthead and editorial headlines.
- **Source Sans 3** — interface labels, controls and readable UI text.
- **IBM Plex Mono** — dates, issue information, categories, counts and archive metadata.

### Layout

- A centered publication masthead with date, volume/issue and edition.
- A compact horizontal newspaper navigation band.
- A wide lead story with an asymmetric copy/media split.
- A 12-column story grid with dense placement and ruled separators.
- A single-column vertical reading order on small screens.
- Coverage, journalist and archive tools remain separate, task-oriented views.

## Imagery

Article lead imagery is extracted from publisher metadata (og:image, Twitter image metadata) or article figures when available. JSON API responses may also provide image_url, image, thumbnail or featured_image. Images are never fabricated from article headlines.

The display treatment uses grayscale, a light sepia cast and contrast. If a source does not provide an image, the front page uses a typographic placeholder rather than unrelated stock photography.

## Motion and accessibility

- The masthead uses a short GSAP reveal for the date strip, wordmark, deck and bottom rule.
- Article images shift gently on hover; story links reveal an underline.
- Native page scrolling remains unchanged.
- prefers-reduced-motion disables nonessential transitions and animation.
- Links open the original article in a new tab; visible text identifies the source action.
- The dataset search, section filter and CSV/JSON exports remain native Streamlit controls.

## Functional boundaries

The design does not replace or simulate news content. Story headlines, authors, dates, image URLs and original article links come from the active investigation. When the user has not run an investigation, the front page shows the investigation entry point and explains how to begin.

The Streamlit app remains a server-side application and still requires a host that supports a long-running Streamlit process and Playwright/Chromium. A successful UI redesign does not imply that every publisher permits automated scraping.
