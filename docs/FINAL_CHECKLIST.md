# Final Checklist (Definition of Done)

## Steps
1. **Bootstrap env**
   ```bash
   python -m venv venv && source venv/bin/activate
   pip install -r requirements.txt
   ```
2. **Unit & Smoke tests**
   ```bash
   pytest -q
   ```
3. **Full validation**
   ```bash
   make bundle-auto
   ```
4. **Soak smoke**
   ```bash
   make soak-smoke
   ```
5. **Morning routine**
   ```bash
   make morning
   ```
6. **Long soak (manual/cron)**
   ```bash
   make soak
   ```
7. **Digest review**
   - check artifacts/digest/*.json
8. **Release dry-run**
   ```bash
   make release-dry VER=vX.Y.Z
   ```
9. **Release**
   ```bash
   make release VER=vX.Y.Z
   git push origin vX.Y.Z
   ```

## Acceptance
- Нет warning по конфигации/логам.
- Все тесты зелёные.
- OPS-доки актуальны.
- Soak отчёты формируются.
- CHANGELOG и релизы работают.
