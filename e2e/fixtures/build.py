"""Build a deterministic fixture for the Playwright suite: invented data rooms and a fresh database.

    python e2e/fixtures/build.py <workspace>     # prints the data root, then the DATABASE_URL

Writes a synthetic data root with invented funds under <workspace>, and rebuilds the `rwp_e2e`
database on the local test Postgres (TEST_DATABASE_URL, default the local Supabase stack) from
supabase/migrations, so it starts with the shipped gates and policy. It then runs the real catalog and
screening pipeline over the rooms with scripted extractor and judge stubs, so every view renders
genuine run output without API keys, network calls, or real fund documents. Tests may edit gates
freely: nothing outside the workspace and the rwp_e2e database is touched.
"""

import json
import os
import shutil
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import psycopg

REPO = Path(__file__).resolve().parents[2]

# ---------- synthetic data rooms ----------
# Each room: folder name, stage folder, and pages {file: [page text, ...]}. Quotes used by the
# scripted extractor below must appear verbatim on the cited page, or verify will reject them.

ROOMS: dict[str, dict] = {
    "Northwind Capital - Private Credit Fund I": {
        "stage": "1-Intake",
        "files": {
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf": [
                "NORTHWIND PRIVATE CREDIT FUND I\nPrivate Placement Memorandum\nTable of Contents\n"
                "Summary of Terms 2\nService Providers 3",
                "Summary of Terms\nEligible investors: accredited investors as defined in Regulation D.\n"
                "The minimum investment is $250,000.\nManagement fee: 1.25% per annum of NAV.\n"
                "Incentive fee: 12.5% of net income over a 6% hurdle.\nServicing fee: 0.50% per annum.",
                "Service Providers\nAdministrator: Harbor Fund Services LLC, an independent administrator.\n"
                "Auditor: Ledger & Lane LLP, independent auditor.\n"
                "The Fund maintains a written valuation policy approved by the board.",
            ],
            "02 Performance/Northwind Track Record Q2 2026.pdf": [
                "Track Record\nPredecessor fund net IRR of 9.8% since inception, net of all fees and expenses.",
            ],
        },
    },
    "Acme Partners - Real Estate Opportunity Fund II": {
        "stage": "1-Intake",
        "files": {
            "Acme REOF II - Term Sheet.pdf": [
                "ACME REAL ESTATE OPPORTUNITY FUND II\nSummary of Terms\n"
                "Investors: qualified purchasers only, under Section 3(c)(7).\n"
                "Minimum commitment: $5,000,000.\nManagement fee: 2.0% of committed capital.\n"
                "Carried interest: 20% over an 8% preferred return.\nFund expenses capped at 1.5% per annum.\n"
                "Target fund size: $250 million.",
            ],
            "Acme REOF II - Investor Deck.pdf": [
                "Acme Partners\nInvestor Presentation\nGross returns on prior deals averaged 18%.\n"
                "Management fee of 1.75% on committed capital.\nTargeting a $400 million fund.",
            ],
        },
    },
    "Bluefield Advisors - Infrastructure Income Fund": {
        "stage": "2-Managers",
        "files": {
            "Bluefield Infrastructure Income - DDQ.pdf": [
                "Due Diligence Questionnaire\nThe fund is open to accredited investors.\n"
                "The minimum investment is $50,000.\nAdministrator: Cobalt Admin Services.",
            ],
        },
    },
    # Screened, with no gate waiting on review: recipes confirm its disposition without moving the
    # review counts other recipes check.
    "Delta Ridge Partners - Evergreen Credit Fund": {
        "stage": "2-Managers",
        "files": {
            "Delta Ridge Evergreen - Fact Sheet.pdf": [
                "Delta Ridge Evergreen Credit Fund\nOpen to accredited investors.\nMinimum investment: $25,000.",
            ],
        },
    },
}

PIPELINE_MD = """# RWP Alternatives Pipeline

Last updated: 2026-10-01

## Active

| Manager | Strategy | Status | Owner | Last action | Next action |
|---|---|---|---|---|---|
| Northwind Capital | Private Credit Fund I | **Under review** | Analyst A | Screened 2026-09-30 | Confirm hurdle |
| Acme Partners | Real Estate Opportunity Fund II | **Triaged** | Analyst B | Extraction complete 2026-09-28 | Screen |
| Bluefield Advisors | Infrastructure Income Fund | **Covered** | Analyst A | IC approved 2026-09-15 | Annual review |
| Delta Ridge Partners | Evergreen Credit Fund | **Triaged** | Analyst B | Fact sheet received 2026-10-02 | Screen |
"""

