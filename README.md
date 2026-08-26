# CodeKit OI – 信息学竞赛专用代码工具

> **专为 OI（信息学竞赛）打造的多功能代码管理套件**
> 版本：OI‑v4.3（赛场增强版）
> 支持对拍、评测、静态分析、AI 辅助、算法模板速查、比赛模式……

---

## 🎯 项目简介

CodeKit OI 是一个面向信息学竞赛选手的命令行工具，旨在简化日常编码、调试、测试、提交等重复性工作。它集成了：

- **编译运行**：支持 C/C++、Python、Java、Go、Rust、C#、JavaScript/TypeScript、Shell、Dart、Swift、Ruby 等十余种语言。
- **OI 专用功能**：对拍（Stress）、批量测试（Test）、数据生成（Gen）、计时与内存统计（Time）、本地评测（Judge）、静态代码分析（Scan）。
- **AI 辅助**：自动生成 Git Commit Message、解释代码、修复 Lint 错误、回答编程问题。
- **算法模板速查**：内置线段树、树状数组、KMP、Dinic、Dijkstra、LCA 等常用模板，并支持插入到源码。
- **比赛模式**：实时监控源文件变化，自动保存快照，生成比赛报告。
- **项目构建**：自动识别 CMake / Make / Cargo / npm / Go 项目。
- **环境管理**：环境指纹保存与恢复，自动检测并选用最新 g++ 版本。

无论是日常刷题、模拟赛，还是现场比赛，CodeKit OI 都能为你提供稳定、高效的辅助。

---

## ✨ 主要特性

| 类别 | 功能 | 说明 |
|------|------|------|
| **核心** | `run` / `compile` / `clean` | 编译运行、清理构建产物 |
| | `watch` | 监控文件变化，自动重跑 |
| | `list` / `search` | 列出代码文件、搜索内容 |
| **OI 对拍** | `stress` | 主程序 vs 暴力，支持自动缩反例、浮点容差、SPJ、Sanitizer |
| | `test` | 批量测试，支持 `.cktest` 数据包、SPJ、内存限制 |
| | `gen` | 数据生成器（支持编译型语言和 Python） |
| | `time` | 计时与内存统计，支持火焰图（需 py-spy） |
| **本地评测** | `judge` | 模拟 NOIP/CSP 评分，支持子任务捆绑、SPJ，导出 HTML 报告 |
| **静态分析** | `scan` | 检测 C/C++ 代码中的危险写法（栈溢出、递归无终止、`#define int long long` 等），输出“赛场避坑指南” |
| **AI 增强** | `explain` / `fix` / `ask` / `commit` | 解释代码、修复错误、问答、智能生成 Git Commit |
| **算法模板** | `snippet list` / `get` | 内置常用模板，支持位置插入和变量替换 |
| **竞赛模式** | `contest start` | 启动比赛，自动保存源文件快照，生成报告 |
| **环境管理** | `env check-g++` | 检测最新 g++ 版本并自动配置 |
| | `env save / restore` | 保存/恢复环境指纹，确保环境一致性 |
| **其它** | `copy` / `submit` / `open` / `todo` / `where` / `mood` / `timer` / `diff` | 剪贴板集成、提交代码、打开题目、TODO 管理、符号查找、心情调节、番茄钟、文件差异比较 |

---

## 📦 安装

### 依赖要求

- **Python 3.6+**（推荐 3.8+）
- **pip**（用于安装可选依赖）

### 快速安装

```bash
# 克隆仓库（或直接下载 CodeKit-OI-v4.2.py）
git clone https://github.com/your-repo/codekit-oi.git
cd codekit-oi

# 安装可选依赖（推荐）
pip install pyyaml psutil tqdm requests plyer watchdog py-spy
# 若需使用 online-judge-tools（提交功能）
pip install online-judge-tools
```

### 配置别名

为了方便使用，推荐在 shell 配置中添加别名：

```bash
alias ck='python3 /path/to/CodeKit-OI-v4.2.py'
```

或者将脚本复制到 `$PATH` 中并赋予执行权限：

```bash
chmod +x CodeKit-OI-v4.2.py
sudo cp CodeKit-OI-v4.2.py /usr/local/bin/ck
```

---

## 🚀 快速开始

### 1. 编译并运行 C++ 程序

