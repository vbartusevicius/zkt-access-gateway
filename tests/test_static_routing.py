"""Static/SPA serving: real files are served, unknown paths fall through to
index.html (so the SPA can own the URL), and nothing escapes the static dir."""
import os

import pytest

from backend.main import resolve_static_file


@pytest.fixture()
def static_dir(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    secret = tmp_path.parent / "secret.txt"
    secret.write_text("do not serve me")
    return tmp_path


class TestFileServing:
    def test_serves_existing_file(self, static_dir):
        assert resolve_static_file("index.html", str(static_dir)) == \
            os.path.realpath(str(static_dir / "index.html"))

    def test_serves_nested_file(self, static_dir):
        assert resolve_static_file("assets/app.js", str(static_dir)) is not None

    def test_leading_slash_tolerated(self, static_dir):
        assert resolve_static_file("/index.html", str(static_dir)) is not None


class TestSpaFallback:
    @pytest.mark.parametrize("path", ["doors", "events", "access/Timezone",
                                      "users", "device", ""])
    def test_spa_routes_fall_through_to_index(self, static_dir, path):
        # None means the caller serves index.html, letting the SPA route it
        assert resolve_static_file(path, str(static_dir)) is None

    def test_directory_is_not_served_as_file(self, static_dir):
        assert resolve_static_file("assets", str(static_dir)) is None


class TestPathTraversal:
    @pytest.mark.parametrize("path", [
        "../secret.txt",
        "../../etc/passwd",
        "assets/../../secret.txt",
        "./../secret.txt",
    ])
    def test_traversal_is_refused(self, static_dir, path):
        assert resolve_static_file(path, str(static_dir)) is None

    def test_symlink_escape_is_refused(self, static_dir):
        link = static_dir / "escape"
        try:
            os.symlink(str(static_dir.parent / "secret.txt"), str(link))
        except (OSError, NotImplementedError):
            pytest.skip("symlinks unavailable")
        assert resolve_static_file("escape", str(static_dir)) is None
