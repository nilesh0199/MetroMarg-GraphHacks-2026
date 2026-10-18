# Data sources and attribution

## Metro timetable

- **Source:** DMRC static GTFS feed from **Delhi Open Transit Data (OTD)**, https://otd.delhi.gov.in/data/staticDMRC/
- **Owner and operator:** Department of Transport, GNCTD, with IIIT-Delhi (as stated on the portal).
- **Version:** the portal lists the data as last updated on 10 August 2023 (262 stops, 36 routes, 17,997 trips, 411,686 stop times).
- **File in this repository:** `dmrc_gtfs.zip`, exactly as downloaded. It has not been modified. The graph is built from it by `import_gtfs.py`.
- **Terms:** https://otd.delhi.gov.in/terms

### How this project relates to the terms

Our reading of the terms, which is not legal advice:

- Downloading static data asks the user to state their intended use. This project is a non-commercial hackathon entry.
- Clause 22 says material on the portal may be reproduced free of charge if it is reproduced accurately, is not used in a derogatory or misleading context, and the source is prominently acknowledged. This is why the file is included unchanged and acknowledged at the top of the README and on the web page.
- Clause 7 says the contents must not be modified, so the original file is kept untouched and everything else is derived from it.
- The project does not track or profile individuals (clause 8).
- The data is provided "as is". It is from 2023 and does not include newer stations. This project is **not endorsed by DMRC or the Department of Transport**.

If the portal's owners ask for the file to be removed, remove it and point to the portal link instead.

## Closure event (9 to 10 October 2026)

Taken from press reports of DMRC's announcement. The project records only what these sources state:

- Business Today, DMRC's revised update: https://www.businesstoday.in/india/story/dmrc-issues-revised-metro-closure-update-ahead-of-oct-10-check-affected-stations-560777-2026-10-09
- News On AIR, the Delhi Police proposal for 57 stations: https://newsonair.gov.in/delhi-police-proposes-closure-of-entry-and-exit-gates-at-57-metro-stations-from-9-pm/

## Other

- Jantar Mantar's coordinates are approximate and set in `import_gtfs.py`.
- Walking times are estimates computed from straight-line distance.
