from app.votes import (
    code_to_label,
    has_concurrence,
    has_dissent,
    parse_vote_entries,
    vote_breakdown,
)


def test_parse_vote_entries_stacked_and_mixed():
    entries = parse_vote_entries(
        "Thomas (C); Gorsuch (C); Sotomayor (C/J/P, D/P); Jackson (C/J/P, D/P)"
    )
    assert entries == [
        ("Thomas", "C"),
        ("Gorsuch", "C"),
        ("Sotomayor", "C/J/P,D/P"),
        ("Jackson", "C/J/P,D/P"),
    ]


def test_has_dissent_and_concurrence():
    other = "Thomas (C); Sotomayor (D)"
    assert has_dissent(other) is True
    assert has_concurrence(other) is True
    assert has_dissent("Sotomayor (C/J)") is False
    assert has_concurrence("Sotomayor (C/J)") is True
    assert has_dissent(None) is False
    assert has_concurrence("") is False


def test_vote_breakdown_flags():
    votes = vote_breakdown("Sotomayor (C/J/P, D/P)")
    assert len(votes) == 1
    assert votes[0]["author"] == "Sotomayor"
    assert votes[0]["has_dissent"] is True
    assert votes[0]["has_concurrence"] is True
    assert "Concurrence in the judgment in part" in votes[0]["label"]
    assert "Dissent in part" in votes[0]["label"]


def test_code_to_label_stacked_qualifiers():
    assert code_to_label("C/J/P") == "Concurrence in the judgment in part"
