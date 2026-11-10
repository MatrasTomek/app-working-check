from pathlib import Path

import pytest

from appcheck.config import ConfigError
from appcheck.statuses import StatusDef, load_statuses, resolve_status


def write(tmp_path, body):
    p = tmp_path / "statuses.yaml"
    p.write_text(body, encoding="utf-8")
    return p


def test_loads_in_order(tmp_path):
    p = write(tmp_path, 'statuses:\n  - {tag: in-progress, label: " W toku ", color: "#D29922"}\n'
                        '  - {tag: done, label: Gotowe, color: "#0969da"}\n')
    assert load_statuses(p) == [StatusDef("in-progress", "W toku", "#d29922"),
                                StatusDef("done", "Gotowe", "#0969da")]


def test_missing_file_is_empty(tmp_path):
    assert load_statuses(tmp_path / "brak.yaml") == []


def test_project_file_is_valid():
    statuses = load_statuses(Path(__file__).parent.parent / "statuses.yaml")
    assert {"in-progress", "in-live-test", "draft", "idea"} <= {s.tag for s in statuses}


@pytest.mark.parametrize("body, message", [
    ('statuses:\n  - {tag: "W toku", label: X, color: "#000000"}\n', "małe litery"),
    ('statuses:\n  - {tag: done, label: X, color: "#000000"}\n  - {tag: done, label: Y, color: "#000000"}\n',
     "powtarza się"),
    ('statuses:\n  - {tag: done, color: "#000000"}\n', "brak pola 'label'"),
    ('statuses:\n  - {tag: done, label: X, color: red}\n', "#rrggbb"),
    ("statuses:\n  - tag: done\n    label: X\n    color: #000000\n", "#rrggbb"),  # bez cudzysłowu # to komentarz
    ("statuses: done\n", "musi być listą"),
])
def test_invalid(tmp_path, body, message):
    with pytest.raises(ConfigError, match=message):
        load_statuses(write(tmp_path, body))


def test_resolve_status_first_in_file_order_wins():
    statuses = [StatusDef("production", "Produkcja", "#1a7f37"), StatusDef("in-progress", "W toku", "#d29922")]
    assert resolve_status(["in-progress", "production", "react"], statuses).tag == "production"
    assert resolve_status(["react"], statuses) is None


def test_text_color_contrast():
    assert StatusDef("a", "A", "#d29922").text_color == "#000000"
    assert StatusDef("b", "B", "#0969da").text_color == "#ffffff"
