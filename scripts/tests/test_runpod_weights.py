import datetime, importlib.util, io, pathlib, unittest, unittest.mock

HERE = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("runpod_weights", HERE / "runpod-weights.py")
rw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rw)


class SigV4(unittest.TestCase):
    def test_aws_get_object_example(self):
        # The "GET Object" example of the AWS S3 docs ("Signature Calculations for the Authorization Header").
        empty = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        h = rw.sign_v4("GET", "examplebucket.s3.amazonaws.com", "/test.txt", {}, {"range": "bytes=0-9"}, empty,
                       "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY", "us-east-1",
                       datetime.datetime(2013, 5, 24, tzinfo=datetime.timezone.utc))
        self.assertEqual(h["Authorization"],
                         "AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20130524/us-east-1/s3/aws4_request, "
                         "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date, "
                         "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
        self.assertNotIn("host", h)  # urllib sets Host itself
        self.assertEqual(h["x-amz-date"], "20130524T000000Z")


class Copy(unittest.TestCase):
    def test_to_copy_skips_same_size(self):
        objects = [("asr/model.safetensors", 10), ("aligner/config.json", 3), ("pyannote/x.bin", 5)]
        sizes = {"asr/model.safetensors": 10, "aligner/config.json": 2}  # pyannote/x.bin is missing
        self.assertEqual(rw.to_copy(objects, sizes), [("aligner/config.json", 3), ("pyannote/x.bin", 5)])

    def test_ranges(self):
        self.assertEqual(rw.ranges(7, part=3), [(0, 2), (3, 5), (6, 6)])
        self.assertEqual(rw.ranges(6, part=3), [(0, 2), (3, 5)])
        self.assertEqual(rw.ranges(0, part=3), [])

    def test_retry_gives_up_after_tries(self):
        calls = []

        def boom():
            calls.append(1)
            raise ConnectionError("reset")

        with unittest.mock.patch.object(rw.time, "sleep"), self.assertRaises(ConnectionError):
            rw.retry(boom, "x")
        self.assertEqual(len(calls), rw.TRIES)

    def test_s3_host_and_gs_split(self):
        self.assertEqual(rw.S3("EU-RO-1", "vol1", "a", "s").host, "s3api-eu-ro-1.runpod.io")
        self.assertEqual(rw.split_gs("gs://p-models/stt-a-qwen3-asr-diar/"), ("p-models", "stt-a-qwen3-asr-diar/"))
        self.assertEqual(rw.split_gs("gs://p-models/x"), ("p-models", "x/"))

    def test_complete_xml(self):
        self.assertEqual(rw.complete_xml(['"e1"', '"e2"']),
                         b'<CompleteMultipartUpload><Part><PartNumber>1</PartNumber><ETag>"e1"</ETag></Part>'
                         b'<Part><PartNumber>2</PartNumber><ETag>"e2"</ETag></Part></CompleteMultipartUpload>')

    def test_upload_id_from_xml(self):
        xml = b'<InitiateMultipartUploadResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/"><UploadId>u1</UploadId></InitiateMultipartUploadResult>'
        self.assertEqual(rw._xml_text(xml, "UploadId"), "u1")


class Cloud(unittest.TestCase):
    def test_cloud_config_reads_the_keys_from_secret_manager(self):
        with unittest.mock.patch.dict(rw.os.environ, {"GCP_PROJECT_ID": "p"}):
            c = rw.cloud_config({"dir": "d", "volumes": [{"id": "vol1", "data_center": "EU-RO-1"},
                                                         {"id": "vol2", "data_center": "EU-CZ-1"}]}, "gs://p-models/d/", False)
        step = c["steps"][0]
        self.assertEqual(step["args"], ["-u", "runpod-weights.py", "--volume-id", "vol1", "--data-center", "EU-RO-1",
                                        "--dir", "d", "--source", "gs://p-models/d/"])
        self.assertEqual([s["args"][3] for s in c["steps"]], ["vol1", "vol2"])  # 1 step per volume
        self.assertTrue(all(s["waitFor"] == ["-"] for s in c["steps"]))  # at the same time
        self.assertEqual(step["secretEnv"], ["RUNPOD_S3_ACCESS_KEY", "RUNPOD_S3_SECRET_KEY"])
        self.assertEqual([s["versionName"] for s in c["availableSecrets"]["secretManager"]],
                         ["projects/p/secrets/runpod-s3-access-key/versions/latest",
                          "projects/p/secrets/runpod-s3-secret-key/versions/latest"])
        self.assertNotIn("user_", str(c))  # no key in the config


class FakeS3(rw.S3):
    """Records the calls. The 2nd part fails."""

    def __init__(self):
        super().__init__("EU-RO-1", "vol1", "a", "s")
        self.calls = []

    def call(self, method, key, query=None, body=b"", headers=None):
        self.calls.append((method, dict(query or {})))
        if query and query.get("partNumber") == 2:
            raise OSError("network")
        r = io.BytesIO(b"<R><UploadId>u1</UploadId></R>")
        r.headers = {"ETag": '"e"'}
        return r


class Multipart(unittest.TestCase):
    def test_failed_part_aborts_the_upload(self):
        s3 = FakeS3()
        with self.assertRaises(OSError):
            s3.multipart("d/f", iter([b"a", b"b"]))
        self.assertEqual([c[0] for c in s3.calls], ["POST", "PUT", "PUT", "DELETE"])
        self.assertEqual(s3.calls[-1][1], {"uploadId": "u1"})


class FlakyS3(FakeS3):
    """Part 1 fails once with a connection error, then works."""

    def call(self, method, key, query=None, body=b"", headers=None):
        if query and query.get("partNumber") == 1 and not any(c[1].get("partNumber") == 1 for c in self.calls):
            self.calls.append((method, dict(query)))
            raise ConnectionError("broken pipe")
        return super().call(method, key, query, body, headers)


class Retry(unittest.TestCase):
    def test_part_is_sent_again_after_a_connection_error(self):
        s3 = FlakyS3()
        with unittest.mock.patch.object(rw.time, "sleep"):
            s3.multipart("d/f", iter([b"a"]))
        self.assertEqual([c[0] for c in s3.calls], ["POST", "PUT", "PUT", "POST"])


if __name__ == "__main__":
    unittest.main()
