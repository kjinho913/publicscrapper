Here is the complete translation and formatting of your markdown document into English:

# Public Institution Business Announcement Auto-Collector — Program Manual

Date: 2026-05-19

---

## 1. Program Overview

This is a scraper pipeline that automatically collects business announcements (bids, services, projects, etc.) from multiple public institution websites, filters them based on keywords, and saves them into an Excel file. It also downloads attached files (announcement PDFs, HWPs, etc.).

**Primary Objective**: Automatically collect public bidding announcements related to IT, AI, and data on a daily basis and manage them cumulatively in a single Excel file.

---

## 2. Target Websites

| Code   | Institution                                                  | URL                                                | Method                            | Current Status                     |
| ------ | ------------------------------------------------------------ | -------------------------------------------------- | --------------------------------- | ---------------------------------- |
| `nipa` | National IT Industry Promotion Agency (NIPA)                 | [https://www.nipa.kr](https://www.nipa.kr)         | HTML Parsing                      | ✅ Normal                          |
| `mss`  | Ministry of Startups and SMEs (MSS)                          | [https://www.mss.go.kr](https://www.mss.go.kr)     | HTML Parsing                      | ✅ Normal                          |
| `g2b`  | Korea ON-line E-Procurement System (G2B / Narajangteo)       | [https://www.g2b.go.kr](https://www.g2b.go.kr)     | Public Data Portal Open API (XML) | ✅ Normal (API Key Required)       |
| `nia`  | National Information Society Agency (NIA)                    | [https://www.nia.or.kr](https://www.nia.or.kr)     | HTML Parsing                      | ✅ Normal                          |
| `etri` | Electronics and Telecommunications Research Institute (ETRI) | [https://ebid.etri.re.kr](https://ebid.etri.re.kr) | HTML Parsing (POST)               | ✅ Normal                          |

The activation status of each site can be configured under the `sources` section in `app/config.yaml`.

---

## 3. Overall Operation Pipeline

```
[Each Website]
    │
    ▼
① List Collection (fetch_list)
    │  Each site's scraper iterates through list pages up to N pages to
    │  extract Announcement No., Title, Ordering Agency, Announcement Date, Closing Date/Time, and Link.
    │
    ▼
② Detail Collection (fetch_detail)
    │  Visit the detail page of each announcement → Complement Summary, Budget, and Attachment URLs.
    │  (G2B already includes detailed information from the API)
    │
    ▼
③ Keyword Filtering (filters.py)
    │  Passes if any of the configured keywords are included in the
    │  "Announcement Title + Content Summary + Ordering Agency" text (OR Logic).
    │
    ▼
④ Attachment Download (downloader.py)
    │  Streaming download after checking allowed extensions and max file size.
    │  Save Path: output/attachments/{source_site}/{announcement_no}/
    │
    ▼
⑤ Save to Excel (excel_writer.py)
    │  Removes duplicates based on (Announcement No. + Source Site) and adds new rows only.
    │  Rows closing within 7 days → Highlighted in Orange.
    │  Announcement Links & Attachment Paths → Clickable Hyperlinks.
    │
    ▼
output/announcements.xlsx  (Cumulative Update)
output/attachments/...     (Attached Files)
logs/scraper_YYYY-MM-DD.log

```

---

## 4. Module Responsibilities

### `app/main.py` — Entry Point & Orchestrator

- Parses command-line arguments (`--once`, `--schedule`, `--debug-*`).
- Loads `config.yaml`.
- Executes activated scrapers sequentially and aggregates results.
- Execution Modes:
- `--once`: Runs immediately for one cycle and exits.
- `--schedule`: Automatically repeats daily according to `schedule.time` (default 08:00) in `config.yaml`.
- `--debug-{site}`: Outputs raw HTML of the site's list page (for selector debugging).

### `scrapers/base.py` — Common Base Class

- `requests.Session` + Auto-retry (up to 3 backoff retries on 500, 502, 503, 504 errors).
- Random delay between requests (1–3 seconds to prevent server overload).
- Auto-detects encoding for Korean websites (handling a mix of EUC-KR and UTF-8).
- Abstract class inherited by all site-specific scrapers.

### `scrapers/nipa.py` — NIPA Scraper

- Business Announcement List: `[https://www.nipa.kr/home/bsnsAll/0/nttList?bbsNo=4&tab=2](https://www.nipa.kr/home/bsnsAll/0/nttList?bbsNo=4&tab=2)`
- Page Parameter: `curPage`
- CSS Selectors: `table.tbgg tbody tr` / `a[href*='nttDetail']`
- Detail Link: Resolves relative path based on `LIST_URL` to `./nttDetail?tab=2&bbsNo=4&nttNo={ID}`.

### `scrapers/mss.py` — MSS Scraper

- Business Announcement List: `https://www.mss.go.kr/site/smba/ex/bbs/List.do?cbIdx=310`
- CSS Selectors: `table tbody tr` / `a[onclick*='doBbsFView']`
- Detail Link: Extracts `bcIdx` from `doBbsFView('310', '{bcIdx}', ...)` in onclick attribute →
  `https://www.mss.go.kr/site/smba/ex/bbs/View.do?cbIdx=310&bcIdx={bcIdx}`.

### `scrapers/g2b.py` — G2B Scraper

- Utilizes the Public Data Portal Open API (XML).
- Endpoint: `[https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc](https://apis.data.go.kr/1230000/ad/BidPublicInfoService/getBidPblancListInfoServc)`
- Parameters: `serviceKey`, `numOfRows=100`, `inqryBgnDt`/`inqryEndDt` (past 7 days), `inqryDiv=1`.
- Queries up to 10 pages = up to 1,000 items.
- Attachment URLs are parsed separately from the detailed HTML page.

### `scrapers/nia.py` — NIA Scraper

- Business Announcement List: `https://www.nia.or.kr/site/nia_kor/ex/bbs/List.do?cbIdx=78336`
- SSR page — collectable via `requests` without a headless browser.
- CSS Selectors: `ul li` / `a[onclick*='doBbsFView']`
- Detail Link: Extracts `bcIdx` from `doBbsFView('78336', '{bcIdx}', ...)` →
  `https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?cbIdx=78336&bcIdx={bcIdx}`
- Date parsed from `span.src` (e.g. `"2026.05.19조회 139"`); org from `span.writer`.
- Attachment files: `a[href*='/common/board/Download.do']`

### `scrapers/etri.py` — ETRI Scraper

- Electronic Bidding List: `https://ebid.etri.re.kr/ebid/ebid/nSsEbidbulletinListPopup.do`
- POST-based pagination (`pageNo`, `biNo`, `pageLine` parameters).
- Enabled via `etri: true` in `config.yaml`.

### `app/filters.py` — Keyword Filter

- Target Search Fields: `Announcement Title + Content Summary + Ordering Agency` (converted to lowercase before comparison).
- `keywords` (OR/AND): announcement passes if any keyword matches.
- `exclude_keywords`: announcement is excluded if any keyword matches — takes priority over `keywords`.
- Changing to `match_logic: AND` requires all keywords to match simultaneously.
- If both keywords and categories are left empty, all items pass.
- Per-site filter override: `sites.{site}.filters` in `config.yaml` is merged with global filters
  (e.g., G2B-specific `exclude_keywords: ["물품구매", "시설공사", ...]`).

### `app/downloader.py` — Attachment Downloader

- Allowed Extensions: `.pdf`, `.hwp`, `.hwpx`, `.docx`, `.xlsx`, `.zip`, `.pptx`
- Maximum File Size: 50MB
- Skips downloading if the file already exists.
- Extracts Korean filenames from the Content-Disposition header (handles both RFC 5987 and EUC-KR).
- Implements streaming download for memory efficiency with large files.
- Save Path: `output/attachments/{source_site}/{announcement_no}/filename`

### `app/excel_writer.py` — Excel Writer

- File: `output/announcements.xlsx` (Single cumulative file when `rolling_file: true`).
- Deduplication: Based on the combined `(Announcement No., Source Site)` key.
- Columns (12 total):
  `Announcement No.`, `Title`, `Ordering Agency`, `Source Site`, `Announcement Date`, `Closing Date/Time`,
  `Budget`, `Content Summary`, `No. of Attachments`, `Attachment Path`, `Announcement Link`, `Collected Date/Time`.
- Styling:
- Header: Blue background + White text.
- Rows closing within 7 days: Highlighted with an orange background.
- Announcement Link / Attachment Path: Clickable hyperlinks.

---

## 5. Output Artifacts

```
output/
├── announcements.xlsx         ← Cumulative Excel for collected announcements (Primary output)
└── attachments/
    ├── NIPA/
    │   └── {Announcement No.}/ ← Attached files for the respective announcement
    ├── 중소벤처기업부/ (MSS)
    │   └── {Announcement No.}/
    └── 나라장터/ (G2B)
        └── {Announcement No}/

logs/
└── scraper_YYYY-MM-DD.log     ← Execution logs (Daily)

```

---

## 6. Configuration (`app/config.yaml`)

| Field                             | Description                                                        |
| --------------------------------- | ------------------------------------------------------------------ |
| `sources.{site}: true/false`      | Activates/deactivates each site                                    |
| `filters.keywords`                | List of target keywords for collection                             |
| `filters.exclude_keywords`        | Exclude if any keyword matches (overrides `keywords`)              |
| `filters.match_logic`             | `OR` (Default) or `AND`                                            |
| `filters.categories`              | G2B business sector code filters (Empty collects all)              |
| `attachments.enabled`             | Enable/disable attachment downloading                              |
| `attachments.max_file_size_mb`    | Maximum file size for downloads (MB)                               |
| `output.rolling_file`             | `true`: Single cumulative file, `false`: Separate files by date    |
| `schedule.time`                   | Scheduled execution time (HH:MM)                                   |
| `api_keys.g2b_api_key`            | Public Data Portal API Key (Required for G2B collection)           |
| `sites.{site}.list_url`           | List page URL (update here when site is renewed, no code changes)  |
| `sites.{site}.filters`            | Site-specific filter override merged with global filters           |
| `request.delay_min/max`           | Range of delay between requests (Seconds)                          |

---

## 7. Execution Guide

```bash
# Execute immediately once (Manual run)
python app/main.py --once

# Automate daily at 08:00 (Server / Background operation)
python app/main.py --schedule

# Debug list page HTML (verify CSS selectors)
python app/main.py --debug-nipa
python app/main.py --debug-mss
python app/main.py --debug-nia
python app/main.py --debug-etri

# Debug detail page HTML (verify attachment selectors)
python app/main.py --debug-detail nia <announcement_url>
```

Installing dependencies:

```bash
pip install -r requirements.txt
```

---

## 8. Current Execution Results (As of 2026-05-19)

| Scraper | Status    | Remarks                                                     |
| ------- | --------- | ----------------------------------------------------------- |
| NIPA    | ✅ Normal | 10 items/page, max 5 pages                                  |
| MSS     | ✅ Normal | cbIdx=310 (announcement board); onclick-based URL           |
| G2B     | ✅ Normal | Past 7 days, max 1,000 items; API key required              |
| NIA     | ✅ Normal | SSR; onclick URL extraction; cbIdx=78336                    |
| ETRI    | ✅ Normal | POST pagination; enabled via `etri: true` in config         |

---

## 9. Extension Guide

To add a new public institution website:

1. Create a new file in `scrapers/` (Inherit from `BaseScraper` in `scrapers/base.py`).
2. Implement `fetch_list()` and `fetch_detail()`.
3. Export the class in `scrapers/__init__.py`.
4. Register the key-class pair in `_SCRAPER_MAP` inside `app/main.py`.
5. Add the new entry under `sources` in `app/config.yaml`.

```


```
