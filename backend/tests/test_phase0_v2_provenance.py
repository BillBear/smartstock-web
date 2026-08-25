import hashlib
import json
import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
TRACKED_COPY = REPOSITORY_ROOT / "docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md"
CHECKSUM = REPOSITORY_ROOT / "docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.sha256"
PROVENANCE_FILE = REPOSITORY_ROOT / "docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.provenance.json"
ORIGINAL_PATH = "/Users/xiong/Documents/SmartStock/reference/SmartStock_Codex_整改执行方案_v2_对抗性审查后_2026-08-21.md"
EXPECTED_SHA = "1331ba14afb59be32dc06247fc742191f3df08af15095ad8a373d04c4070aa72"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class Phase0V2ProvenanceTests(unittest.TestCase):
    def test_tracked_v2_checksum_and_provenance_are_byte_identical(self):
        self.assertEqual(sha256_file(TRACKED_COPY), EXPECTED_SHA)
        provenance = json.loads(PROVENANCE_FILE.read_text())
        self.assertEqual(provenance["original_absolute_path"], ORIGINAL_PATH)
        self.assertEqual(provenance["original_sha256"], EXPECTED_SHA)
        self.assertEqual(provenance["tracked_copy_sha256"], EXPECTED_SHA)
        self.assertTrue(provenance["byte_identical"])
        self.assertEqual(
            CHECKSUM.read_text().split()[-1],
            "docs/superpowers/specs/2026-08-21-smartstock-remediation-v2.md",
        )


if __name__ == "__main__":
    unittest.main()
