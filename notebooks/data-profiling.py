"""
Stage 2 — Profile every Excel file in data/raw/

Reads every sheet in every Excel file, generates a ydata-profiling HTML report,
and writes the reports to data/interim/profiles/.

Run from the project root:
    python notebooks/01-data-profiling.py
"""

from pathlib import Path
import pandas as pd
from ydata_profiling import ProfileReport

# ----- Paths -----
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
OUT_DIR = PROJECT_ROOT / "data" / "interim" / "profiles"
OUT_DIR.mkdir(parents=True, exist_ok=True)

# ----- Helpers -----
def safe_name(s: str) -> str:
    """Make a string filesystem-safe."""
    return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in s)

def profile_file(xlsx_path: Path) -> None:
    """Profile every sheet in a single Excel file."""
    file_stem = safe_name(xlsx_path.stem)
    print(f"\n=== {xlsx_path.name} ===")

    # Read all sheets into a dict of DataFrames
    try:
        all_sheets = pd.read_excel(xlsx_path, sheet_name=None, engine="openpyxl")
    except Exception as e:
        print(f"  ! Could not read file: {e}")
        return

    for sheet_name, df in all_sheets.items():
        rows, cols = df.shape
        print(f"  - sheet '{sheet_name}': {rows} rows, {cols} cols")

        if rows == 0:
            print(f"    (skipped — sheet is empty)")
            continue

        out_name = f"{file_stem}__{safe_name(sheet_name)}.html"
        out_path = OUT_DIR / out_name

        report = ProfileReport(
            df,
            title=f"{xlsx_path.name} — {sheet_name}",
            minimal=True,   # faster; full mode is slow on wide data
            explorative=False,
        )
        report.to_file(out_path)
        print(f"    -> {out_path.relative_to(PROJECT_ROOT)}")

# ----- Main -----
def main() -> None:
    xlsx_files = sorted(RAW_DIR.glob("*.xlsx")) + sorted(RAW_DIR.glob("*.xls"))

    if not xlsx_files:
        print(f"No Excel files found in {RAW_DIR}")
        print("Copy your .xlsx files into data/raw/ first.")
        return

    print(f"Found {len(xlsx_files)} Excel file(s) in {RAW_DIR.relative_to(PROJECT_ROOT)}")

    for xlsx in xlsx_files:
        profile_file(xlsx)

    print(f"\nDone. Reports are in {OUT_DIR.relative_to(PROJECT_ROOT)}/")
    print("Next: open each HTML report in your browser and read carefully.")

if __name__ == "__main__":
    main()