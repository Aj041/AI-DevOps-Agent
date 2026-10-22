import pytest
from tools.core import RepositoryTools

def test_tools_reject_path_escape(tmp_path):
    with pytest.raises(ValueError): RepositoryTools(str(tmp_path)).read_file("../secret")

def test_tools_proposal_does_not_write(tmp_path):
    result = RepositoryTools(str(tmp_path)).proposed_file("new.txt", "hello")
    assert result["is_new"] and not (tmp_path / "new.txt").exists()
