"""
Tests for slyp.analysis internals - specifically _facts_from_extract()'s
handling of unreadable_fields (as distinct from None-ness).

extract_payslip() already nulls every field it flags unreadable before
returning a PayslipExtract, so these two checks agree for data that came
through the real pipeline. analyse_payslip() is a public function
callable with any hand-built PayslipExtract though (as every test in this
suite does), and nothing in the contract enforces that a field can't be
present while also listed as unreadable - so _facts_from_extract() has to
check both explicitly, the same way findings.py's _check_* functions do.
"""

import re
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from slyp import calculations
from slyp.analysis import (
    _facts_from_extract,
    analyse_payslip,
    build_score,
    build_tax_code_explanation,
)
from slyp.findings import CalculationComparison
from slyp.calculations import parse_tax_code
from slyp.contract import (
    FIELD_LABELS,
    field_label,
    field_labels,
    Deductions,
    Finding,
    Pay,
    Period,
    PayslipExtract,
    Source,
    TaxCodeRead,
    UserContext,
)

TAX_CODE = parse_tax_code("1257L")


def _extract(*, unreadable_fields=None, ni_category="A", student_loan_plan=None, tax_year="2026/27"):
    return PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year=tax_year),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("800.00"), gross_ytd=Decimal("800.00")),
        deductions=Deductions(
            income_tax=Decimal("0.00"),
            national_insurance=Decimal("0.00"),
            ni_category=ni_category,
            student_loan_plan=student_loan_plan,
        ),
        net_pay=Decimal("800.00"),
        unreadable_fields=unreadable_fields or [],
    )


# --------------------------------------------------------------------------
# Happy path - regression
# --------------------------------------------------------------------------


def test_facts_from_extract_builds_normally_with_nothing_unreadable():
    extract = _extract()
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.frequency == "monthly"
    assert facts.period_number == 1
    assert facts.gross_ytd == Decimal("800.00")
    assert facts.ni_category == "A"
    assert facts.student_loan_plan is None


# --------------------------------------------------------------------------
# Unreadable (present-but-untrusted) must refuse, not just None
# --------------------------------------------------------------------------


