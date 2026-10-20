# Census Places gazetteer

`2025_Gaz_place_national.zip` is the vendored 2025 U.S. Census Bureau national
Places Gazetteer used by Architecture V2 Phase 4. Runtime geocoding is local and
deterministic; it does not call an API or an LLM.

- Source: <https://www2.census.gov/geo/docs/maps-data/data/gazetteer/2025_Gazetteer/2025_Gaz_place_national.zip>
- Census release year: 2025
- SHA-256: `49644173a453469d9bd77fb7a493b027f87567e209edaf2078aac7543ac2ee29`
- Jurisdictions used: the 50 states and District of Columbia; Puerto Rico rows
  in the national file are intentionally excluded.

The loader verifies the archive checksum and required columns before exposing
any rows.