# field -> (file, page, quote, value), or a list of them. Quotes are verbatim from the pages above.
FACTS: dict[str, dict[str, tuple[str, int, str, str] | list[tuple[str, int, str, str]]]] = {
    "Northwind Capital - Private Credit Fund I": {
        "investor_standard": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            2,
            "accredited investors as defined in Regulation D",
            "accredited investors",
        ),
        "minimum_investment": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            2,
            "The minimum investment is $250,000.",
            "$250,000",
        ),
        "management_fee": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            2,
            "Management fee: 1.25% per annum of NAV.",
            "1.25%",
        ),
        "servicing_fee": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            2,
            "Servicing fee: 0.50% per annum.",
            "0.50%",
        ),
        "incentive_fee": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            2,
            "Incentive fee: 12.5% of net income over a 6% hurdle.",
            "12.5% over 6% hurdle",
        ),
        "administrator": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            3,
            "Administrator: Harbor Fund Services LLC, an independent administrator.",
            "Harbor Fund Services",
        ),
        "auditor": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            3,
            "Auditor: Ledger & Lane LLP, independent auditor.",
            "Ledger & Lane LLP",
        ),
        "valuation_policy": (
            "01 Offering/Northwind Private Credit Fund I - PPM.pdf",
            3,
            "The Fund maintains a written valuation policy approved by the board.",
            "written policy",
        ),
        "net_return": (
            "02 Performance/Northwind Track Record Q2 2026.pdf",
            1,
            "net IRR of 9.8% since inception, net of all fees and expenses",
            "9.8% net IRR",
        ),
    },
    "Delta Ridge Partners - Evergreen Credit Fund": {
        "investor_standard": (
            "Delta Ridge Evergreen - Fact Sheet.pdf",
            1,
            "Open to accredited investors.",
            "accredited investors",
        ),
        "minimum_investment": ("Delta Ridge Evergreen - Fact Sheet.pdf", 1, "Minimum investment: $25,000.", "$25,000"),
    },
    "Acme Partners - Real Estate Opportunity Fund II": {
        "investor_standard": (
            "Acme REOF II - Term Sheet.pdf",
            1,
            "Investors: qualified purchasers only, under Section 3(c)(7).",
            "qualified purchasers only",
        ),
        "minimum_investment": ("Acme REOF II - Term Sheet.pdf", 1, "Minimum commitment: $5,000,000.", "$5,000,000"),
        "exemption": ("Acme REOF II - Term Sheet.pdf", 1, "Section 3(c)(7)", "3(c)(7)"),
        # The deck and the term sheet disagree on the fee, so the cost gate stays open (decisions B6, F3).
        "management_fee": [
            ("Acme REOF II - Term Sheet.pdf", 1, "Management fee: 2.0% of committed capital.", "2.0%"),
            ("Acme REOF II - Investor Deck.pdf", 1, "Management fee of 1.75% on committed capital.", "1.75%"),
        ],
        "fund_expenses": ("Acme REOF II - Term Sheet.pdf", 1, "Fund expenses capped at 1.5% per annum.", "1.5%"),
        "incentive_fee": (
            "Acme REOF II - Term Sheet.pdf",
            1,
            "Carried interest: 20% over an 8% preferred return.",
            "20% over 8%",
        ),
        "gross_return": (
            "Acme REOF II - Investor Deck.pdf",
            1,
            "Gross returns on prior deals averaged 18%.",
            "18% gross",
        ),
    },
}


def sources(entry):
    """A FACTS entry is one source or a list of them."""
    return entry if isinstance(entry, list) else [entry]


# A fabricated quote on every gate, so the "rejected, quote not on cited page" path is exercised.
HALLUCINATED = "This sentence does not appear anywhere in the data room."


