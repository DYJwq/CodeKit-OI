# CodeKit OI 特供版 v5.2 — README

> 专为信息学竞赛（OI）设计的代码管理工具
> 版本：**OI-v5.2** ｜ 作者：DYJwq(github)

---

## 目录

- [一、项目简介](#一项目简介)
- [二、环境要求与安装](#二环境要求与安装)
- [三、快速开始](#三快速开始)
- [四、命令速查总表](#四命令速查总表)
- [五、核心命令详解](#五核心命令详解)
  - [1. 运行与编译](#1-运行与编译)
  - [2. 对拍（stress）](#2-对拍stress)
  - [3. 批量测试（test）](#3-批量测试test)
  - [4. 本地评测机（judge）](#4-本地评测机judge)
  - [5. 数据生成（gen）](#5-数据生成gen)
  - [6. 交互题（interact）](#6-交互题interact)
  - [7. 计时与性能（time / bench）](#7-计时与性能time--bench)
  - [8. 提交前防雷（polish / scan / check）](#8-提交前防雷polish--scan--check)
  - [9. 统一失败库（failures）](#9-统一失败库failures)
  - [10. 崩溃日志（anal_log）](#10-崩溃日志anal_log)
- [六、配置系统](#六配置系统)
- [七、插件系统](#七插件系统)
- [八、AI 服务](#八ai-服务)
- [九、外部工具集成](#九外部工具集成)
- [十、进阶主题](#十进阶主题)
- [十一、版本演进](#十一版本演进)
- [十二、常见问题 FAQ](#十二常见问题-faq)

---

## 一、项目简介

**CodeKit OI** 是一个面向信息学竞赛选手的一体化命令行工具箱。它把 OI 备赛与比赛期间的常用操作（编译、对拍、数据生成、评测、性能测试、OJ 提交、代码抛光、崩溃分析等）整合到单一 `ck` 命令下，并提供插件化的语言 / 命令扩展机制。

### 主要特性

| 类别 | 功能 |
|---|---|
| **编译运行** | C / C++ / Python 内建支持，可插拔多语言扩展 |
| **对拍** | 支持 ddmin 增量调试自动缩小反例、并行、Sanitizer、浮点容差、SPJ、AI 自动生成三件套 |
| **评测** | 本地 OI / IOI / ACM 赛制模拟，支持子任务、HTML 报告、JSON 输出、内存限制 |
| **交互题** | 编译选手程序与交互器，由交互器负责通信（v5.2 新增） |
| **数据生成** | 随机种子控制、批量生成、AI 生成生成器 |
| **失败库** | 统一归档编译错误 / WA 反例 / RE 现场，支持重试与追溯 |
| **提交防雷** | 自动注释 `freopen`、删除调试输出、检查 `#define int long long` |
| **性能** | 计时 / 内存 / 火焰图 / 基准回归追踪 |
| **OJ 集成** | 提交、打开题目、快速提交、批量提交 |
| **AI 辅助** | 代码解释、错误诊断、commit message、生成测试、修复 Lint |
| **可扩展** | 语言插件（Python）、命令插件、CommandFormat 别名系统 |

### 已移除（纪念）

- `ck fetch`：享年 12 个小版本，死于 v5.0，安葬于 v5.1
- `ck upgrade`：享年 12 个小版本，死于 v5.0，安葬于 v5.1

可用 `ck rip` 进行纪念。

---

## 二、环境要求与安装

### 基础要求

- Python **3.6+**（推荐 3.10+）
- 操作系统：Windows / Linux / macOS

### 可选依赖（按需安装）

| 库/工具 | 用途 | 安装方式 |
|---|---|---|
| `yaml` (PyYAML) | YAML 配置文件 | `pip install pyyaml` |
| `psutil` | Windows 下内存统计 | `pip install psutil` |
| `requests` | 在线拉取（部分功能） | `pip install requests` |
| `tqdm` | 进度条 | `pip install tqdm` |
| `plyer` | 桌面通知 | `pip install plyer` |
| `watchdog` | 高效文件监控（否则轮询） | `pip install watchdog` |
| `py-spy` | 火焰图 / top 采样 | `pip install py-spy` |
| `online-judge-tools` (`oj`) | OJ 提交 | `pip install online-judge-tools` |
| `clang-format` | C/C++ 格式化 | 系统包管理器 |
| `black` | Python 格式化 | `pip install black` |
| `cloc` | 代码统计 | 系统包管理器 |
| `ctags` | 符号索引 | 系统包管理器 |
| `gdb` / `lldb` | 调试器 | 系统包管理器 |


### 配置目录

首次运行会自动创建：

```
~/.codekit/
├── config.json          # 全局配置（JSON）
├── config.yaml          # 全局配置（YAML，优先于 JSON）
├── templates/           # 模板目录
├── plugins/
│   ├── available/       # 可用语言插件
│   └── enabled/         # 已启用语言插件
├── commands/            # 命令插件
├── snippets/            # 算法模板
├── contests/            # 比赛记录
├── snapshots/           # 快照
├── cache/fetch/         # 缓存
└── logs/                # 崩溃日志
```

---

## 三、快速开始

```bash
# 打印帮助
ck

# 打印版本
ck --version

# 初始化 OI C++ 模板
ck init cpp

# 编译 + 运行
ck run main.cpp

# 无配置对拍（自动检测 data/in 或 data）
ck test main.cpp

# 使用 AI 自动生成暴力 & 生成器并对拍
ck stress main.cpp --auto --cases 100 --shrink

# 本地评测（无配置文件，自动检测）
ck judge --source main.cpp

# 生成代码并用 Python 打包成 EXE
ck pyexe main.py

# AI 解释代码
ck explain main.cpp --ask "这段代码的时间复杂度？"

# 用调试器打开
ck debug main.cpp
```

---

## 四、命令速查总表

| 命令 | 别名 | 功能 |
|---|---|---|
| `run` | — | 运行源文件 |
| `compile` | — | 仅编译 |
| `clean` | — | 清理构建产物 |
| `list` | `ls` | 列出当前目录代码文件 |
| `search` | — | 搜索代码内容 |
| `new` | — | 创建新文件（含模板）或插件模板 |
| `backup` | — | 备份当前目录 |
| `restore` | `back` | 从备份还原 |
| `git` | — | 执行 Git 白名单命令 |
| `watch` | — | 监控文件变化自动重跑 |
| `pyexe` | — | PyInstaller 打包 |
| `todll` | — | .cs / .cpp 打包为 DLL |
| `chdir` | `cd` | 切换工作目录 |
| `config` | — | 查看 / 修改配置 |
| `shell` | `interactive` | 交互模式 |
| `build` | — | 项目构建（CMake/Make/Cargo/npm/Go） |
| `deps` | — | 依赖管理（check / install） |
| `fmt` | — | 代码格式化 |
| `grep` | — | 全文搜索（ripgrep / grep / findstr） |
| `def` | — | 查找符号定义（ctags / 正则） |
| `stats` | — | 代码统计（cloc / 内置） |
| `debug` | — | 启动调试器 |
| `plugin` | — | 插件管理（list / install / reload） |
| `test` | — | 批量测试 / 生成单元测试 |
| `terminal` | — | 启动新终端 |
| `edit` | — | 默认编辑器打开文件 |
| `task` | — | 执行自定义任务（`.codemanager` 中 [tasks]） |
| `env` | — | 环境管理（list / set / save / restore / check-g++） |
| `kill` | — | 终止进程 |
| `lint` | — | 静态代码检查 |
| `init` | — | 生成 OI 模板 |
| `commit` | — | AI 生成 commit message |
| `checksum` | — | 计算文件哈希 |
| `freeze` | — | 生成依赖哈希锁文件 |
| `archive` | — | 打包项目（zip / tar） |
| `explain` | — | AI 解释代码 |
| `fix` | — | AI 修复 Lint 错误 |
| `self-test` | — | 运行自检 |
| `failures` | — | 统一失败库（list / show / retry） |
| `import` | — | 导入命令模块 |
| `stress` | — | 对拍 |
| `time` | — | 计时 / 内存 / 火焰图 |
| `gen` | — | 数据生成 |
| `snippet` | — | 算法模板速查与插入 |
| `contest` | — | 竞赛模式 |
| `check` | — | 静态代码质量预检 |
| `copy` | — | 复制文件内容到剪贴板 |
| `submit` | — | 提交到 OJ |
| `bench` | — | 性能基准与回归 |
| `open` | — | 打开 OJ 题目页面 |
| `todo` | — | TODO / FIXME 统计与管理 |
| `where` | — | 查找符号定义位置 |
| `mood` | — | 状态管理（normal / tired） |
| `ask` | — | AI 提问 |
| `timer` | — | 番茄钟 |
| `diff` | — | 文件差异比较 |
| `judge` | — | 本地 OI 评测机 |
| `scan` | — | 静态分析（赛场避坑指南） |
| `polish` | — | 提交前抛光 |
| `sample` | — | 样例自动测试 |
| `anal_log` | — | 崩溃日志分析 |
| **`interact`** | — | **交互题支持（v5.2）** |
| **`rip`** | — | **纪念 fetch / upgrade（v5.2）** |

全局开关：

| 开关 | 含义 |
|---|---|
| `-v`, `--verbose` | 输出详细调试信息 |
| `-n`, `--dry-run` | 试运行（只打印操作不执行） |
| `-q`, `--quiet` | 静默模式（抑制所有输出） |
| `--version` | 打印版本并退出 |

---

## 五、核心命令详解

### 1. 运行与编译

```bash
ck run main.cpp                  # 自动编译 + 运行
ck run main.cpp 3.10 arg1 arg2   # Python 3.10 运行并传参
ck run main.cpp --std c++20      # 指定 C++ 标准

ck compile main.cpp              # 仅编译
ck compile main.cpp --sanitize   # 启用 ASan + UBSan
```

- 支持自动检测项目构建系统（CMake、Make、Cargo、npm、Go、Python）；
- 支持自动降级：`g++` 缺失时尝试 `cl`（MSVC）；
- 编译成功会写入 `.codekit-meta.json` 记录编译器版本。

### 2. 对拍（stress）

```bash
ck stress main.cpp brute.cpp --gen gen.py --cases 100
ck stress main.cpp --auto                     # AI 生成暴力 + 生成器
ck stress main.cpp --replay                   # 重放失败库中的 WA 反例
ck stress main.cpp brute.cpp --gen gen.py \
    --cases 200 --shrink --parallel --workers 4 \
    --eps 1e-6 --sanitize --checker spj.cpp \
    --celebrate --dry-run
```

参数详解：

| 参数 | 说明 |
|---|---|
| `main` | 主程序（优化） |
| `brute` | 暴力程序（`--auto` 时可省略） |
| `--gen` | 生成器（`--auto` 时可省略） |
| `--cases` | 测试组数 |
| `--timeout` | 每组超时（秒） |
| `--gen-args` | 传给生成器的参数 |
| `--shrink` | 启用 **ddmin** 增量调试缩小反例 |
| `--parallel` / `--workers` | 并行执行与线程数 |
| `--eps` | 浮点容差 |
| `--sanitize` | 启用 ASan 检测内存错误 |
| `--checker` | SPJ 程序路径 |
| `--celebrate` | 全部 AC 时打印彩蛋（Teto / Miku） |
| `--auto` | AI 自动生成暴力 + 生成器 |
| `--replay` | 重放失败库中 WA 反例 |

**ddmin 算法（v5.2 修复）**

对拍失败时若开启 `--shrink`，会用经典 **Delta Debugging** 最小化反例：

- `granularity` 从 2 起步，逐块尝试删除；
- 只要能保持"仍是 WA"，就接受并降低 granularity；
- 否则提高 granularity 细分。

v5.2 修复了原终止条件 bug：原实现比较 `granularity >= len(chunks)`（实际 chunk 数可能小于 granularity），导致过早停止。修复后改为与 **行数** 比较。

### 3. 批量测试（test）

```bash
ck test main.cpp                             # 自动检测 data/in 或 data
ck test main.cpp --input-dir ./data/in
ck test main.cpp --cktest .cktest            # 数据包
ck test main.cpp --sanitize --memory-limit 256
ck test main.cpp --dry-run
ck test --gen --file main.cpp                # 用 AI 生成单元测试
```

**自动检测输入目录（v5.2）**：依次查找 `data/in` → `data` → `.`，选第一个含 `*.in` 的目录；若无则返回第一个存在的目录，最终兜底当前工作目录。

**.cktest 数据包格式**（JSON / YAML）：

```json
{
  "name": "Problem P1001",
  "checker": "spj.cpp",
  "cases": [
    {"id": 1, "input": "1.in", "output": "1.out", "score": 10},
    {"id": 2, "input": "2.in", "output": "2.out", "score": 20}
  ]
}
```

### 4. 本地评测机（judge）

```bash
ck judge --source main.cpp                        # 无配置文件
ck judge --problem-config problem.json --source main.cpp
ck judge --source main.cpp --html                 # 导出 HTML 报告
ck judge --source main.cpp --format json          # 机器可读 JSON
ck judge --source main.cpp --dry-run
```

**题目配置**（`.codekit-problem.json`）：

```json
{
  "name": "P1001 A+B Problem",
  "time_limit": 1.0,
  "memory_limit": 256,
  "input_dir": "data/in",
  "output_dir": "data/out",
  "checker": "spj.cpp",
  "scoring": "oi",
  "subtasks": [
    {"id": "P1", "score": 30, "cases": ["1.in", "2.in"]},
    {"id": "P2", "score": 70, "cases": ["3.in", "4.in", "5.in"]}
  ]
}
```

**v5.2 增强**：无配置文件时自动检测 `data/in` → `data` → `.`，并自动根据 `*.in` 生成单个满分子任务。

**赛制**：

- `oi`：子任务内全部 AC 才得分；
- `ioi`：按测试点均分得分；
- `acm`：按 AC 数量计分。

### 5. 数据生成（gen）

```bash
ck gen gen.py --cases 10 --seed 12345
ck gen gen.py --cases 5 --output-prefix test --gen-args --n 1000
ck gen gen.py --cases 3 --dry-run
```

- 输出到 `data/in/xxx001.in`、`xxx002.in` ...；
- 生成器支持 `.py` 和编译型语言；
- `--seed` 通过环境变量 `CODEKIT_SEED` 传给生成器。

### 6. 交互题（interact）

> **v5.2 新增**

```bash
ck interact solution.cpp interactor.cpp --input in.txt
ck interact solution.py  interactor.py --timeout 10 --dry-run
```

工作方式：

1. 编译选手程序与交互器；
2. 启动交互器，把选手程序可执行文件路径作为 `argv[1]` 传入；
3. 交互器通过管道 / 子进程负责通信，并自行判定结果；
4. 交互器退出码即为最终结果（0 通过）。

**交互器约定**：

- `argv[1]`：选手程序可执行文件路径；
- `stdin`：可选输入数据文件（通过 `--input` 提供）；
- 交互器完全负责子进程 / 管道通信与最终判定。

### 7. 计时与性能（time / bench）

```bash
ck time main.cpp --flamegraph --top
ck time main.cpp --timeout 10
ck bench main.cpp --iterations 5 --save
ck bench main.cpp --compare
ck bench main.cpp --track
```

- `time` 支持火焰图（依赖 `py-spy`）、Top 函数采样（`cProfile`）；
- `bench --track` 会记录 git commit hash，并与上次结果比较；
- 变化超过 `bench.threshold_percent`（默认 20%）会警告。

### 8. 提交前防雷（polish / scan / check）

```bash
ck polish main.cpp --output main_polished.cpp --yes
ck polish main.cpp --fileIO          # 保留文件IO操作
ck scan .
ck check main.cpp
```

- `polish` 默认注释 `freopen` / `fclose`，删除调试输出，检查 `#define int long long`；
- `scan` 检测常见危险写法：`int*int` 溢出、递归无终止、大数组、`#define int long long`；
- `check` 检测数组过大、int 乘法溢出、递归深度、未关同步。

### 9. 统一失败库（failures）

```bash
ck failures list                     # 列出所有失败
ck failures list --type wa           # 按类型过滤（compile / wa / re）
ck failures show <id>                # 查看完整现场
ck failures retry                    # 重跑所有失败
ck failures retry --type compile
```

目录结构：

```
.codekit-failures/
├── index.json
├── compile/
│   └── compile_YYYYMMDD_HHMMSS_xxx/
│       ├── source.cpp
│       ├── error.err
│       └── ai.txt
├── wa/
│   └── wa_.../
│       ├── source.cpp
│       ├── input.txt
│       ├── main_out.txt
│       ├── brute_out.txt
│       └── meta.json
└── re/
    └── re_.../
        ├── source.cpp
        ├── input.txt
        ├── stderr.txt
        └── meta.json
```

对拍 / 评测 / watch 失败时会自动归档。

### 10. 崩溃日志（anal_log）

```bash
ck anal_log --list                   # 列出所有崩溃日志
ck anal_log --summary                # 统计摘要
ck anal_log --tail 5                 # 只显示最后 5 条
ck anal_log crash_20240101.log
```

崩溃日志目录：`~/.codekit/logs/crash_YYYYMMDD.log`

每份日志包含：时间、argv、Python 版本、平台、异常类型、Traceback、最近 20 条历史命令。

---

## 六、配置系统

### 配置文件查找顺序

1. `~/.codekit/config.yaml`（若 PyYAML 可用，优先于 JSON）
2. `~/.codekit/config.json`
3. 项目级：`./.codekit/local.json` / `config.json` / `config.yaml`
4. 旧版：`~/.codemanager`
5. 环境变量：`CODEKIT_*` 前缀（`__` 表示嵌套层级）
6. 内建默认值

### 环境变量覆盖示例

```bash
export CODEKIT_AI__API_KEY=sk-xxxx
export CODEKIT_GCC_VERSION=c++20
export CODEKIT_OI__DEFAULT_GPP=g++-13
export CODEKIT_AI_KEY=sk-xxxx        # 特例：直接映射到 ai.api_key
```

### 主要配置项

```jsonc
{
  "gcc_version": "c++17",              // 默认 C++ 标准
  "default_language": "cpp",
  "template_dir": "~/.codekit/templates",
  "timeout": "60",
  "env_file": ".env",
  "color_output": "true",
  "work_dir": "...",
  "safe_clean": "true",
  "clean_confirm": "true",

  "ai": {
    "provider": "openai",              // openai / ollama / llama.cpp
    "api_key": null,
    "model": "gpt-4",
    "base_url": null,
    "ollama_url": "http://localhost:11434/api/generate",
    "llama_url": "http://localhost:8080/completion",
    "context_depth": 3,
    "include_git_diff": true,
    "include_comments": true
  },

  "plugins": {
    "dir": "~/.codekit/plugins",
    "enabled_only": true,
    "auto_load": true,
    "allowed_origins": ["local"]
  },

  "commands": {
    "dir": "~/.codekit/commands",
    "auto_load": true
  },

  "watch": {
    "exclude": [".git", "__pycache__", "*.tmp", "*.swp", "*.log", "*.pyc"],
    "poll_interval": 1.0,
    "use_polling": false,
    "recursive": true
  },

  "debug": {
    "debugger": "gdb",
    "install_hints": { "gdb": "sudo apt install gdb", ... }
  },

  "terminal": {
    "default": "auto",
    "fallback": "xterm",
    "detect_order": ["wezterm", "alacritty", "gnome-terminal", "konsole", "xfce4-terminal", "xterm"]
  },

  "git": {
    "allow_commands": ["clone", "pull", "push", "commit", "status", "log", "fetch", "checkout"],
    "deny_options": ["--upload-pack", "--receive-pack", "--exec"]
  },

  "security": {
    "plugin_whitelist_only": true,
    "env_override_prefix": "CODEKIT_"
  },

  "oi": {
    "gpp_versions": ["g++-14", "g++-13", "g++-12", "g++-11", "g++"],
    "default_gpp": "g++",
    "timeout": 5,
    "memory_limit_mb": 512,
    "author": "OIer",
    "default_input_dir": null,
    "default_output_dir": null
  },

  "check": {
    "array_size_warning": 100000,
    "recursion_depth_warning": 1000000,
    "int_overflow_warning": true
  },

  "copy": { "default_command": "auto" },

  "fetch": {
    "cache_dir": "~/.codekit/cache/fetch",
    "timeout": 10
  },

  "submit": {
    "command_template": "oj submit --language {language} --yes {url} {file}",
    "platforms": {
      "luogu": {
        "url_template": "https://www.luogu.com.cn/problem/{problem}",
        "language_map": { "cpp": "cpp", "c": "c", "python": "python", ... }
      },
      "codeforces": {
        "url_template": "https://codeforces.com/problemset/problem/{contest}/{problem}",
        "language_map": { ... }
      },
      "atcoder": {
        "url_template": "https://atcoder.jp/contests/{contest}/tasks/{problem}",
        "language_map": { ... }
      }
    }
  },

  "bench": {
    "baseline_file": ".codekit-bench.json",
    "iterations": 3,
    "threshold_percent": 20.0,
    "history_file": ".codekit-bench-history.json",
    "track_cases": 100
  },

  "mood": {
    "state": "normal",
    "tired_threshold_cases": 100
  },

  "timer": {
    "default_duration": 25,
    "notification": true
  },

  "polish": {
    "backup_suffix": "_polished",
    "auto_confirm": false
  },

  "compile_flags": [],

  "CommandFormat": [
    { "指令名": "s", "对应指令": "stress $1 $2 --gen $3 --cases 200" }
  ]
}
```

### 配置命令

```bash
ck config show                 # 显示完整配置（API Key 打码）
ck config get oi.default_gpp
ck config set oi.timeout 10
ck config diff                 # 对比已保存配置
ck config reload               # 热重载
```

### CommandFormat：指令别名系统

`CommandFormat` 是一组 `{"指令名": ..., "对应指令": ...}` 映射，允许用户自定义命令别名：

```json
{
  "CommandFormat": [
    { "指令名": "s", "对应指令": "stress main.cpp brute.cpp --gen gen.py --cases 200" },
    { "指令名": "j", "对应指令": "judge --source main.cpp --html" }
  ]
}
```

之后 `ck s` 等价于 `ck stress main.cpp brute.cpp ...`。支持 `$1`、`$2` ... 参数占位符，最多迭代 5 层（防循环）。

**命令解析优先级**：`module_list` > `CommandFormat` > `Command`。

---

## 七、插件系统

CodeKit 提供两类插件：**语言插件**与**命令插件**。

### 语言插件（LanguageHandler）

用于扩展 CodeKit 能识别的源码类型与编译 / 运行逻辑。

**目录**：

- `~/.codekit/plugins/available/` — 可用
- `~/.codekit/plugins/enabled/` — 启用

**模板生成**：

```bash
ck new mylang.py --plugin
```

生成如下骨架：

```python
from CodeKit import LanguageHandler, Config, Console, Path, Optional, List, Tuple

class Mylang(LanguageHandler):
    name = "Mylang"
    extensions = [".ml"]
    __deps__ = []           # 依赖声明，可用于展示

    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        Console.info(f"Running {self.name} on {file}")
        return True

    def compile(self, file: Path, sanitize: bool = False) -> Tuple[bool, str]:
        return False, "解释型语言无法编译"

    def clean(self, file: Optional[Path] = None) -> bool:
        return True

    def build(self, file: Optional[Path] = None) -> bool:
        return False

    def help(self) -> str:
        return f"自定义插件 {self.name}"

Handler = Mylang
```

将文件放入插件目录后：

```bash
ck plugin reload
ck plugin list
```

**编译型语言**可直接继承 `CompiledLanguageHandler`：

```python
from CodeKit import CompiledLanguageHandler

class MyCompiler(CompiledLanguageHandler):
    name = "MyLang"
    extensions = [".mylang"]
    compiler_cmd = "mylangc"
    std_flag = "-std="
    output_flag = "-o"

Handler = MyCompiler
```

**插件安全**：默认启用 `plugin_whitelist_only`，只允许加载 `~/.codekit/plugins/available` 与 `enabled` 下的插件。

### 命令插件（CommandPlugin）

用于扩展 `ck` 的子命令。

**目录**：`~/.codekit/commands/`

**模板生成**：

```bash
ck new mycmd.py --command
```

生成骨架：

```python
import argparse
from CodeKit import CommandPlugin, CodeManager, Console, Path, config

class MycmdCommand(CommandPlugin):
    name = "mycmd"

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.name)
        parser.add_argument('--message', '-m', default='Hello')
        parser.add_argument('--count', '-c', type=int, default=1)
        return parser

    def run(self, parsed_args: argparse.Namespace, code_manager: CodeManager) -> bool:
        for _ in range(parsed_args.count):
            Console.info(f"自定义命令输出: {parsed_args.message}")
        return True

    def check_dependencies(self) -> bool:
        return True
```

将文件放入 `~/.codekit/commands/` 后自动加载，即可用 `ck mycmd --message hi -c 3`。

### 动态导入（import）

也可以临时导入命令模块，无需拷贝到固定目录：

```bash
ck import myplugin.py                    # 立即导入
ck import a.py b.py --persistence        # 导入并拷贝到加载目录
ck import myplugin.py --lazy             # 交互模式下延迟加载
```

**行为矩阵**：

| 模式 | `--lazy` | `--persistence` | 行为 |
|---|---|---|---|
| 非交互 | 否 | 是 | 立即导入，立即拷贝到加载目录 |
| 非交互 | 是 | 否 | 报错 |
| 非交互 | 是 | 是 | 报错 |
| 交互 | 否 | 是 | 立即导入，立即拷贝 |
| 交互 | 是 | 否 | 塞缓存，用时加载 |
| 交互 | 是 | 是 | 塞缓存；真正加载时才拷贝 |

---

## 八、AI 服务

CodeKit 支持三种 provider：

| provider | 配置 | 说明 |
|---|---|---|
| `openai` | `api_key`, `model`, `base_url` | 兼容 OpenAI Chat Completions 协议 |
| `ollama` | `ollama_url`, `model` | 本地 Ollama |
| `llama.cpp` | `llama_url` | 本地 llama.cpp |

### 配置示例

```bash
# 方式一：环境变量
export CODEKIT_AI_KEY=sk-xxxx

# 方式二：配置
ck config set ai.provider openai
ck config set ai.model gpt-4
ck config set ai.api_key sk-xxxx

# 方式三：配置 env: 前缀间接引用
ck config set ai.api_key env:OPENAI_KEY
```

### AI 相关命令

| 命令 | 功能 |
|---|---|
| `ck explain <file> [--ask "问题"]` | 解释代码或追问 |
| `ck fix [--file f]` | 修复 Lint 错误 |
| `ck commit` | 生成 git commit message |
| `ck ask "问题"` | 通用提问（含项目上下文） |
| `ck stress main.cpp --auto` | 生成暴力 + 生成器 |
| `ck test --gen --file f` | 生成单元测试 |
| `ck watch <file> --nerror --ai-explain` | 编译错误 AI 分析 |

### 上下文收集

`AIService._collect_context` 会自动收集：

- `git diff --staged` 前 500 字符；
- 当前目录树（前 30 行，深度由 `context_depth` 决定）；
- 前几个源码文件的注释（前 10 行）。

可在配置中开关：`ai.include_git_diff`、`ai.include_comments`。

---

## 九、外部工具集成

| 命令 | 依赖 | 备注 |
|---|---|---|
| `ck fmt` | `clang-format` / `black` / `prettier` / `gofmt` / `rustfmt` | 按扩展名自动选择 |
| `ck grep` | `rg` / `grep` / `findstr` | 优先 ripgrep |
| `ck def` | `ctags`（可选） | 无 ctags 时用正则 |
| `ck stats` | `cloc`（可选） | 无 cloc 时内置统计 |
| `ck debug` | `gdb` / `lldb` / `pdb` | 按语言自动选择 |
| `ck time --flamegraph` | `py-spy` | 生成 SVG 火焰图 |
| `ck submit` | `online-judge-tools` (`oj`) | 提交 OJ |
| `ck copy` | `clip` / `pbcopy` / `xclip` / `xsel` | 剪贴板 |
| `ck watch` | `watchdog`（可选） | 无则轮询 |

---

## 十、进阶主题

### .env 文件

CodeKit 会自动搜索当前目录及其父目录的 `.env`：

```
DATABASE_URL=postgres://...
CODEKIT_AI_KEY=sk-xxxx
FOO=${BAR}/baz
```

支持 `${VAR}` 变量展开。

```bash
ck env list
ck env set FOO bar
ck env save                 # 保存环境指纹 .codekit-env.json
ck env restore              # 恢复 / 校验环境
ck env check-g++            # 自动检测并选用最新 g++
```

### 环境指纹

`.codekit-env.json` 记录：

- Python 版本与可执行文件路径
- 编译器路径与版本（gcc / g++ / clang / rustc / go / javac / dotnet / swiftc / dart / ruby）
- 工具（make / cmake / cargo / npm / pip）
- 依赖文件哈希（requirements.txt / package.json / go.mod / Cargo.toml）
- 关键环境变量

`ck env restore` 会逐项比对，给出修复建议，并可选自动执行安装命令（apt / brew / yum / rustup）。

### 竞赛模式（contest）

```bash
ck contest start contest.json --duration 3600
```

比赛配置：

```json
{
  "name": "模拟赛 R1",
  "scoring": "oi",
  "duration": 3600,
  "auto_submit": false,
  "readonly_data": true,
  "hash_check": true,
  "auto_backup": true,
  "backup_path": "./.contest_backups",
  "platform": "luogu",
  "global": {
    "time_limit": 1.0,
    "memory_limit": 256
  },
  "problems": [
    {
      "id": "T1",
      "name": "签到题",
      "src": "T1.cpp",
      "config": "T1.json"
    }
  ]
}
```

功能：

- 数据目录设为只读 + 记录哈希（防改数据）；
- 每隔 1 秒监控源文件改动并快照到 `~/.codekit/contests/<name>_<ts>/snapshots/`；
- 计时结束后自动评测并生成 `report.txt`；
- 可选自动提交（`auto_submit`）。

### 崩溃日志与 SIGINT 处理

- 顶层异常捕获并写入 `~/.codekit/logs/crash_YYYYMMDD.log`；
- 全局 SIGINT 处理器会先终止所有活跃子进程，再抛出 `KeyboardInterrupt`；
- `--quiet` 会用 `_QuietStream` 屏蔽标准输出。

### 命令历史

每次命令都追加到 `~/.codekit_history`（含时间戳），崩溃日志会附带最后 20 条。

### 任务系统（task）

在当前目录 `.codemanager` 中定义：

```ini
[tasks]
build = ck:compile main.cpp
test = ck:test main.cpp --input-dir data/in
run = ck:run main.cpp

deploy = ./deploy.sh {args}
```

- `ck:...` 前缀：内部命令
- 其他：作为 shell 命令执行，支持 `{args}` 占位符

```bash
ck task build
ck task deploy --env prod
```

---

## 十一、版本演进

| 版本 | 新增 |
|---|---|
| **OI-v5.2** | `ck interact` 交互题；`judge` / `test` 自动检测数据目录；`--input-dir` 变为可选；无配置文件自动生成子任务；修复 ddmin 终止条件；`ck rip` 纪念 |
| OI-v5.1 | `--shrink` 使用 ddmin 增量调试 |
| OI-v5.0 | `template_dir` 迁移到 `~/.codekit/templates`；全局 SIGINT；崩溃日志；`anal_log`；全局 `--quiet`；`judge --format json`；`snippet --from-file` |
| v4.x | 引入插件系统、AI 服务、失败库、竞赛模式 |
| 早期 | `fetch` / `upgrade`（已移除） |

---

## 十二、常见问题 FAQ

**Q1：`ck` 命令不存在？**

把脚本加入 PATH，或建立软链接：`ln -sf $(pwd)/CodeKit-OI-v5.2.py /usr/local/bin/ck`。

**Q2：无配置文件如何对拍？**

```bash
ck stress main.cpp brute.cpp --gen gen.py
```

或让 AI 生成：

```bash
ck stress main.cpp --auto
```

**Q3：对拍卡在缩小反例？**

ddmin 迭代上限 10000，超出会提前退出并警告。可加 `--cases 50` 缩小初始反例规模。

**Q4：Windows 上内存限制不生效？**

Windows 不支持 `RLIMIT_AS`，`--memory-limit` 会被忽略（会打印警告）。可用 `time` 命令查看 `psutil` 提供的峰值。

**Q5：AI 生成失败提示 "Nee~"？**

这是 Teto 在提醒：检查 `ai.provider` / `ai.api_key` / 网络。用 `ck config show` 查看，`ck config set ai.provider ollama` 可切本地。

**Q6：如何只跑失败库中的某类型？**

```bash
ck failures retry --type wa
```

**Q7：如何优雅地纪念 fetch / upgrade？**

```bash
ck rip
```

**Q8：`--quiet` 后连错误都看不到？**

`--quiet` 会屏蔽所有 `Console` 输出。若需定位问题，可查看 `~/.codekit/logs/crash_*.log`，或改用 `-v`。

**Q9：对拍遇到浮点输出如何处理？**

使用 `--eps 1e-6`：

```bash
ck stress main.cpp brute.cpp --gen gen.py --eps 1e-6
```

**Q10：如何自定义命令别名？**

在配置里加 `CommandFormat` 项：

```json
{
  "CommandFormat": [
    { "指令名": "s", "对应指令": "stress main.cpp brute.cpp --gen gen.py --cases 200" }
  ]
}
```

---

## 许可与致谢


> `LoveTeto: bool = True`
> `LoveMiku: float = 3 / 4`

祝你比赛 RP++，全 AC！🎉
###### ***rip子指令有彩蛋***