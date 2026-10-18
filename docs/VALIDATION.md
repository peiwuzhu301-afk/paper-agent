# Validation notes

## 已在交付环境完成

- Python 源码 `compileall` / AST 语法检查
- 项目 ZIP 完整性检查
- 纯逻辑单测已执行：`4 passed`（hash embedding、mock agent、report evaluator）
- 默认配置支持 zero-key / sample 模式

## 当前交付环境限制

交付沙箱未预装 `langgraph`、`chromadb`、`autogen-agentchat` 等运行依赖；尝试 `pip install` 时沙箱 DNS 无法访问 PyPI，因此无法在这里完成真实依赖安装后的 API E2E。项目把版本写入 `pyproject.toml`，你本机联网执行 `scripts/setup.*` 后即可安装。

## 推荐你本机执行

```bash
paper-agent doctor
pytest -q
paper-agent demo
paper-agent serve
```

再开 Vue：

```bash
cd frontend
npm run dev
```

## 关于简历指标

这个仓库没有把“Top-5 82%、解析率 90%、8 分钟、人工 4.1/5”等数字硬编码成结果。真正求职使用时，请用你自己的 benchmark 数据和人工评分产生可复现实验结果，再写回简历。
