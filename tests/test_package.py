import importlib.util
from pathlib import Path
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("package", ROOT / "scripts/package.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class PackageTests(unittest.TestCase):
    def test_package_is_reproducible_and_contains_only_installable_files(self):
        with tempfile.TemporaryDirectory() as directory:
            first, second = (Path(directory) / name for name in ("a.zip", "b.zip"))
            self.assertEqual(package.build(first), package.build(second))
            with zipfile.ZipFile(first) as archive:
                self.assertIn("meta.xml", archive.namelist())
                self.assertIn("htdocs/index.php", archive.namelist())
                self.assertIn("_meta/pre-install.php", archive.namelist())
                self.assertNotIn("AGENTS.md", archive.namelist())
                self.assertFalse(any("__pycache__" in name or name.endswith(".key") for name in archive.namelist()))
