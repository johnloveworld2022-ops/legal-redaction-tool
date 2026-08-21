import pytest

import core.case_workspace as case_workspace
from core.case_workspace import case_workspace_for


@pytest.fixture(autouse=True)
def isolated_workbench(tmp_path, monkeypatch):
    monkeypatch.setattr(case_workspace, "WORKBENCH_ROOT", tmp_path / "工作台")
    yield


def test_normal_case_name_creates_workspace_inside_workbench_root(tmp_path):
    ws = case_workspace_for("测试案A")
    assert case_workspace.WORKBENCH_ROOT in ws.root.parents


@pytest.mark.parametrize(
    "malicious_name",
    [
        "x/../../../../../tmp/evil_case",
        "../escape",
        "a/b",
        "a\\b",
        "..",
        "./..",
    ],
)
def test_path_traversal_in_case_name_is_rejected(malicious_name):
    with pytest.raises(ValueError):
        case_workspace_for(malicious_name)


def test_rejected_case_name_never_creates_any_directory_outside_workbench(tmp_path):
    # Belt and suspenders: even if the ValueError guard were somehow
    # bypassed, no directory should ever be created outside WORKBENCH_ROOT.
    outside_marker = tmp_path / "tmp" / "evil_case"
    try:
        case_workspace_for("x/../../../../../tmp/evil_case")
    except ValueError:
        pass
    assert not outside_marker.exists()
