# Continuous integration

Workflow: `.github/workflows/validate.yml`.

- Triggers: pushes and pull requests for `main` and `dev`, plus manual dispatch.
- Spec revision: the workflow receives the full immutable `${{ github.sha }}`
  for its own checkout and rejects any mismatch before vector execution.
- Validation matrix: `windows-latest`, `ubuntu-latest`, and `macos-latest`.
- Toolchain: the latest stable Python 3 release available to `setup-python`.
- SDK conformance and interop belong to each SDK repository; this repository
  does not check out or orchestrate mutable revisions of downstream SDKs.
- Negative gates: wrong spec SHA, mandatory skip, failed case, missing check,
  incomplete report, and cleanup failure.
- Timeout: 10 minutes per job.
- Artifacts: three spec reports and negative-gate evidence, retained for 14 days.

Local spec validation:

```powershell
$specSha = git -C yuumi-spec rev-parse HEAD
python yuumi-spec/conformance/spec_ci.py --spec-sha $specSha --output-dir artifacts/spec
python yuumi-spec/conformance/report_tool.py artifacts/spec/report.json
```

Across the organization there are 12 engine cells: four engine repositories
times three operating systems. Each cell gates its 25 conformance checks and
seven interop checks and uploads its own machine-readable report.
