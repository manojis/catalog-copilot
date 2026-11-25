import gzip
import json
from pathlib import Path

import pytest

from catalog_copilot.ingest.source import iter_records


@pytest.mark.parametrize("name", ["records.jsonl", "records.jsonl.gz"])
def test_iter_records_reads_plain_and_gzip_and_skips_bad_lines(tmp_path: Path, name: str) -> None:
    path = tmp_path / name
    content = json.dumps({"a": 1}) + "\n\nnot json\n" + json.dumps({"a": 2}) + "\n"
    if name.endswith(".gz"):
        with gzip.open(path, "wt", encoding="utf-8") as f:
            f.write(content)
    else:
        path.write_text(content, encoding="utf-8")

    assert list(iter_records(str(path))) == [{"a": 1}, {"a": 2}]
