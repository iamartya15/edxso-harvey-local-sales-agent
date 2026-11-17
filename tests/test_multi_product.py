"""Multi-product: config, per-product scoring, dashboard product list."""

import json
from pathlib import Path

import pytest

from sellbird.config import SellbirdConfig
from sellbird.fit import product_fit

ROOT = Path(__file__).resolve().parent.parent


def _seed() -> dict:
    return json.loads((ROOT / "data" / "seed_sample_data.json").read_text())


def _company(seed, product_id):
    return next(c for c in seed["companies"] if c["product_id"] == product_id)


def test_seed_has_three_products_and_ten_prospects():
    seed = _seed()
    assert len(seed["products"]) == 3
    assert {p["id"] for p in seed["products"]} == {
        "school-erp", "coaching-booking", "college-attendance"}
    assert len(seed["prospects"]) == 10
    assert all(p["email"].endswith(".test") for p in seed["prospects"])
    assert all(p["email_status"] == "guess" for p in seed["prospects"])


def test_each_product_has_icp_and_offer():
    for product in _seed()["products"]:
        assert product["icp"]["industries"] and product["icp"]["titles"]
        assert product["icp"]["geography"]
        assert product["key_benefits"] and product["objection_responses"]
        assert product["offer"]["primary"]


def test_config_loads_three_products_with_own_icps():
    import yaml

    data = yaml.safe_load((ROOT / "sellbird.yaml").read_text())
    cfg = SellbirdConfig(**data)
    assert len(cfg.all_products()) == 3
    assert cfg.brain.provider == "ollama"
    assert cfg.brain.model == "qwen3:0.6b"
    erp = cfg.product_by_id("school-erp")
    assert erp is not None and erp.icp is not None
    assert "K-12 School" in erp.icp.industries
    assert cfg.icp_for_product(erp).titles == erp.icp.titles
    assert cfg.product_by_id("nope") is None


def test_same_company_scores_differently_per_product():
    seed = _seed()
    school = _company(seed, "school-erp")
    prospects = [p for p in seed["prospects"] if p["company_id"] == school["id"]]
    observations = [o for o in seed["observations"] if o["company_id"] == school["id"]]
    erp = next(p for p in seed["products"] if p["id"] == "school-erp")
    coaching = next(p for p in seed["products"] if p["id"] == "coaching-booking")
    erp_score, _ = product_fit(school, prospects, observations, erp)
    coaching_score, _ = product_fit(school, prospects, observations, coaching)
    # A K-12 school matches the school ERP ICP, not the coaching ICP.
    assert erp_score > coaching_score
    assert 0 <= erp_score <= 100 and 0 <= coaching_score <= 100


def test_hiring_school_scores_full_buying_points():
    seed = _seed()
    school = _company(seed, "school-erp")
    # co-02 (Little Scholars) is hiring an Admission Counsellor: 25 buying pts.
    school = next(c for c in seed["companies"] if c["id"] == "co-02")
    prospects = [p for p in seed["prospects"] if p["company_id"] == "co-02"]
    observations = [o for o in seed["observations"] if o["company_id"] == "co-02"]
    erp = next(p for p in seed["products"] if p["id"] == "school-erp")
    score, reasons = product_fit(school, prospects, observations, erp)
    assert "hiring: admission counsellor" in reasons
    assert score == 20 + 30 + 5 + 25  # sector + decision-maker + guess email + hiring
