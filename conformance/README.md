# Executable conformance harness

`harness.py` validates one SDK on one operating system. It runs that SDK's
canonical conformance suite and, for an engine, the real Go-to-engine scenarios.
It never downloads dependencies or checks out repositories.

```text
<root>/yuumi-spec
<root>/Yuumi
<root>/<selected-engine-repository>
```

Only the selected SDK, `yuumi-spec`, and `Yuumi` for engine interop are
required. Dependencies and build outputs must already exist. A complete local
Windows Python cell is:

```powershell
$specSha = git -C yuumi-spec rev-parse HEAD
python yuumi-spec/conformance/harness.py `
  --repositories-root . `
  --spec-sha $specSha `
  --platform windows `
  --sdk python `
  --stage all `
  --output-dir artifacts/python
python yuumi-spec/conformance/report_tool.py artifacts/python/report.json
```

For C++, add `--cpp-build-dir <directory>` and, for a multi-configuration
Windows build, `--cpp-configuration Debug` or `Release`.

## Report and exit codes

Every expected check is enumerated before execution. The versioned JSON report
records the platform, architecture, toolchains, available repository commits,
spec SHA, per-case state, log path, duration, cleanup diagnostics, summary,
and `complete` flag.

- `0`: every expected result passed and cleanup passed;
- `1`: a test or cleanup failed;
- `2`: configuration, repository layout, spec SHA, or toolchain is invalid;
- `3`: a mandatory case is skipped, not run, missing, or the report is incomplete.

GitHub Actions owns the 12 real engine cells: four engine repositories on three
operating systems. The 25 conformance cases and seven interop scenarios are
checks inside a cell, not another matrix dimension.

## Negative gates

Run the deterministic gate tests with:

```powershell
python -m unittest discover -s yuumi-spec/conformance -p "test_*.py" -v
python yuumi-spec/conformance/report_tool.py --self-test
```

The tests prove that failure, mandatory skip, missing checks, and cleanup
failure cannot produce exit code zero or `complete: true`. `spec_ci.py` also
returns configuration exit code `2` for an incorrect full spec SHA.
