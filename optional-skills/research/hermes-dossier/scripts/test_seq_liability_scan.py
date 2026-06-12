"""Smoke tests for the in-silico antibody developability scan.

Run with: pytest optional-skills/research/hermes-dossier/scripts/test_seq_liability_scan.py
Stdlib + pytest only; no external bio dependencies.
"""
import importlib.util
import os

_here = os.path.dirname(__file__)
_spec = importlib.util.spec_from_file_location(
    "seq_liability_scan", os.path.join(_here, "seq_liability_scan.py"))
scan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(scan)

# Trastuzumab VH (public sequence) — has well-documented liabilities.
TRAS_VH = ("EVQLVESGGGLVQPGGSLRLSCAASGFNIKDTYIHWVRQAPGKGLEWVARIYPTNGYTRYADSV"
           "KGRFTISADTSKNTAYLQMNSLRAEDTAVYYCSRWGGDGFYAMDYWGQGTLVTVSS")


def test_clean_sequence_strips_invalid():
    seq, invalid = scan.clean_sequence("evql 123 vesXgg")
    assert seq == "EVQLVESGG"
    assert "X" in invalid


def test_basic_properties_in_range():
    r = scan.scan_sequence(TRAS_VH, "VH")
    assert r["length"] == 120
    assert 12000 < r["molecular_weight_da"] < 14000
    assert 6.0 < r["isoelectric_point"] < 10.0
    assert r["extinction"]["e280_cystines"] > r["extinction"]["e280_reduced"] or \
        TRAS_VH.count("C") < 2


def test_known_deamidation_hotspot_detected():
    r = scan.scan_sequence(TRAS_VH, "VH")
    types = {l["type"] for l in r["liabilities"]}
    assert "deamidation" in types        # NG/NS/... present
    assert "isomerization" in types      # DG present (WGGDG)


def test_cdr_flagging():
    # CDR-H2 NG deamidation (around position 55) should flag in_cdr=True
    r = scan.scan_sequence(TRAS_VH, "VH", cdr_ranges=[(50, 66)])
    ng = [l for l in r["liabilities"]
          if l["type"] == "deamidation" and 50 <= l["position"] <= 66]
    assert ng and all(l["in_cdr"] for l in ng)


def test_unpaired_cysteine_flag():
    r = scan.scan_sequence("EVQLCAA", "X")          # one Cys -> unpaired
    assert r["cysteine"]["odd_unpaired_cys"] is True
    assert "unpaired_cysteine" in r["developability_flags"]


def test_deterministic():
    a = scan.scan_sequence(TRAS_VH, "VH")
    b = scan.scan_sequence(TRAS_VH, "VH")
    assert a == b