```bash
ck run main.cpp
```

### 2. 对拍（Stress Testing）

```bash
ck stress main.cpp brute.cpp --gen gen.py --cases 100 --shrink --celebrate
```

- `main.cpp`：你的优化程序
- `brute.cpp`：暴力程序
- `--gen gen.py`：数据生成器（也可以是编译型程序）
- `--cases 100`：生成 100 组数据
- `--shrink`：自动缩小反例数据规模
- `--celebrate`：全部通过时打印彩蛋 🎉

### 3. 批量测试

```bash
ck test main.cpp --input-dir data/in --cktest .cktest --sanitize
```

- 支持 `.cktest` 数据包（JSON/YAML 格式），可配置每个测试点的分值、输入输出文件，以及 SPJ。

### 4. 本地 OI 评测（模拟 NOIP/CSP）

```bash
ck judge --problem-config .codekit-problem.json --source main.cpp --html
```

`.codekit-problem.json` 示例：

```json
{
  "name": "求和",
  "time_limit": 1.0,
  "memory_limit": 256,
  "subtasks": [
    {
      "id": "sub1",
      "score": 30,
      "cases": ["1.in", "2.in"]
    },
    {
      "id": "sub2",
      "score": 70,
      "cases": ["3.in", "4.in", "5.in"]
    }
  ],
  "checker": "checker.cpp"
}
```

### 5. 静态代码检查（赛场避坑指南）

```bash
ck scan .
```

输出常见问题：局部数组过大、递归无终止、`#define int long long`、int 乘法溢出等。

### 6. 算法模板插入

```bash
ck snippet list                       # 查看所有模板
ck snippet get segtree --output main.cpp --insert --position "// @insert_here"
```

### 7. 比赛模式

```bash
ck contest start contest.json --duration 3600 --cfg my_config.json
```

- `--cfg` 可覆盖 `config` 位置参数，支持指定任意路径的 JSON 配置文件。
- 比赛期间源文件每次保存都会自动生成快照，结束后生成报告。

---

## 📚 命令完整参考

### 基础命令

| 命令 | 说明 |
|------|------|
| `run  [args]` | 编译并运行程序 |
| `compile ` | 仅编译，不运行 |
| `clean [--dry-run] [--no-confirm]` | 清理构建产物（.exe, .o, __pycache__ 等） |
| `list [filter]` | 列出当前目录的代码文件 |
| `search ` | 在代码文件中搜索关键词 |
| `new  [--plugin] [--command]` | 创建新文件（带模板）或插件模板 |
| `backup [dst]` | 备份当前项目 |
| `restore ` | 从备份还原 |
| `watch  [--test] [--input-dir] ...` | 监控文件变化，自动重跑/测试 |
| `edit ` | 用默认编辑器打开文件 |
| `terminal` | 启动新终端（自动检测 wezterm, alacritty 等） |
| `chdir [path]` | 切换工作目录 |

### 项目构建与依赖

| 命令 | 说明 |
|------|------|
| `build` | 自动检测 CMake/Make/Cargo/npm/Go 并构建 |
| `deps check` | 查看依赖文件 |
| `deps install` | 安装依赖（pip/npm/go mod/cargo fetch） |
| `fmt ` | 格式化代码（需 clang-format/black/prettier 等） |

### 代码搜索与统计

| 命令 | 说明 |
|------|------|
| `grep ` | 快速搜索（优先使用 rg，fallback 到 grep/findstr） |
| `def ` | 查找符号定义（基于 ctags 或正则） |
| `stats [--by-file]` | 代码行数统计（优先使用 cloc） |
| `where ` | 在当前项目查找符号定义 |

### Git 与版本控制

| 命令 | 说明 |
|------|------|
| `git ` | 安全执行 Git 命令（白名单过滤） |
| `commit` | AI 生成 Commit Message 并提交 |

### 环境管理

| 命令 | 说明 |
|------|------|
| `env list` | 列出环境变量（过滤敏感路径） |
| `env set  ` | 设置环境变量并保存到 .env |
| `env save` | 保存环境指纹（编译器版本、依赖文件哈希等） |
| `env restore` | 检查环境指纹一致性，尝试自动修复 |
| `env check-g++` | 扫描系统 g++ 版本并自动配置最新版 |

### OI 专用命令

