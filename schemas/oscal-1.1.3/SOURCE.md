# Vendored NIST OSCAL 1.1.3 JSON schemas

These files are copied unmodified from the official NIST OSCAL v1.1.3 release.
Do not edit them. To update, download the new release assets and update this file,
the checksums below, and `OSCAL_VERSION` (a deliberate, reviewed change).

| File | Source URL | SHA-256 |
|------|------------|---------|
| `oscal_catalog_schema.json` | https://github.com/usnistgov/OSCAL/releases/download/v1.1.3/oscal_catalog_schema.json | `5e120afbd14c480a9498ab6388857ef32b3b880e458525e966ff7c7f59333d90` |
| `oscal_poam_schema.json` | https://github.com/usnistgov/OSCAL/releases/download/v1.1.3/oscal_poam_schema.json | `e404043fef9cc6108c0e895932f513043d54f28457b4eb02e74dc0cff1215e16` |
| `oscal_profile_schema.json` | https://github.com/usnistgov/OSCAL/releases/download/v1.1.3/oscal_profile_schema.json | `d14c99b4bc48cb1ef370cd27a78c23e04bab847e737e11f478b37714db30851b` |
| `oscal_assessment-results_schema.json` | https://github.com/usnistgov/OSCAL/releases/download/v1.1.3/oscal_assessment-results_schema.json | `d9e34757f0c12aff61f52b821f0b8f83ba0ba75b3a149a202b08ba82f82bc4c3` |

- Downloaded: 2026-11-26
- `oscal_poam_schema.json` added 2026-11-27 (Milestone 3), `$id` `http://csrc.nist.gov/ns/oscal/1.1.3/oscal-poam-schema.json`.
- `oscal_assessment-results_schema.json` added 2026-11-27 (Milestone 5), `$id` `http://csrc.nist.gov/ns/oscal/1.1.3/oscal-ar-schema.json`.
- Schema `$id`s: `http://csrc.nist.gov/ns/oscal/1.1.3/oscal-catalog-schema.json` and
  `http://csrc.nist.gov/ns/oscal/1.1.3/oscal-profile-schema.json` (JSON Schema draft-07)
- License: NIST OSCAL is a work of the US government, in the public domain in the US
  (see https://github.com/usnistgov/OSCAL/blob/main/LICENSE.md).
- `shared/tests/test_oscal_schema.py` checks these hashes, so any edit fails the tests.