def test_facts_from_extract_refuses_unreadable_frequency():
    extract = _extract(unreadable_fields=["period.frequency"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_period_number():
    extract = _extract(unreadable_fields=["period.period_number"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_gross_this_period():
    extract = _extract(unreadable_fields=["pay.gross_this_period"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_gross_ytd():
    extract = _extract(unreadable_fields=["pay.gross_ytd"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_ni_category():
    # A category is present ("A") but not confidently read - must refuse
    # rather than silently trust the guess.
    extract = _extract(unreadable_fields=["deductions.ni_category"])
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


def test_facts_from_extract_refuses_unreadable_student_loan_plan():
    # A plan is present ("2") but not confidently read - must refuse
    # rather than silently pick that plan or silently treat it as no
    # loan at all.
    extract = _extract(unreadable_fields=["deductions.student_loan_plan"], student_loan_plan="2")
    with pytest.raises(ValueError):
        _facts_from_extract(extract, TAX_CODE)


# --------------------------------------------------------------------------
# None (genuinely absent) must keep its existing, legitimate default -
# these are NOT the same as unreadable and must not start refusing too
# --------------------------------------------------------------------------


def test_facts_from_extract_defaults_absent_ni_category_to_a():
    extract = _extract(ni_category=None)
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.ni_category == "A"


def test_facts_from_extract_defaults_absent_student_loan_plan_to_none():
    extract = _extract(student_loan_plan=None)
    facts = _facts_from_extract(extract, TAX_CODE)
    assert facts.student_loan_plan is None


# --------------------------------------------------------------------------
# End to end: analyse_payslip() degrades gracefully rather than crashing
# or computing on untrusted data
# --------------------------------------------------------------------------


def test_analyse_payslip_degrades_gracefully_when_frequency_unreadable():
    extract = _extract(unreadable_fields=["period.frequency"])
    result = analyse_payslip(extract)
    assert result.status == "ok"
    assert any(f.id == "calculation_unavailable" for f in result.findings)
    assert not any(f.id == "income_tax_differs_from_calculation" for f in result.findings)


def test_analyse_payslip_degrades_gracefully_when_ni_category_unreadable():
    extract = _extract(unreadable_fields=["deductions.ni_category"])
    result = analyse_payslip(extract)
    assert result.status == "ok"
    assert any(f.id == "calculation_unavailable" for f in result.findings)
    assert not any(f.id == "national_insurance_differs_from_calculation" for f in result.findings)


# --------------------------------------------------------------------------
# Tax year gate - a payslip must not be calculated with the wrong year's
# rates, and an undeterminable tax year must refuse rather than assume
# the current one.
# --------------------------------------------------------------------------


def test_analyse_payslip_proceeds_for_the_supported_tax_year():
    extract = _extract(tax_year="2026/27")
    result = analyse_payslip(extract)
    assert result.status == "ok"


def test_analyse_payslip_refuses_a_prior_tax_year():
    extract = _extract(tax_year="2025/26")
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "2025/26" in result.failure_reason
    assert result.findings == []
    assert result.score is None


def test_analyse_payslip_refuses_when_tax_year_is_undeterminable():
    extract = _extract(tax_year=None)
    result = analyse_payslip(extract)
    assert result.status == "unsupported"
    assert "could not be determined" in result.failure_reason
    assert result.findings == []
    assert result.score is None


def test_the_refusal_names_the_tax_year_as_the_reason():
    """
    Distinct status and a message naming the real reason - not "this tax
    code needs a manual check" or a generic unreadable error, which would
    send the user to check the wrong thing.
    """
    result = analyse_payslip(_extract(tax_year="2025/26"))

    assert result.status == "unsupported"
    assert "2025/26" in result.failure_reason
    assert "not currently supported" in result.failure_reason
    assert result.verdict.headline == (
        "This payslip is from a tax year we don't yet support"
    )


# --------------------------------------------------------------------------
# Score: a check with nothing to check is not a pass
# --------------------------------------------------------------------------


def _scored(
    *,
    gross,
    tax,
    ni,
    net,
    gross_ytd=None,
    tax_code="1257L",
    period_number=1,
    unreadable_fields=None,
):
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(
            period_number=period_number, frequency="monthly", tax_year="2026/27"
        ),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(
            gross_this_period=Decimal(gross),
            gross_ytd=Decimal(gross_ytd or gross),
        ),
        deductions=Deductions(
            income_tax=Decimal(tax) if tax is not None else None,
            income_tax_ytd=Decimal(tax) if tax is not None else None,
            national_insurance=Decimal(ni) if ni is not None else None,
            ni_category="A",
        ),
        net_pay=Decimal(net),
        unreadable_fields=unreadable_fields or [],
    )
    return analyse_payslip(extract).score


def test_under_every_threshold_the_zero_comparisons_do_not_count_as_passes():
    """
    The £583.55 payslip. Income tax and NI are both £0.00 due and £0.00
    deducted - nothing could have been wrong, so nothing was verified.
    Those two must not be counted as passes.
    """
    score = _scored(gross="583.55", gross_ytd="854.07", tax="0.00", ni="0.00", net="583.55")

    assert score.checks_run == 2
    assert len(score.not_applicable) == 2
    assert any("income tax" in reason.lower() for reason in score.not_applicable)
    assert any("national insurance" in reason.lower() for reason in score.not_applicable)


def test_above_the_thresholds_every_check_genuinely_runs():
    score = _scored(
        gross="2500.00",
        gross_ytd="7500.00",
        tax="290.50",
        ni="116.16",
        net="2093.34",
        tax_code="1257L M1",
        period_number=5,
    )

    assert score.checks_run == 4
    assert score.checks_passed == 4
    assert score.not_applicable == []
    assert score.value == 100


def test_a_calculation_that_never_ran_is_not_four_silent_passes():
    """
    The case from the reported screenshot: the engine could not calculate
    (no period number), so no tax or NI finding could possibly fire - and
    the absence of a finding used to be counted as a pass, producing
    "4/4 checks clear" beside "we could not complete every calculation".
    """
    score = _scored(
        gross="2500.00",
        gross_ytd="7500.00",
        tax="290.50",
        ni="116.16",
        net="2093.34",
        unreadable_fields=["period.period_number"],
    )

    assert score.checks_run == 2  # reconciliation and tax code only
    assert len(score.not_applicable) == 2
    assert all("couldn't work out" in reason for reason in score.not_applicable)


def test_no_applicable_check_scores_none_rather_than_zero():
    """
    A zero would read as a failing payslip. None means unscored, which is
    what "we could not check anything here" actually is.

    Exercised through build_score() directly rather than analyse_payslip():
    an unreadable tax code fails validate_extract() and stops the analysis
    before scoring, so the tax-code check always runs on any result that
    reaches a score. The guard still has to hold for direct callers, and
    for the day validate_extract() softens.
    """
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("583.55"), gross_ytd=Decimal("583.55")),
        deductions=Deductions(income_tax=None, national_insurance=None, ni_category="A"),
        net_pay=Decimal("583.55"),
        unreadable_fields=["tax_code.value"],
    )

    score = build_score(findings=[], extract=extract, comparison=CalculationComparison())

    assert score.checks_run == 0
    assert score.checks_passed == 0
    assert score.value is None
    assert len(score.not_applicable) == 4


def test_score_without_a_comparison_treats_every_calculated_check_as_not_run():
    """
    build_score()'s comparison argument defaults to None for backwards
    compatibility. That must mean "nothing was calculated", not "the
    calculation agreed" - the difference between a hedge and a pass.
    """
    extract = PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=1, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value="1257L"),
        pay=Pay(gross_this_period=Decimal("2500.00"), gross_ytd=Decimal("2500.00")),
        deductions=Deductions(
            income_tax=Decimal("290.50"),
            national_insurance=Decimal("116.16"),
            ni_category="A",
        ),
        net_pay=Decimal("2093.34"),
    )

    score = build_score(findings=[], extract=extract)

    assert score.checks_run == 2  # reconciliation + tax code
    assert len(score.not_applicable) == 2


# --------------------------------------------------------------------------
# £100,000 Personal Allowance taper, end to end  —  FR-04
# --------------------------------------------------------------------------


def _high_earner_extract(tax_code="1257L"):
    """A CORRECT £150,000 payslip: £12,500/month at month 12, taxed exactly
    as HMRC would with a fully tapered (zero) allowance.

        20% of 37,700         =  7,540.00
      + 40% of (125,140-37,700) = 34,976.00
      + 45% of (150,000-125,140) = 11,187.00
                                 ----------
                                  53,703.00 for the year  ->  4,475.25/month

    NI: 8% of (4,189-1,048) + 2% of (12,500-4,189) = 417.50.
    """
    gross = Decimal("12500.00")
    income_tax = Decimal("4475.25")
    national_insurance = Decimal("417.50")

    return PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=12, frequency="monthly", tax_year="2026/27"),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(gross_this_period=gross, gross_ytd=Decimal("150000.00")),
        deductions=Deductions(
            income_tax=income_tax,
            national_insurance=national_insurance,
            ni_category="A",
        ),
        net_pay=gross - income_tax - national_insurance,
        reconciles=True,
    )


def test_the_150k_repro_returns_unsupported_not_a_finding():
    """FR-04, verify/FINAL_REPORT.md.

    This exact payslip used to return status="ok" with a verdict of "2
    things to check", a score of 75, and an
    income_tax_differs_from_calculation finding claiming £678.37 had been
    under-deducted - on a payslip that is correct to the penny.

    Named after the repro so it cannot be quietly retired.
    """
    result = analyse_payslip(_high_earner_extract())

    assert result.status == "unsupported"
    assert result.findings == []
    assert result.score is None

    # The user must be told the actual reason, not "we could not complete
    # every calculation".
    assert result.failure_reason is not None
    assert "100,000" in result.failure_reason
    assert "Personal Allowance" in result.failure_reason

    # The specific wrong claim must be gone.
    assert not any(
        f.id == "income_tax_differs_from_calculation" for f in result.findings
    )
    assert "678.37" not in (result.failure_reason or "")


def test_the_150k_repro_no_longer_produces_any_pound_figure():
    """Rule 2, stated as a property rather than a finding id: a refusal
    must not carry a number the user could act on."""
    result = analyse_payslip(_high_earner_extract())

    assert all(f.estimate is None for f in result.findings)


def test_a_high_earner_on_a_zero_allowance_code_is_still_analysed():
    """BR grants no allowance, so there is nothing to taper - refusing it
    would refuse a payslip the engine handles correctly."""
    result = analyse_payslip(_high_earner_extract(tax_code="BR"))

    assert result.status == "ok"


def test_an_ordinary_payslip_is_unaffected_by_the_taper_guard():
    """The guard must not have narrowed what the engine will answer."""
    result = analyse_payslip(_extract())

    assert result.status == "ok"


# --------------------------------------------------------------------------
# Personal Allowance used to date
# --------------------------------------------------------------------------
#
# Gated harder than anything else in the result. The emergency-code estimate
# is framed as "possible, check with HMRC"; this is a flat statement about
# the user's own tax position, and it would be acted on. So it is shown on
# exactly one branch and suppressed everywhere else, with no hedged variant.


def _allowance_extract(
    *,
    tax_code="1257L",
    gross_ytd=Decimal("7500.00"),
    unreadable=None,
    previous_employment=False,
    period_number=5,
):
    return PayslipExtract(
        source=Source(filename="t.pdf", pages=1, scanned_at=datetime.now(timezone.utc)),
        period=Period(period_number=period_number, frequency="monthly",
                      tax_year="2026/27"),
        tax_code=TaxCodeRead(value=tax_code),
        pay=Pay(gross_this_period=Decimal("2500.00"), gross_ytd=gross_ytd),
        deductions=Deductions(
            income_tax=Decimal("290.50"),
            national_insurance=Decimal("116.16"),
            ni_category="A",
        ),
        net_pay=Decimal("2093.34"),
        unreadable_fields=unreadable or [],
        previous_employment_ytd_present=previous_employment,
    )


def test_allowance_used_worked_example_7500_of_12570():
    """The worked example, pinned by name.

    1257L grants GBP 12,570 for the year. Year-to-date gross on this
    employment is GBP 7,500, which is below the allowance, so all GBP 7,500
    of it has been covered by the allowance:

        used = min(7,500.00, 12,570.00) = 7,500.00

    Hand-checked. If the wording or the arithmetic moves, this fails.
    """
    result = analyse_payslip(_allowance_extract(), UserContext(only_job=True))

    usage = result.allowance_usage
    assert usage is not None
    assert usage.used_gbp == Decimal("7500.00")
    assert usage.allowance_gbp == Decimal("12570")
    assert usage.statement == (
        "You've used £7,500.00 of your £12,570.00 tax-free allowance this year."
    )
    # It must not talk about what is left, or about the rest of the year.
    for forbidden in ("left", "remaining", "by April", "you can still", "before you"):
        assert forbidden not in usage.statement.lower()


def test_allowance_used_is_capped_at_the_allowance():
    """Earnings above the allowance have used all of it, not more than it."""
    result = analyse_payslip(
        _allowance_extract(gross_ytd=Decimal("20000.00")),
        UserContext(only_job=True),
    )
    assert result.allowance_usage is not None
    assert result.allowance_usage.used_gbp == Decimal("12570")


def test_allowance_suppressed_when_there_is_other_employment():
    """Answered yes to another job. YTD covers this employment only, so the
    figure would be understated by whatever they earned elsewhere."""
    result = analyse_payslip(_allowance_extract(), UserContext(only_job=False))
    assert result.allowance_usage is None


def test_allowance_suppressed_when_the_question_was_not_answered():
    """'Not sure', or never asked. No hedged variant - suppressed outright."""
    assert analyse_payslip(
        _allowance_extract(), UserContext(only_job=None)
    ).allowance_usage is None
    assert analyse_payslip(_allowance_extract()).allowance_usage is None


@pytest.mark.parametrize("tax_code", ["BR", "D0", "D1", "0T"])
def test_allowance_suppressed_for_codes_granting_no_allowance(tax_code):
    """Nothing to track: these codes grant no Personal Allowance here."""
    result = analyse_payslip(
        _allowance_extract(tax_code=tax_code), UserContext(only_job=True)
    )
    assert result.allowance_usage is None


@pytest.mark.parametrize(
    "field", ["pay.gross_ytd", "tax_code.value", "period.period_number"]
)
def test_allowance_suppressed_when_an_input_failed_the_confidence_gate(field):
    result = analyse_payslip(
        _allowance_extract(unreadable=[field]), UserContext(only_job=True)
    )
    assert result.allowance_usage is None


def test_allowance_suppressed_when_the_payslip_shows_previous_employment():
    """Documentary evidence beats the user's answer. Someone who joined in
    July may well consider this their only job now, but the YTD column
    still is not the whole tax year."""
    result = analyse_payslip(
        _allowance_extract(previous_employment=True), UserContext(only_job=True)
    )
    assert result.allowance_usage is None


def test_allowance_suppressed_on_a_refused_tax_year():
    extract = _allowance_extract()
    extract.period.tax_year = "2025/26"
    result = analyse_payslip(extract, UserContext(only_job=True))
    assert result.status == "unsupported"
    assert result.allowance_usage is None


@pytest.mark.parametrize("tax_code", ["S1257L", "C1257L", "K475"])
def test_allowance_suppressed_on_a_refused_tax_code(tax_code):
    result = analyse_payslip(
        _allowance_extract(tax_code=tax_code), UserContext(only_job=True)
    )
    assert result.status == "unsupported"
    assert result.allowance_usage is None


def test_allowance_suppressed_above_the_taper_threshold():
    """The GBP 100k refusal returns before the allowance figure is built."""
    extract = _allowance_extract(gross_ytd=Decimal("150000.00"))
    extract.pay.gross_this_period = Decimal("12500.00")
    extract.period.period_number = 12
    result = analyse_payslip(extract, UserContext(only_job=True))
    assert result.status == "unsupported"
    assert result.allowance_usage is None


# --------------------------------------------------------------------------
# No dotted field path may reach a user
# --------------------------------------------------------------------------
#
# "tax_code.value" was rendered to a real user. Paths are an internal key -
# the findings layer matches Finding.source_fields against unreadable_fields
# and both have to be exact - but they are not English, and three separate
# places printed the key instead of a label:
#
#   1. app/page.tsx rendered unreadable_fields.join(", ")
#   2. validate_extract built failure_reason by joining the paths
#   3. four path_warnings in extract_payslip began with one
#
# This asserts the property rather than the three sites, so a fourth place
# fails here rather than reaching someone's screen.

FIELD_PATH = re.compile(
    r"\b(?:tax_code|pay|deductions|period|net_pay|employer_name)(?:\.[a-z_]+)+\b"
)


def _user_facing_strings(result):
    """Every string in an AnalysisResult a person can end up reading."""
    out = []
    if result.failure_reason:
        out.append(("failure_reason", result.failure_reason))
    if result.verdict:
        out.append(("verdict.headline", result.verdict.headline))
    for finding in result.findings:
        out.append((f"{finding.id}.title", finding.title))
        out.append((f"{finding.id}.explanation", finding.explanation))
        if finding.next_step:
            out.append((f"{finding.id}.next_step", finding.next_step))
        if finding.estimate:
            out.append((f"{finding.id}.estimate.label", finding.estimate.label))
    if result.score:
        out += [("score.movers", m) for m in result.score.movers]
        out += [("score.not_applicable", n) for n in result.score.not_applicable]
    if result.allowance_usage:
        out.append(("allowance_usage.statement", result.allowance_usage.statement))
    if result.extract:
        out += [("extract.warnings", w) for w in result.extract.warnings]
        out += [
            ("extract.unreadable_field_labels", label)
            for label in result.extract.unreadable_field_labels
        ]
    return out


@pytest.mark.parametrize(
    "unreadable",
    [
        [],
        ["tax_code.value"],
        ["pay.gross_this_period"],
        ["net_pay"],
        ["pay.gross_ytd"],
        ["deductions.income_tax"],
        ["deductions.national_insurance"],
        ["deductions.pension_employee"],
        ["period.frequency"],
        ["period.period_number"],
        ["pay.gross_this_period", "net_pay", "tax_code.value"],
    ],
)
def test_no_user_facing_string_contains_a_field_path(unreadable):
    extract = _allowance_extract()
    extract.unreadable_fields = unreadable
    if "tax_code.value" in unreadable:
        extract.tax_code.value = None

    result = analyse_payslip(extract, UserContext(only_job=True))

    for where, text in _user_facing_strings(result):
        assert not FIELD_PATH.search(text), (
            f"{where} leaks a field path: {text!r}"
        )


def test_every_known_field_path_has_a_label():
    """A path with no entry falls back to something generic, which is safe
    but useless. Every path extraction can actually report should have real
    words."""
    from slyp.extraction import _KNOWN_FIELD_PATHS

    missing = sorted(p for p in _KNOWN_FIELD_PATHS if p not in FIELD_LABELS)

    assert missing == [], f"no label for: {missing}"


def test_labels_are_deduplicated_but_order_is_kept():
    assert field_labels(["net_pay", "tax_code.value", "net_pay"]) == [
        "your net pay",
        "your tax code",
    ]


def test_an_unknown_path_falls_back_without_leaking_it():
    assert "made.up.path" not in field_label("made.up.path")


# --------------------------------------------------------------------------
# What the tax code means
# --------------------------------------------------------------------------
#
# A clean payslip told the user nothing about what any of it meant - we only
# spoke when something was wrong. This explains what is printed, on every
# payslip, including one with no findings at all.
#
# Explain, never advise. The line is easy to cross and BR is where it would
# happen: "no personal allowance is applied here" is what the code does,
# "which is normal for a second job" is a claim about the reader's
# circumstances that the findings layer only makes when only_job is False.


# Anything asserting a code is right, expected or unremarkable. Some are
# claims about the user's situation, which this layer knows nothing about;
# the rest are reassurance, which is advice wearing a description's clothes.
FORBIDDEN_WORDS = [
    "normal", "correct", "expected", "fine", "should be", "as it should",
    "nothing wrong", "no problem", "usual", "typical", "common",
    "appropriate", "second job", "another job", "looks right", "is right",
    "don't worry", "no need",
]

TAX_CODES = ["1257L", "BR", "D0", "D1", "0T", "NT"]


def _explain(code, findings=None):
    extract = _allowance_extract(tax_code=code)
    return build_tax_code_explanation(extract, parse_tax_code(code), findings or [])


@pytest.mark.parametrize("base", TAX_CODES)
@pytest.mark.parametrize("suffix", ["", " M1"])
def test_every_reachable_code_and_basis_is_explained(base, suffix):
    """Twelve combinations - six kinds, cumulative and not. These are the
    only ones that reach status ok: parse_tax_code raises for Scottish,
    Welsh, K and unparseable codes, so analyse_payslip returns unsupported
    before findings are built."""
    explanation = _explain(base + suffix)

    assert explanation is not None
    assert explanation.subject == "tax_code"
    assert base + suffix in explanation.body
    assert len(explanation.body) > 60


@pytest.mark.parametrize("base", TAX_CODES)
@pytest.mark.parametrize("suffix", ["", " M1"])
def test_no_explanation_implies_a_code_is_correct_or_normal(base, suffix):
    explanation = _explain(base + suffix)
    lowered = explanation.body.lower()

    for word in FORBIDDEN_WORDS:
        assert word not in lowered, f"{base + suffix}: says {word!r} -> {explanation.body}"


def test_the_br_explanation_says_what_br_does_and_nothing_about_whether_it_fits():
    """Called out on its own because it is the specific trap. The findings
    layer has user_context and says "BR can be expected for a second job"
    only when only_job is False. This layer has no user context, so saying
    it here would state unconditionally what the findings layer gates - and
    would tell someone on BR as their ONLY job that it was expected."""
    body = _explain("BR").body.lower()

    assert "basic rate" in body
    assert "no personal allowance" in body
    for word in ("second job", "another job", "normal", "expected", "correct"):
        assert word not in body


@pytest.mark.parametrize(
    ("code", "must_contain"),
    [
        ("1257L", ["£12,570", "cumulatively"]),
        ("1257L M1", ["£12,570", "on its own"]),
        ("500L", ["£5,000"]),
        ("BR", ["basic rate"]),
        ("D0", ["higher rate"]),
        ("D1", ["additional rate"]),
        ("0T", ["no personal allowance", "first pound"]),
        ("NT", ["no income tax"]),
    ],
)
def test_the_wording_says_the_right_thing_for_each_code(code, must_contain):
    body = _explain(code).body.lower()

    for phrase in must_contain:
        assert phrase.lower() in body, f"{code}: missing {phrase!r} -> {body}"


def test_the_allowance_figure_comes_from_the_parsed_code_not_new_arithmetic():
    """free_pay_annual was computed by parse_tax_code from the digits on the
    payslip. This layer reads it; it does not recompute it."""
    assert f"£{parse_tax_code('1257L').free_pay_annual:,.0f}" in _explain("1257L").body
    assert f"£{parse_tax_code('500L').free_pay_annual:,.0f}" in _explain("500L").body


def test_suppressed_when_the_tax_code_failed_the_confidence_gate():
    extract = _allowance_extract(tax_code="1257L")
    extract.unreadable_fields = ["tax_code.value"]

    assert build_tax_code_explanation(extract, parse_tax_code("1257L"), []) is None


@pytest.mark.parametrize(
    "finding_id",
    ["tax_code_d0", "tax_code_d1", "tax_code_zero_allowance", "tax_code_nt",
     "tax_code_emergency_basis"],
)
def test_suppressed_when_a_finding_already_explains_the_code(finding_id):
    """Suppress, not replace - the same sentence must not appear twice on
    one screen, and those findings keep working exactly as they did."""
    finding = Finding(
        id=finding_id, severity="advisory", title="t", explanation="e"
    )

    assert _explain("1257L", findings=[finding]) is None


def test_an_unrelated_finding_does_not_suppress_it():
    finding = Finding(
        id="payslip_does_not_reconcile", severity="action", title="t", explanation="e"
    )

    assert _explain("1257L", findings=[finding]) is not None


def test_it_renders_on_a_payslip_with_no_findings_at_all():
    """The point of the feature. A clean payslip previously said nothing
    about what any of it meant."""
    result = analyse_payslip(_allowance_extract(), UserContext(only_job=True))

    assert result.findings == []
    assert len(result.explanations) == 1
    assert result.explanations[0].subject == "tax_code"
    assert "1257L" in result.explanations[0].body


def test_a_refused_code_produces_no_partial_explanation():
    """Scottish, Welsh and K codes return unsupported before findings are
    built, so there is nothing to half-explain."""
    for code in ("S1257L", "C1257L", "K475"):
        extract = _allowance_extract(tax_code=code)
        result = analyse_payslip(extract, UserContext(only_job=True))

        assert result.status == "unsupported"
        assert result.explanations == []
