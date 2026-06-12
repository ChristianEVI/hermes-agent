#!/usr/bin/env python3
"""
seq_liability_scan.py — In-silico developability & sequence-liability scan for
therapeutic antibody chains (VH/VL or full HC/LC).

Pure Python standard library only — no RDKit, no Biopython. All physicochemical
scales are published constants embedded below, so the scan is fully reproducible
(ALCOA+ friendly) and can run over an entire catalogue with zero wet-lab work.

Usage:
    python3 seq_liability_scan.py --vh <VH_SEQ> --vl <VL_SEQ> --name "mAb-123"
    python3 seq_liability_scan.py --fasta chains.fasta --name "mAb-123"
    echo ">VH\nEVQL..." | python3 seq_liability_scan.py --fasta -

Output: structured JSON on stdout (one record per chain + an aggregated record).

Method version is stamped into the output for traceability.
"""
import sys
import re
import json
import argparse

METHOD_VERSION = "hermes-insilico/1.0.0"

# --- Average residue masses (Da), monoisotopic-independent average values ------
RESIDUE_MASS = {
    "A": 71.0788, "R": 156.1875, "N": 114.1038, "D": 115.0886, "C": 103.1388,
    "E": 129.1155, "Q": 128.1307, "G": 57.0519, "H": 137.1411, "I": 113.1594,
    "L": 113.1594, "K": 128.1741, "M": 131.1926, "F": 147.1766, "P": 97.1167,
    "S": 87.0782, "T": 101.1051, "W": 186.2132, "Y": 163.1760, "V": 99.1326,
}
WATER = 18.01524

# --- Kyte & Doolittle hydropathy scale (for GRAVY) -----------------------------
KD_HYDROPATHY = {
    "A": 1.8, "R": -4.5, "N": -3.5, "D": -3.5, "C": 2.5, "Q": -3.5, "E": -3.5,
    "G": -0.4, "H": -3.2, "I": 4.5, "L": 3.8, "K": -3.9, "M": 1.9, "F": 2.8,
    "P": -1.6, "S": -0.8, "T": -0.7, "W": -0.9, "Y": -1.3, "V": 4.2,
}

# --- EMBOSS pKa values for pI / net-charge calculation -------------------------
PKA = {"D": 3.9, "E": 4.1, "C": 8.5, "Y": 10.1, "H": 6.5, "K": 10.8, "R": 12.5}
PKA_NTERM = 8.6
PKA_CTERM = 3.6
NEG_RESIDUES = ("D", "E", "C", "Y")   # acidic — deprotonation gives negative charge
POS_RESIDUES = ("K", "R", "H")        # basic — protonation gives positive charge

# --- Molar extinction coefficients at 280 nm (Pace et al. 1995) ----------------
E_TRP = 5500
E_TYR = 1490
E_CYSTINE = 125

VALID_AA = set(RESIDUE_MASS.keys())

# --- Sequence-liability motifs (CDR-priority hotspots) -------------------------
# Each: (key, label, compiled regex, severity, note)
LIABILITY_MOTIFS = [
    ("deamidation", "Asn deamidation (NG/NS/NT/NH/NN)", re.compile(r"N[GSTHN]"),
     "high", "Chemical degradation hotspot; rate highest for NG."),
    ("isomerization", "Asp isomerization (DG/DS/DT/DH/DD)", re.compile(r"D[GSTHD]"),
     "high", "Iso-Asp formation; potency/stability risk."),
    ("n_glycosylation", "N-glycosylation sequon (N-X-S/T, X!=P)", re.compile(r"N[^P][ST]"),
     "medium", "Potential occupancy / heterogeneity."),
    ("lysine_glycation", "Lys glycation (KE/KD)", re.compile(r"K[ED]"),
     "low", "Non-enzymatic glycation propensity."),
]
RE_NTERM_PYROGLU = re.compile(r"^[QE]")


def clean_sequence(seq):
    """Uppercase, strip whitespace/numbers, keep only valid 1-letter AA codes."""
    s = re.sub(r"[^A-Za-z]", "", seq).upper()
    invalid = sorted(set(s) - VALID_AA)
    s = "".join(c for c in s if c in VALID_AA)
    return s, invalid


def molecular_weight(seq):
    return round(sum(RESIDUE_MASS[a] for a in seq) + WATER, 2) if seq else 0.0


def gravy(seq):
    return round(sum(KD_HYDROPATHY[a] for a in seq) / len(seq), 4) if seq else 0.0


