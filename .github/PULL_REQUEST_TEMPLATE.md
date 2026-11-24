## Summary

<!-- Briefly describe what this PR changes and why. -->

## Type of Change

- [ ] Bug fix
- [ ] New feature
- [ ] Privacy / PII redaction rule
- [ ] Refactor / performance optimization
- [ ] Documentation / Compatibility matrix
- [ ] Packaging / CI

## Checklist

- [ ] Preserves **100% offline, 0 MB VRAM** local-first architecture (zero telemetry or cloud calls)
- [ ] `QT_QPA_PLATFORM=offscreen pytest -v` passes locally
- [ ] `ruff check .` passes with zero errors
- [ ] Updated bilingual EN/TR strings (`i18n.py`) and `CHANGELOG.md` if applicable
