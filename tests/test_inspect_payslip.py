from tools.inspect_payslip import find_labels


def test_finds_each_label_on_its_own_line():
    text = "\n".join(
        [
            "Tax Code: 1257L",
            "Gross Pay: 2500.00",
            "Net Pay: 1900.00",
            "National Insurance: 210.00",
            "PAYE: 300.00",
            "Pension: 75.00",
            "Student Loan: 45.00",
            "Year to Date: 12500.00",
            "Employee Number: 00123",
        ]
    )
    hits = find_labels(text)

    assert hits["tax code"] == ["Tax Code: 1257L"]
    assert hits["gross"] == ["Gross Pay: 2500.00"]
    assert hits["net"] == ["Net Pay: 1900.00"]
    assert hits["national insurance"] == ["National Insurance: 210.00"]
    assert hits["PAYE / income tax"] == ["PAYE: 300.00"]
    assert hits["pension"] == ["Pension: 75.00"]
    assert hits["student loan"] == ["Student Loan: 45.00"]
    assert hits["year to date / YTD"] == ["Year to Date: 12500.00"]
    assert hits["employee number"] == ["Employee Number: 00123"]


def test_label_with_no_match_is_absent():
    hits = find_labels("Nothing relevant here.")
    assert hits == {}


def test_matching_is_case_insensitive():
    hits = find_labels("TAX CODE: BR")
    assert hits["tax code"] == ["TAX CODE: BR"]


def test_line_can_match_two_labels_at_once():
    hits = find_labels("National Insurance Number: QQ123456C")
    assert hits["national insurance"] == ["National Insurance Number: QQ123456C"]
    assert hits["NI number"] == ["National Insurance Number: QQ123456C"]


def test_income_tax_wording_matches_paye_label():
    hits = find_labels("Income Tax this period: 150.00")
    assert hits["PAYE / income tax"] == ["Income Tax this period: 150.00"]
