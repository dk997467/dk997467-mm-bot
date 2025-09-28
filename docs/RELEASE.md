# Release process

1. Ensure CI is green and READY-gate passes:

```
make bundle-auto
```

2. Prepare version and run dry-run:

```
make release-dry VER=v0.1.0
```

3. Create tag and write CHANGELOG file:

```
make release VER=v0.1.0
git push origin v0.1.0
```

Artifacts (bundle/digest/soak reports) remain locally; attach to releases as needed.
