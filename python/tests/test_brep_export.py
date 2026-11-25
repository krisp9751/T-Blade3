"""STEP and .brep export of the blade-row bodies (tblade3.brep.export)."""
import pytest

pytest.importorskip("OCP")
from tblade3.brep import build, export, occ  # noqa: E402


@pytest.fixture(scope="module")
def row(tct_geometry):
    return build.build_row(tct_geometry)


def test_step_roundtrip_with_names(row, tmp_path):
    paths = export.export_row(row, tmp_path, "tct", formats=("step",))
    assert paths == [tmp_path / "tct.step"]
    back = export.read_step(paths[0])
    assert set(back) == set(export.DEFAULT_BODIES)
    for name, (shape, faces) in back.items():
        assert occ.is_valid(shape)
        assert occ.volume(shape) == pytest.approx(occ.volume(row.bodies[name]), rel=1e-7)
        assert set(faces) == set(row.faces_by_role(name)), name


def test_brep_files(row, tmp_path):
    paths = export.export_row(row, tmp_path, "tct", bodies=("passage", "assembly"), formats=("brep",))
    assert [p.name for p in paths] == ["tct_passage.brep", "tct_assembly.brep"]
    shape = export.read_brep(paths[0])
    assert occ.volume(shape) == pytest.approx(occ.volume(row.bodies["passage"]), rel=1e-9)
    assert occ.counts(export.read_brep(paths[1]))["solid"] == 3


def test_bad_arguments(row, tmp_path):
    with pytest.raises(ValueError):
        export.export_row(row, tmp_path, "x", bodies=("wing",))
    with pytest.raises(ValueError):
        export.export_row(row, tmp_path, "x", formats=("iges",))