def net_charge_at_ph(seq, ph):
    """Net charge using Henderson-Hasselbalch over ionisable groups + termini."""
    pos = 1.0 / (1.0 + 10 ** (ph - PKA_NTERM))   # N-terminus
    for r in POS_RESIDUES:
        n = seq.count(r)
        if n:
            pos += n * (1.0 / (1.0 + 10 ** (ph - PKA[r])))
    neg = 1.0 / (1.0 + 10 ** (PKA_CTERM - ph))    # C-terminus
    for r in NEG_RESIDUES:
        n = seq.count(r)
        if n:
            neg += n * (1.0 / (1.0 + 10 ** (PKA[r] - ph)))
    return pos - neg


def isoelectric_point(seq):
    """Bisection for the pH where net charge == 0."""
    if not seq:
        return 0.0
    lo, hi = 0.0, 14.0
    for _ in range(100):
        mid = (lo + hi) / 2.0
        if net_charge_at_ph(seq, mid) > 0:
            lo = mid
        else:
            hi = mid
    return round((lo + hi) / 2.0, 2)


def extinction_coefficient(seq):
    """E(280) in M^-1 cm^-1. Reports both reduced and oxidised (cystine) forms."""
    n_trp, n_tyr, n_cys = seq.count("W"), seq.count("Y"), seq.count("C")
    e_reduced = n_trp * E_TRP + n_tyr * E_TYR
    e_cystine = e_reduced + (n_cys // 2) * E_CYSTINE
    mw = molecular_weight(seq)
    return {
        "e280_reduced": e_reduced,
        "e280_cystines": e_cystine,
        "a280_0.1pct_reduced": round(e_reduced / mw, 3) if mw else 0.0,
        "a280_0.1pct_cystines": round(e_cystine / mw, 3) if mw else 0.0,
    }


def find_motifs(seq, cdr_ranges=None):
    """Locate liability motifs. Overlapping matches found via lookahead."""
    hits = []
    for key, label, rx, severity, note in LIABILITY_MOTIFS:
        # use finditer with overlapping support
        pattern = re.compile(f"(?=({rx.pattern}))")
        for m in pattern.finditer(seq):
            pos = m.start()
            hits.append({
                "type": key, "label": label, "motif": m.group(1),
                "position": pos + 1,  # 1-based
                "severity": severity, "note": note,
                "in_cdr": _in_cdr(pos + 1, cdr_ranges),
            })
    # Oxidation-prone single residues (Met, Trp)
    for res, key, sev in (("M", "met_oxidation", "medium"), ("W", "trp_oxidation", "medium")):
        for i, a in enumerate(seq):
            if a == res:
                hits.append({
                    "type": key, "label": f"{res} oxidation", "motif": res,
                    "position": i + 1, "severity": sev,
                    "note": "Oxidation-prone residue (esp. solvent-exposed / CDR).",
                    "in_cdr": _in_cdr(i + 1, cdr_ranges),
                })
    # N-terminal pyroglutamate
    if RE_NTERM_PYROGLU.match(seq):
        hits.append({
            "type": "n_term_pyroglu", "label": "N-terminal pyroglutamate (Q/E)",
            "motif": seq[0], "position": 1, "severity": "low",
            "note": "Charge-variant / heterogeneity at N-terminus.",
            "in_cdr": False,
        })
    hits.sort(key=lambda h: h["position"])
    return hits


def _in_cdr(pos1, cdr_ranges):
    if not cdr_ranges:
        return None  # unknown without numbering
    return any(start <= pos1 <= end for (start, end) in cdr_ranges)


def free_cysteine_flag(seq):
    n = seq.count("C")
    return {"cys_count": n, "odd_unpaired_cys": (n % 2 == 1)}


def scan_sequence(seq, name="chain", cdr_ranges=None):
    """Scan a single chain. Returns a structured dict (importable for tests)."""
    seq, invalid = clean_sequence(seq)
    motifs = find_motifs(seq, cdr_ranges)
    cys = free_cysteine_flag(seq)
    ext = extinction_coefficient(seq)
    high = sum(1 for m in motifs if m["severity"] == "high")
    return {
        "name": name,
        "length": len(seq),
        "molecular_weight_da": molecular_weight(seq),
        "isoelectric_point": isoelectric_point(seq),
        "net_charge_ph7.4": round(net_charge_at_ph(seq, 7.4), 2),
        "gravy_hydropathy": gravy(seq),
        "aromatic_fraction": round(
            sum(seq.count(a) for a in "FWY") / len(seq), 4) if seq else 0.0,
        "extinction": ext,
        "cysteine": cys,
        "liabilities": motifs,
        "liability_count": len(motifs),
        "high_severity_count": high,
        "developability_flags": _developability_flags(seq, motifs, cys),
        "invalid_chars_ignored": invalid,
        "method_version": METHOD_VERSION,
    }


def _developability_flags(seq, motifs, cys):
    """TAP-/Jain-oriented heuristic flags (sequence-derivable subset only)."""
    flags = []
    if cys["odd_unpaired_cys"]:
        flags.append("unpaired_cysteine")
    if sum(1 for m in motifs if m["severity"] == "high") >= 4:
        flags.append("high_chemical_liability_load")
    if any(m["type"] == "n_glycosylation" for m in motifs):
        flags.append("n_glycosylation_site_present")
    gv = gravy(seq)
    if gv > 0.0:
        flags.append("elevated_hydrophobicity")
    return flags


def parse_fasta(text):
    """Minimal FASTA parser → list of (header, seq)."""
    records, header, buf = [], None, []
    for line in text.splitlines():
        line = line.strip()
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(buf)))
            header, buf = line[1:].strip() or "chain", []
        elif line:
            buf.append(line)
    if header is not None:
        records.append((header, "".join(buf)))
    return records


