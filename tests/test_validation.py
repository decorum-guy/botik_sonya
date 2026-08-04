from app.models import ValidatorSpec
from app.validation import validate_answer


def test_text_exact_normalizes_case_yo_and_punctuation() -> None:
    spec = ValidatorSpec(type="text_exact", values=["Ёлка"])
    assert validate_answer(" ёЛкА!!! ", spec)


def test_integer_range() -> None:
    spec = ValidatorSpec(type="integer_range", minimum=10, maximum=20)
    assert validate_answer("15", spec)
    assert not validate_answer("21", spec)


def test_date_equal_accepts_common_formats() -> None:
    spec = ValidatorSpec(type="date_equal", date="2023-09-18")
    assert validate_answer("18.09.2023", spec)
    assert validate_answer("2023-09-18", spec)
