from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "download_physionet_2019.py"
SPEC = importlib.util.spec_from_file_location("download_physionet_2019", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class PhysioNetDownloaderTests(unittest.TestCase):
    def test_namespaced_s3_listing_is_parsed(self) -> None:
        xml = b"""<?xml version='1.0' encoding='UTF-8'?>
        <ListBucketResult xmlns='http://s3.amazonaws.com/doc/2006-03-01/'>
          <IsTruncated>true</IsTruncated>
          <Contents><Key>prefix/p1.psv</Key><ETag>&quot;abc&quot;</ETag><Size>12</Size></Contents>
          <NextContinuationToken>next-token</NextContinuationToken>
        </ListBucketResult>"""
        objects, token = MODULE.parse_listing(xml)
        self.assertEqual(token, "next-token")
        self.assertEqual(objects[0].key, "prefix/p1.psv")
        self.assertEqual(objects[0].etag, "abc")
        self.assertEqual(objects[0].size, 12)

    def test_transient_timeout_is_retried(self) -> None:
        item = MODULE.S3Object("prefix/p1.psv", 3, "etag")
        with tempfile.TemporaryDirectory() as temporary, patch.object(
            MODULE.urllib.request,
            "urlopen",
            side_effect=[TimeoutError("transient"), io.BytesIO(b"abc")],
        ) as mocked:
            path = MODULE.download_object(
                item, Path(temporary), "prefix/", attempts=2
            )
            self.assertEqual(path.read_bytes(), b"abc")
            self.assertEqual(mocked.call_count, 2)

    def test_tls_context_keeps_verification_enabled(self) -> None:
        self.assertTrue(MODULE.TLS_CONTEXT.check_hostname)
        self.assertEqual(MODULE.TLS_CONTEXT.verify_mode, MODULE.ssl.CERT_REQUIRED)


if __name__ == "__main__":
    unittest.main()
