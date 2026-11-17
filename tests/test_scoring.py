"""Scoring: per-product fit weights (sector 20 / maker 30 / reach 25 / buying 25)."""

from types import SimpleNamespace

from sellbird.fit import company_fit, product_fit


def _product(industries=("K-12 School",), titles=("Principal",), hiring=("Admission Counsellor",)):
    return {
        "id": "school-erp",
        "icp": {
            "industries": list(industries),
            "company_size": "20-200 staff",
            "titles": list(titles),
            "geography": ["India"],
            "hiring_signals": list(hiring),
        },
    }


def _company(industry="K-12 School"):
    return {"id": "c1", "name": "Test School", "domain": "test.test", "industry": industry}


def _person(title="Principal", status="verified", first="Ana"):
    return {"first_name": first, "title": title, "email_status": status, "status": "new"}


def test_full_fit_is_100():
    score, reasons = product_fit(
        _company(), [_person()],
        [{"signal_code": "HIRING_ROLE", "value_text": "Admission Counsellor wanted"}],
        _product(),
    )
    assert score == 100
    assert reasons == ["sector: K-12 School", "decision maker: Principal",
                       "verified email", "hiring: admission counsellor"]


def test_off_sector_and_no_contact_scores_low():
    score, reasons = product_fit(_company("Steel Plant"), [], [], _product())
    assert score == 0
    assert "no way to reach yet" in reasons


def test_guessed_email_is_only_5_points():
    score, reasons = product_fit(_company(), [_person(status="guess")], [], _product())
    assert score == 20 + 30 + 5
    assert "guessed email" in reasons


def test_upstream_company_fit_unchanged():
    cfg = SimpleNamespace(
        icp=SimpleNamespace(industries=["K-12 School"], titles=["Principal"],
                            hiring_signals=["Admission Counsellor"]),
        compliance=SimpleNamespace(do_not_contact=[]),
    )
    score, _ = company_fit(_company(), [_person()], [], cfg)
    assert score == 20 + 30 + 25
