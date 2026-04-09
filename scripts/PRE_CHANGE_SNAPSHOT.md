# Pre-change Snapshot (Windows / PowerShell)

Create a backup branch + tag before risky edits, so you can restore quickly.

## Run

From repo root:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pre_change_snapshot.ps1 -Label "before-big-edit"
```

This creates:

- branch: `snapshot/<timestamp>-before-big-edit`
- tag: `snapshot-<timestamp>-before-big-edit`

And pushes both to `origin`.

## Options

- Custom remote:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pre_change_snapshot.ps1 -Label "before-hotfix" -Remote origin
```

- Create locally only (no push):

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\pre_change_snapshot.ps1 -Label "local-test" -NoPush
```

## Restore

```powershell
git checkout <snapshot-branch>
# or
git checkout <snapshot-tag>
```