def tiny_pdf(pages):
    """A valid PDF with one page per entry in `pages`, so pdf.js can render it and citations to
    page N land on a real page N."""
    font = 3 + 2 * len(pages)  # object number of the shared font
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids ["
        + b" ".join(f"{3 + 2 * i} 0 R".encode() for i in range(len(pages)))
        + b"] /Count "
        + str(len(pages)).encode()
        + b" >>",
    ]
    for i, text in enumerate(pages):
        lines = "\n".join(
            f"({ln.replace('\\', '').replace('(', '[').replace(')', ']')}) Tj T*" for ln in text.splitlines()
        )
        stream = f"BT /F1 11 Tf 14 TL 50 740 Td\n{lines}\nET".encode()
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {4 + 2 * i} 0 R "
            f"/Resources << /Font << /F1 {font} 0 R >> >> >>".encode()
        )
        objs.append(b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream")
    objs.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def write_rooms(data_root):
    data_root.mkdir(parents=True, exist_ok=True)
    (data_root / "PIPELINE.md").write_text(PIPELINE_MD)
    folders = []
    for name, room in ROOMS.items():
        folder = data_root / room["stage"] / name
        index = []
        for rel, pages in room["files"].items():
            pdf = folder / rel
            pdf.parent.mkdir(parents=True, exist_ok=True)
            pdf.write_bytes(tiny_pdf(pages))
            for i, text in enumerate(pages, 1):
                index.append({"file": rel, "page": i, "chars": len(text), "text": text})
        (folder / "_index").mkdir(parents=True, exist_ok=True)
        (folder / "_index" / "pages.jsonl").write_text("".join(json.dumps(p) + "\n" for p in index))
        folders.append(folder)
    return folders


# ---------- scripted model stubs ----------


def install_stubs():
    from sg import consistency, extractors, judges, llm

    def extractor(gate, room, pages):
        t0 = time.time()
        table = FACTS.get(room.name, {})
        facts = [
            {"field": f["name"], "value": value, "file": file, "page": page, "quote": quote}
            for f in gate["extractor"]["fields"]
            if f["name"] in table
            for file, page, quote, value in sources(table[f["name"]])
        ]
        first = gate["extractor"]["fields"][0]["name"]
        facts.append(
            {
                "field": first,
                "value": "?",
                "file": next(iter(ROOMS[room.name]["files"])),
                "page": 1,
                "quote": HALLUCINATED,
            }
        )
        llm.record(
            "fixture",
            "scripted-extractor",
            t0,
            usage={"input_tokens": 1200, "output_tokens": 180},
            output={"facts": facts},
            input_chars=sum(len(p["text"]) for p in pages),
        )
        return facts

    def marketing(room, catalog):
        """Acme's deck and term sheet disagree on the fund size."""
        if not room.name.startswith("Acme"):
            return []
        return [
            {
                "topic": "Target fund size",
                "summary": "The deck targets $400 million; the term sheet says $250 million.",
                "marketing": {
                    "file": "Acme REOF II - Investor Deck.pdf",
                    "page": 1,
                    "quote": "Targeting a $400 million fund.",
                },
                "filed": {
                    "file": "Acme REOF II - Term Sheet.pdf",
                    "page": 1,
                    "quote": "Target fund size: $250 million.",
                },
            }
        ]

    def judge(gate, brief, questions):
        t0 = time.time()
        have = {f["field"] for f in brief["facts"]}
        answers = {}
        for q in questions:
            if q["type"] == "bool":
                yes = {
                    "sufficient": len(have) >= (1 if gate["id"] == "track_record" else 2),
                    "qp_only": any("qualified purchasers only" in f["quote"] for f in brief["facts"]),
                    "has_valuation_policy": "valuation_policy" in have,
                    "fund_level": "net_return" in have,
                }.get(q["id"], False)
                # Track record on Northwind is deliberately borderline, so one gate needs analyst review.
                p = 0.72 if gate["id"] == "track_record" and yes else (0.92 if yes else 0.08)
                answers[q["id"]] = {"true": p, "false": round(1 - p, 2)}
            else:
                pick = "net" if "net_return" in have else "gross" if "gross_return" in have else q["options"][-1]
                answers[q["id"]] = {
                    o: (0.9 if o == pick else round(0.1 / (len(q["options"]) - 1), 3)) for o in q["options"]
                }
        llm.record("fixture", "scripted-judge", t0, usage={"input_tokens": 600, "output_tokens": 40}, output=answers)
        return answers

    extractors.EXTRACTORS["fixture"] = extractor
    consistency.MARKETING_CHECK["fixture"] = marketing
    judges.JUDGES["fixture"] = judge


def fresh_database(name="rwp_e2e"):
    """Drop and recreate `name` on the local test server, apply every migration, return its URL."""
    admin = os.environ.get("TEST_DATABASE_URL", "postgresql://postgres:postgres@127.0.0.1:54322/postgres")
    parts = urlsplit(admin)
    if parts.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit(f"TEST_DATABASE_URL points at {parts.hostname}; the e2e fixture only uses a local Postgres")
    with psycopg.connect(admin, autocommit=True) as a:
        a.execute(f'drop database if exists "{name}" with (force)')
        a.execute(f'create database "{name}"')
    url = urlunsplit(parts._replace(path=f"/{name}"))
    with psycopg.connect(url, autocommit=True) as c:
        for m in sorted((REPO / "supabase" / "migrations").glob("*.sql")):
            c.execute(m.read_text())
    return url


def main(workspace):
    ws = Path(workspace).resolve()
    if ws.exists():
        shutil.rmtree(ws)
    ws.mkdir(parents=True)
    data_root = ws / "data"
    folders = write_rooms(data_root)
    os.environ["DATABASE_URL"] = url = fresh_database()

    sys.path.insert(0, str(REPO))
    from sg import store
    from sg.catalog import build as build_catalog
    from sg.pipeline import run

    install_stubs()
    # Northwind was filed long before its screen, so the clock shows a late screen.
    store.save_intake(
        "Northwind_Capital_-_Private_Credit_Fund_I",
        {"referred_by": "Adviser network", "owner": "Analyst A", "filed_on": "2026-09-01", "share_class": "Class I"},
    )
    for folder in folders:
        build_catalog(folder)
    # Bluefield stays unscreened, so the "Not screened" state is covered too.
    for folder in [f for f in folders if not f.name.startswith("Bluefield")]:
        run(folder, "fixture", "fixture")
        time.sleep(1.1)  # runs are stamped to the second
    print(data_root)
    print(url)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else REPO / "e2e" / ".workspace")
