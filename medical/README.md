# Medical Sync

Runs on GitHub Actions every hour and files openly available medical data into Google Drive, sorted into eight data types and their sub-types. A daily job lists healthcare companies whose SEC filings mention these data types, with their next earnings call. After every run a counter records how many files and how much storage each type and sub-type holds.

Only **publicly downloadable** data is collected. Controlled-access or credentialed data (full MIMIC, GDC controlled genomics, restricted TCIA collections) and non-public patient data are not. If you obtain approved access to such a source yourself, it can be added with your own credentials.

## What goes where

```
Medical Data/
  DICOM - Imaging/   <specialty>/<CT | MRI | X-ray | Ultrasound>/<collection>/<series>/   DICOM files
  EHR/               Critical Care & Emergency (MIMIC-IV demo), Emergency (MIMIC-IV-ED demo),
                     Critical Care (eICU demo), Synthetic patient records (Synthea CSV and FHIR)
  Claims/            Medicare synthetic claims: Inpatient, Outpatient, Professional (carrier),
                     Pharmacy (prescription drug events), Beneficiary summary
  Wearables/         Continuous glucose monitors (Dexcom, Libre), Apple Watch, Wrist sensors
                     (Empatica E4), Heart rate monitors & actigraphy, Activity trackers
  Audio/             Primary care visits (PriMock57 mock consultations: audio, transcripts, notes)
  Genomics/          WES / WGS somatic mutations, Gene panels, Signaling & pathway data (RPPA),
                     Lab molecular data (gene expression, methylation, copy number), by disease area
  Pathology/         Whole-slide images and Pathology reports, by site: Dermatology, GI, Cervical &
                     endometrial, Prostate, Breast, Hematopathology, Thyroid, Other surgical resections
  Other/             Patient case reports (by specialty), Medical education cases,
                     Studies (New studies, Ongoing studies: record + protocol / SAP / consent PDFs)
  <type>/Company documents/<company>/   public documents from company websites, by type
Medical Sync - private/
  counter            files and storage per data type and sub-type (Google Sheet)
  progress           history of the totals, newest first (Google Sheet)
  company-leads      healthcare companies, data types their filings mention, next earnings call
```

Archives (DICOM series, PhysioNet projects, Synthea, claims) are **unpacked into folders**; no zips are stored. Each unpacked folder has a `_SOURCE.txt` with the source, licence and attribution, and every file's Drive description says the same.

| Type | Source | Licence |
|---|---|---|
| DICOM - Imaging | The Cancer Imaging Archive, public collections; CT, MRI, X-ray (incl. mammography) and ultrasound series | Per series, Creative Commons (recorded per file) |
| EHR | PhysioNet MIMIC-IV / MIMIC-IV-ED / eICU demo databases (real, de-identified); Synthea | ODbL; Apache-2.0 (synthetic) |
| Claims | CMS DE-SynPUF sample 1 | Public use file (synthetic) |
| Wearables | PhysioNet open projects | CC BY / ODC, checked on each project page |
| Audio | PriMock57 (role-played consultations, not real patients) | CC BY 4.0 |
| Genomics | NCI Genomic Data Commons, open tier only | GDC open access |
| Pathology | NCI GDC open slide images and pathology reports | GDC open access |
| Other | Europe PMC open-access case reports; ClinicalTrials.gov | Per article (recorded); public record |
| Company documents | Healthcare company websites (from `websites.sites` and the leads list); robots.txt respected | Copyright of the company |

Notes on what the data is:
- GDC slides are mostly surgical resection specimens, so pathology folders are named by site, not as "core biopsies". Cytology (Pap smears, FNA) is not in any open source used here.
- Real de-identified EHR beyond the demos, real claims, real consultation audio and raw WGS/WES reads are only available under credentialed access or data-use agreements.
- Non-commercial (NC) and no-derivatives (ND) licences are collected too and recorded per file: check a file's licence before using it commercially.

## Data counter

`src/progress.js` runs after every sync (or alone: **Actions > Medical sync > Run workflow > count_only**). It counts every file medical-sync put in Drive by its data type and sub-type, then:

- writes the **counter** sheet: one row per sub-type (files, storage, share of total storage), a TOTAL row per data type and an overall total;
- adds a row to the **progress** sheet (files and GB per data type), so growth can be followed;
- prints the same table in the run's summary.

## Running

- **Schedule**: collection hourly at :17, one parallel job per source; company leads daily at 02:40 UTC. Each job works up to 45 minutes; when a source has work left the next run starts straight away.
- **Re-runs**: every file carries a key from its source, so nothing is collected twice; an unpacked archive is finished when its `_SOURCE.txt` exists. Listings restart from the top every `rescanDays` (30) to pick up new material.
- **Drive space**: uploads stop when Drive is within `driveReserveMB` (2 GB) of full.
- **Manual run**: **Actions > Medical sync > Run workflow**, optionally one source and/or **dry run**.
- **Locally**: `npm install`, then `SOURCE=gdc DRY_RUN=true node src/index.js` lists what one source would collect (first 25 items; `DRY_RUN_LIMIT` changes that).

## Secrets

| Secret | Value |
|---|---|
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REFRESH_TOKEN` | OAuth client (Desktop app) and a refresh token with the `drive.file` scope; the same ones earnings-sync uses work |
| `SEC_USER_AGENT` | Your name and e-mail, e.g. `Jane Doe jane@example.com`; the SEC blocks requests without one |
| `GOOGLE_SERVICE_ACCOUNT_JSON`, `DRIVE_ROOT_FOLDER_ID` | Optional, instead of OAuth: a service account and a Shared Drive folder |

## Configuration (`medical.json`)

Each source has its own section: the case-report searches (`europepmc.queries`), study statuses (`ctgov.queries`), TCIA collections and licence pattern (`tcia`), GDC data types (`gdc.groups`), PhysioNet projects with their type and folder (`physionet.projects`), GitHub datasets (`github.datasets`), fixed downloads (`files.items`), SEC search phrases per type (`leads.phrases`) and extra company websites (`websites.sites`: `{ "name": "...", "startUrls": ["https://..."] }`). Set `"enabled": false` on a section to turn it off.
