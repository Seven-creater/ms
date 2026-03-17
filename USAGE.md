# ModelScope Download Skill 使用说明

## 1. 目标
本 Skill 的 V1 目标是通过对话/命令完成四项核心能力：
1. 模型检索
2. 数据集检索
3. 模型下载
4. 数据集下载

并支持一个补充能力：输入检索 `query` 后，返回结果列表及每个仓库的主页内容（`README.md`）。

---

## 2. 文件结构

```text
modelscope-download/
├─ SKILL.md
├─ USAGE.md
├─ agents/openai.yaml
├─ scripts/mshub.py
└─ references/
   ├─ capability-mapping.md
   └─ claude-migration.md
```

---

## 3. 运行前准备

### 3.1 Python 依赖
- `python>=3.9`（本地已在 Python 3.13 测试）
- `modelscope`（推荐 `1.35.0`，兼容低版本）
- `requests`

示例安装：

```bash
python -m pip install modelscope requests
```

### 3.2 Token（可选）
公开资源检索/下载通常不需要 token。  
若访问私有/受限资源，可设置：

```bash
set MODELSCOPE_API_TOKEN=your_token
```

---

## 4. 快速开始

进入目录后执行：

```bash
python scripts/mshub.py --help
```

主命令：

```bash
python scripts/mshub.py model search ...
python scripts/mshub.py dataset search ...
python scripts/mshub.py model download ...
python scripts/mshub.py dataset download ...
```

支持 `--json` 结构化输出（可放在命令任意位置）：

```bash
python scripts/mshub.py --json model search -q qwen --top 3
python scripts/mshub.py model search -q qwen --top 3 --json
```

---

## 5. 四项核心能力用法

## 5.1 模型检索

```bash
python scripts/mshub.py --json model search -q qwen --top 5
```

常用参数：
- `-q/--query`：关键词
- `--owner`：限定作者/组织
- `--page`、`--size`：分页
- `--top`：最终返回条数

## 5.2 数据集检索

```bash
python scripts/mshub.py --json dataset search -q alpaca --top 5
```

参数同模型检索。

## 5.3 模型下载

```bash
python scripts/mshub.py --json model download --repo-id Qwen/Qwen3-8B --local-dir ./downloads/model
```

可选过滤（按文件模式）：

```bash
python scripts/mshub.py --json model download --repo-id Qwen/Qwen3-8B --include README.md --local-dir ./downloads/model-readme
```

## 5.4 数据集下载

```bash
python scripts/mshub.py --json dataset download --repo-id AI-ModelScope/alpaca-gpt4-data-zh --local-dir ./downloads/dataset
```

可选过滤：

```bash
python scripts/mshub.py --json dataset download --repo-id AI-ModelScope/alpaca-gpt4-data-zh --include README.md --local-dir ./downloads/dataset-readme
```

---

## 6. Query + 结果 + README（主页内容）

## 6.1 CLI 方式
在检索命令中加 `--with-readme`：

```bash
python scripts/mshub.py --json model search -q qwen --top 3 --with-readme
python scripts/mshub.py --json dataset search -q alpaca --top 3 --with-readme
```

结果中会附加：
- `homepage.path`
- `homepage.content`
- `homepage.content_preview`
- `homepage.content_length`

## 6.2 Python 函数方式（你提的场景）

```python
from scripts.mshub import search_with_readme

# 模型侧
model_result = search_with_readme(
    "qwen",
    entity="model",
    top=5,
    include_readme=True,
)

# 数据集侧
dataset_result = search_with_readme(
    "alpaca",
    entity="dataset",
    top=5,
    include_readme=True,
)
```

---

## 7. 输出与错误处理

## 7.1 输出
默认输出：可读文本。  
`--json` 输出：结构化 JSON，便于对话代理或程序消费。

## 7.2 常见错误
- `invalid_repo_id`：`repo_id` 格式不正确（应为 `owner/name`）
- `network_error`：网络/endpoint 不可达
- `*_download_failed`：下载失败（可能是网络、权限、版本差异）

每个错误都带有 `next_step` 建议字段。

---

## 8. 版本与兼容策略

- 推荐版本：`modelscope==1.35.0`
- 当前实现兼容低版本（已在较低版本环境验证主链路）
- 脚本会做能力探测并返回 `runtime.capabilities`
- 不自动修改全局 Python 环境

---

## 9. V1 边界（明确不做）

以下不属于当前交付主线：
- create（模型/数据集创建）
- upload-file / upload-folder
- delete-repo / delete-files
- 删除确认流
- 全量 Hub 运维能力

---

## 10. 一句话总结（可直接发导师）

该 Skill 已实现并验证 ModelScope 的 V1 四项能力（模型检索、数据集检索、模型下载、数据集下载），并额外支持“输入 query 后同时返回检索结果与仓库 README 主页内容”的统一接口，输出可读文本与 JSON 两种格式，兼容低版本且不强制改造全局环境。
