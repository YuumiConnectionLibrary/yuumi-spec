import importlib.util
import os
import pathlib
import sys
import tempfile
import unittest


MODULE_PATH = pathlib.Path(__file__).with_name("harness.py")
SPEC = importlib.util.spec_from_file_location("yuumi_harness", MODULE_PATH)
HARNESS = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(HARNESS)
class HarnessTests(unittest.TestCase):
    def test_go_parser_maps_combined_cases_and_skip(self):
        output = "\n".join(
            [
                '{"Action":"pass","Test":"TestCC005AndCC008ListeningState"}',
                '{"Action":"skip","Test":"TestCC009Negotiation"}',
            ]
        )
        self.assertEqual(
            HARNESS.parse_go_conformance(output),
            {"CC-005": "pass", "CC-008": "pass", "CC-009": "skip"},
        )

    def test_text_parser_maps_all_supported_runner_styles(self):
        output = "\n".join(
            [
                "test test_ec_001_configuration ... ok",
                "test ec_002_address ... FAILED",
                "ok 3 - EC-003 native dialer",
                "4/4 Test #4: yuumi_EC-004 .... Not Run",
                "test_ec_005_write_failure ... ok",
            ]
        )
        self.assertEqual(
            HARNESS.parse_text_conformance(output),
            {
                "EC-001": "pass",
                "EC-002": "fail",
                "EC-003": "pass",
                "EC-004": "skip",
                "EC-005": "pass",
            },
        )

    def test_interop_parser_rejects_missing_scenarios_by_omission(self):
        manifest = {
            "cases": [
                {"id": "INT-001", "test": "first"},
                {"id": "INT-002", "test": "second"},
            ]
        }
        statuses = HARNESS.parse_interop(
            "--- PASS: TestGoEngineInterop/first (0.01s)", manifest
        )
        self.assertEqual(statuses, {"INT-001": "pass"})
        self.assertNotIn("INT-002", statuses)

    def test_exit_codes_distinguish_failure_and_incomplete(self):
        report = {
            "expected_checks": [{}],
            "results": [{"status": "pass"}],
            "cleanup": {"status": "pass"},
            "summary": {"pass": 0, "fail": 0, "skip": 0, "not-run": 0, "total": 0},
            "complete": False,
        }
        HARNESS.finalize_report(report)
        self.assertEqual(HARNESS.report_exit_code(report), 0)
        report["results"][0]["status"] = "skip"
        HARNESS.finalize_report(report)
        self.assertEqual(HARNESS.report_exit_code(report), 3)
        report["results"][0]["status"] = "fail"
        HARNESS.finalize_report(report)
        self.assertEqual(HARNESS.report_exit_code(report), 1)
        report["results"][0]["status"] = "pass"
        report["cleanup"]["status"] = "fail"
        HARNESS.finalize_report(report)
        self.assertEqual(HARNESS.report_exit_code(report), 1)

    def test_timeout_terminates_the_owned_process_group(self):
        with tempfile.TemporaryDirectory() as directory:
            log = pathlib.Path(directory) / "timeout.log"
            code, output, duration, timed_out = HARNESS.run_command(
                [sys.executable, "-c", "import time; time.sleep(30)"],
                pathlib.Path(directory),
                os.environ.copy(),
                0.1,
                log,
            )
            log_exists = log.is_file()
        self.assertTrue(timed_out)
        self.assertIn("HARNESS TIMEOUT", output)
        self.assertTrue(log_exists)


if __name__ == "__main__":
    unittest.main()


"""
These tests exercise result normalization and the negative gates without
requiring language toolchains or mutating any SDK checkout.
"""
