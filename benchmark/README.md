# Benchmark 测试集 — 标准化评估用例

每个技能配备基准测试用例，版本迭代后自动运行，量化得分变化。

## 测试用例组织

```
benchmark/
├── video/
│   ├── script.create.json
│   ├── voice.generate.json
│   └── video.compose.json
├── mlops/
│   └── model.search.json
├── investment/
│   ├── data.fetch.json
│   └── fund.diagnose.json
└── results/
    └── <timestamp>_<skill>_benchmark.json
```

## 测试用例格式

```json
{
  "skill_name": "script.create",
  "test_cases": [
    {
      "test_id": "basic_generation",
      "description": "从主题生成基础脚本",
      "input": {
        "source": "道氏理论",
        "source_type": "topic"
      },
      "expected_output_schema": {
        "required": ["title", "scenes"]
      },
      "expected_pass_score": 75
    }
  ]
}
```