| 命令 | 说明 |
|------|------|
| `stress` | 对拍（详细参数见上文） |
| `test` | 批量测试 |
| `gen` | 数据生成器 |
| `time` | 计时与内存统计，支持火焰图 |
| `init [lang]` | 生成 OI 模板（cpp/c/python/java/go/rust） |
| `snippet list / get` | 算法模板速查与插入 |
| `contest start` | 竞赛模式 |
| `judge` | 本地评测机 |
| `scan` | 静态代码分析（赛场避坑指南） |

### AI 辅助

| 命令 | 说明 |
|------|------|
| `explain [file] [--ask ]` | 解释代码或追问问题 |
| `fix [--file]` | 使用 AI 修复 Lint 错误 |
| `ask ` | 向 AI 提问，结合当前上下文 |
| `commit` | 智能生成 Commit Message |

### 其它实用工具

| 命令 | 说明 |
|------|------|
| `copy ` | 复制文件内容到剪贴板 |
| `submit  --problem  --platform ` | 提交代码（需 online-judge-tools） |
| `open  --platform ` | 在浏览器打开题目 |
| `todo [--add] [--list] [--sort-by-date] [--count]` | 管理 TODO/FIXME 注释 |
| `diff   [--ignore-trailing-spaces] [--ignore-blank-lines]` | 文件差异比较 |
| `kill ` | 终止进程（强制） |
| `mood set/get` | 设置/查看心情状态（影响 stress 用例数） |
| `timer [minutes]` | 番茄钟计时 |
| `archive [--format zip/tar] [--output]` | 打包项目 |
| `checksum  [--algo]` | 计算文件哈希 |
| `freeze` | 生成依赖锁文件 |
| `self-test` | 运行自检 |
| `doctor` | 环境诊断 |

---

## 🔧 配置

配置文件位于 `~/.codekit/config.json`（或 `config.yaml`），支持项目级配置（`.codekit/config.json`）。常用配置项：

```json
{
  "ai": {
    "api_key": "your-openai-key",
    "provider": "openai",
    "model": "gpt-4",
    "base_url": null,
    "ollama_url": "http://localhost:11434/api/generate"
  },
  "oi": {
    "default_gpp": "g++-14",
    "timeout": 5,
    "memory_limit_mb": 512,
    "author": "YourName"
  },
  "check": {
    "array_size_warning": 100000,
    "int_overflow_warning": true
  },
  "bench": {
    "iterations": 3,
    "threshold_percent": 20.0
  }
}
```

环境变量覆盖：以 `CODEKIT_` 为前缀的变量可覆盖配置，如 `CODEKIT_AI_KEY` 会覆盖 `ai.api_key`。

---

## 🧩 扩展开发

CodeKit OI 支持**语言插件**和**命令插件**，方便自定义功能。

### 语言插件（扩展新语言）

1. 在 `~/.codekit/plugins/` 下创建 Python 文件。
2. 继承 `LanguageHandler` 或 `CompiledLanguageHandler`，实现 `run`、`compile` 等方法。
3. 注册 `Handler` 类。
4. 重启 CodeKit 或执行 `ck plugin reload`。

### 命令插件（添加新子命令）

1. 在 `~/.codekit/commands/` 下创建 Python 文件。
2. 继承 `CommandPlugin`，实现 `get_parser` 和 `run` 方法。
3. 注册 `Handler` 类（无需额外操作，自动加载）。

### 创建插件模板

```bash
ck new my_lang --plugin      # 生成语言插件模板
ck new my_cmd --command      # 生成命令插件模板
```

---

## 🧪 测试与自检

运行自检以确认环境正常：

```bash
ck self-test
```

会检查配置加载、插件注册、服务容器、基本运行等功能。

---

## 🤝 贡献

欢迎提交 Issue 或 Pull Request。
项目遵循 MIT 许可证，详见 [LICENSE](LICENSE)。

---

## 📄 许可证

MIT License © 2026 CodeKit Contributors

---

## 📞 联系与反馈

- 作者：Teto & Miku （代码中埋有彩蛋 🎵）
- 建议通过 GitHub Issue 反馈问题。

---

**Happy Coding & AC Everywhere!**
`Nee~! 今天也要加油哦！`
# **现为4.3版本,文档正在书写**
