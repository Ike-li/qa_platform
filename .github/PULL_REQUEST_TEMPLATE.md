## 这个 PR 做了什么

<!-- 一两句说清改动和原因。「为什么」比「做了什么」更重要，后者看 diff 就行。 -->

## 验证

<!-- 贴实际跑过的命令和输出，不要只写「测试通过」。 -->

```
# 例：
# .venv/bin/pytest tests/unit -q
# RUN_INTEGRATION_TESTS=1 .venv/bin/pytest tests/integration -q
```

## 检查项

- [ ] 本地依赖已与 CI 对齐：`uv pip install -e '.[dev]' --upgrade`
- [ ] `ruff check src tests scripts` 通过
- [ ] 新增/改动的行为有对应测试
- [ ] 改了 `pyproject.toml` 的依赖 → 已跑 `uv lock` 并提交 `uv.lock`
- [ ] 改了 ORM schema → 已跑 `alembic check`
- [ ] 改了前端 → `npm run build` 与 `npm run lint -- --max-warnings=0` 通过

## 未验证的部分

<!-- 明确写出你知道自己没测到的地方。留空比写假的好，写「无」也可以。 -->
