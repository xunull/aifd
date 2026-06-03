# Release process

How `aifd` gets a new version onto PyPI.

The release pipeline lives in `.github/workflows/release.yml`. It fires on
`v*` tag pushes and runs four jobs in series:

```
build   →   publish-to-testpypi   →   publish-to-pypi   →   github-release
```

`build` enforces a version-consistency gate (tag must match
`pyproject.toml`'s `version`). TestPyPI catches broken wheels before they
poison the real PyPI index. The GitHub Release page is built from the
matching `## [x.y.z]` section in `CHANGELOG.md`.

## One-time setup

These three steps configure the credentials and gating that the workflow
expects. Do them once before the first release; subsequent releases reuse
the configuration.

### 1. Pending Trusted Publisher on PyPI

`pypa/gh-action-pypi-publish` uses OIDC instead of API tokens. PyPI must
know which GitHub workflow is allowed to publish under the `aifd` project
name. Because the project doesn't exist on PyPI yet, register a *pending*
publisher.

1. Sign in at https://pypi.org/manage/account/publishing/
2. Click **Add a new pending publisher**
3. Fill in:
   - **PyPI project name:** `aifd`
   - **Owner:** `xunull`
   - **Repository name:** `aifd`
   - **Workflow filename:** `release.yml`
   - **Environment name:** `pypi`
4. Save. The entry should appear in *Your pending publishers*.

After the first successful release, PyPI converts the pending publisher
into a real one tied to the live project.

### 2. Pending Trusted Publisher on TestPyPI

Same as above, but on https://test.pypi.org/manage/account/publishing/.

- **Project name:** `aifd`
- **Owner / repo / workflow:** same as PyPI
- **Environment name:** `testpypi`

TestPyPI is a separate registry with its own login.

### 3. GitHub repository environments

The publish jobs reference two GitHub Environments. They must exist on the
repository before the first release, otherwise the jobs stall with
*"Required environment does not exist"*.

Open https://github.com/xunull/aifd/settings/environments and create:

- **`testpypi`** — no protection rules. Auto-deploys.
- **`pypi`** — add a **Required reviewers** rule listing yourself
  (`xunull`). This puts a human-gated approval step in front of the real
  PyPI publish, so a mistaken tag or broken wheel still has a chance to be
  caught.

## Cutting a release

Once setup is done, a release is three commands:

```bash
# 1. Make sure pyproject.toml and aifd/__init__.py both say the new version.
#    The build job will fail fast if they disagree with the tag.
grep '^version' pyproject.toml
grep '__version__' aifd/__init__.py

# 2. Update CHANGELOG.md with a new `## [x.y.z] - YYYY-MM-DD` section.
#    The GitHub Release page is built from this section.

# 3. Tag and push.
git tag v$(grep '^version' pyproject.toml | sed -E 's/^version *= *"([^"]+)".*/\1/') main
git push origin --tags
```

Watch the run at https://github.com/xunull/aifd/actions. Sequence:

| Stage | What you should see |
|---|---|
| `build` | passes the version gate, builds `aifd-x.y.z-py3-none-any.whl` and the sdist |
| `publish-to-testpypi` | uploads to https://test.pypi.org/project/aifd — verify the page renders |
| `publish-to-pypi` | shows **"awaiting review"** on the Actions run; click **Review pending deployments** → **Approve** |
| `github-release` | creates the tagged Release with the CHANGELOG section as the body |

After approval the PyPI upload happens and `pipx install aifd` works for
everyone.

## Smoke test after release

In a clean environment (a fresh shell, fresh dir):

```bash
pipx install aifd                    # or uvx aifd ai session list
aifd --version                       # should match the tag
aifd ai session list --help
aifd ai claude skill list --json | jq '.[0]'
```

If any of these fail, **do not retry the same tag**. PyPI refuses to
overwrite a version. Bump to the next patch (e.g. `0.2.2`), fix, retag.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `build` fails with `Tag vX.Y.Z does not match pyproject version` | `pyproject.toml` or `aifd/__init__.py` not updated. Bump them, force-delete the tag locally and remote, retag. |
| `publish-to-pypi` shows 401 from PyPI | Trusted Publisher entry on pypi.org not configured or the environment name mismatches (`pypi`). |
| `publish-to-testpypi` shows 401 from TestPyPI | Same as above, but the entry must live on test.pypi.org. |
| Action stuck on *"waiting for review"* | GitHub Environment `pypi` requires a reviewer — open the run and approve. |
| GitHub Release body is empty / placeholder | `CHANGELOG.md` has no `## [x.y.z]` heading matching the tag. Add the section and re-run the workflow (won't republish PyPI, but will recreate the Release). |
| PyPI says the version already exists | You can't republish. Bump to the next patch and retag. |

## Why the chain has TestPyPI in the middle

PyPI is permanent: it refuses to re-upload the same version and refuses
to delete a version (yanking only hides it). A broken wheel that reaches
PyPI is a broken wheel that's there forever. TestPyPI lets us catch:

- missing files in the wheel (forgot to include `docs/` or similar)
- wrong package metadata (typo in classifier, wrong license tag)
- entry-point bugs (`aifd` command not in `PATH` after install)
- platform incompatibility (Python version constraint wrong)

`publish-to-pypi` `needs: publish-to-testpypi`, so a TestPyPI failure
halts the chain before the real PyPI upload runs.