def aggregate(chain_records, name):
    """Build an antibody-level aggregate from the per-chain records."""
    all_seq_len = sum(c["length"] for c in chain_records)
    total_liab = sum(c["liability_count"] for c in chain_records)
    total_high = sum(c["high_severity_count"] for c in chain_records)
    total_mw = round(sum(c["molecular_weight_da"] for c in chain_records), 2)
    all_flags = sorted({f for c in chain_records for f in c["developability_flags"]})
    return {
        "name": name,
        "chains": [c["name"] for c in chain_records],
        "total_length": all_seq_len,
        "total_fv_mw_da": total_mw,
        "total_liability_count": total_liab,
        "total_high_severity_count": total_high,
        "developability_flags": all_flags,
        "verdict": _verdict(total_high, all_flags),
        "method_version": METHOD_VERSION,
    }


def _verdict(total_high, flags):
    if "unpaired_cysteine" in flags or total_high >= 6:
        return "ELEVATED_RISK"
    if total_high >= 3 or flags:
        return "MODERATE_RISK"
    return "LOW_RISK"


def _parse_cdr_arg(val):
    """Parse '27-38,56-65' → [(27,38),(56,65)]."""
    if not val:
        return None
    out = []
    for part in val.split(","):
        a, b = part.split("-")
        out.append((int(a), int(b)))
    return out


def main():
    ap = argparse.ArgumentParser(description="In-silico antibody developability scan")
    ap.add_argument("--name", default="antibody", help="Molecule name / ERP ref")
    ap.add_argument("--vh", help="VH (heavy-chain variable) sequence")
    ap.add_argument("--vl", help="VL (light-chain variable) sequence")
    ap.add_argument("--hc", help="Full heavy-chain sequence")
    ap.add_argument("--lc", help="Full light-chain sequence")
    ap.add_argument("--fasta", help="FASTA file path, or '-' for stdin")
    ap.add_argument("--cdr-vh", help="VH CDR ranges, e.g. '27-38,56-65,105-117'")
    ap.add_argument("--cdr-vl", help="VL CDR ranges, e.g. '24-34,50-56,89-97'")
    args = ap.parse_args()

    chains = []  # (label, seq, cdr_ranges)
    if args.fasta:
        text = sys.stdin.read() if args.fasta == "-" else open(args.fasta).read()
        for header, seq in parse_fasta(text):
            chains.append((header, seq, None))
    for label, seq, cdr in (
        ("VH", args.vh, _parse_cdr_arg(args.cdr_vh)),
        ("VL", args.vl, _parse_cdr_arg(args.cdr_vl)),
        ("HC", args.hc, None),
        ("LC", args.lc, None),
    ):
        if seq:
            chains.append((label, seq, cdr))

    if not chains:
        ap.error("No sequence provided. Use --vh/--vl, --hc/--lc, or --fasta.")

    chain_records = [scan_sequence(seq, label, cdr) for (label, seq, cdr) in chains]
    result = {
        "molecule": args.name,
        "modality": "antibody",
        "status": "RUO",
        "method_version": METHOD_VERSION,
        "chains": chain_records,
        "aggregate": aggregate(chain_records, args.name),
    }
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
