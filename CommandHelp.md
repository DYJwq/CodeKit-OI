# CodeKit OI 指令速查手册

> **版本**：OI-v4.2 (赛场增强版)  
> **适用对象**：信息学竞赛选手、算法爱好者、本地代码调试达人  
> **一句话简介**：将编译器、调试器、对拍器、评测机、AI 助手、环境检测揉成一体的“赛博义肢”

---

## 目录
1. [快速上手](#快速上手)
2. [核心命令](#核心命令)
3. [构建与依赖管理](#构建与依赖管理)
4. [代码质量与格式化](#代码质量与格式化)
5. [调试与性能分析](#调试与性能分析)
6. [OI 专用命令（王牌功能）](#oi-专用命令王牌功能)
7. [AI 辅助命令](#ai-辅助命令)
8. [工具与辅助命令](#工具与辅助命令)
9. [全局选项](#全局选项)
10. [配置文件与环境变量](#配置文件与环境变量)
11. [常见问题](#常见问题)

---

## 快速上手

```bash
# 查看版本
ck --version

# 运行一个 C++ 文件（自动编译+执行）
ck run main.cpp

# 对拍（stress）自动找反例
ck stress main.cpp brute.cpp --gen gen.py --cases 100

# 本地评测（模拟 NOIP 评分）
ck judge --problem-config .codekit-problem.json --source main.cpp

# 进入交互式 Shell
ck shell
```

---

## 核心命令

### `ck run <file> [version] [args...]`
运行代码文件（支持多语言），自动根据后缀调用对应解释器/编译器。  
- `<file>`：源文件路径  
- `version`：可选，Python 版本（如 `3.10`）  
- `args...`：传递给程序的命令行参数  
- `--std`：指定 C++ 标准（如 `c++17`）  

示例：
```bash
ck run main.cpp --std c++20
ck run script.py 3.9 --input data.txt
```

---

### `ck compile <file> [--sanitize]`
仅编译，不运行。  
- `--sanitize`：启用 AddressSanitizer 和 UndefinedBehaviorSanitizer（用于内存错误检测）

---

### `ck clean [--dry-run] [--no-confirm]`
清理项目中的构建产物（`.exe`、`.o`、`__pycache__`、`node_modules` 等）。  
- `--dry-run`：预览要删除的文件，不实际删除  
- `--no-confirm`：跳过确认提示

---

### `ck list` 或 `ck ls [filter]`
列出当前目录下所有代码文件（按语言分组）。  
- `filter`：按扩展名过滤，如 `.cpp`

---

### `ck search <keyword>`
在当前目录所有代码文件中搜索关键词（支持多种语言）。

---

### `ck new <file> [--plugin] [--command]`
创建新文件，自动填充模板（支持 `.cpp`、`.py`、`.java` 等）。  
- `--plugin`：生成语言插件模板  
- `--command`：生成命令插件模板

---

## 构建与依赖管理

### `ck build`
检测当前目录下的项目（CMake/Make/Cargo/NPM/Go）并执行构建命令。

### `ck deps check` / `ck deps install`
- `check`：显示依赖文件（`requirements.txt`、`package.json` 等）内容  
- `install`：根据项目类型安装依赖（pip/npm/go mod/cargo fetch）

---

## 代码质量与格式化

### `ck fmt <target>`
格式化代码（需安装对应工具，如 `clang-format`、`black`、`prettier`）。  
- `<target>`：文件或目录

### `ck lint`
运行静态代码检查（`pylint`、`eslint`、`clang-tidy`、`cargo clippy` 等）。

### `ck check [target]`
专为 OI 设计的 C/C++ 快速预检：  
- 检查大数组、int 溢出、递归深度、关闭同步流等常见“赛场坑点”。

### `ck scan [target]`
生成“赛场避坑指南”，扫描危险写法（`#define int long long`、栈上超大数组、无终止递归等）。

---

## 调试与性能分析

### `ck debug <file> [args...]`
启动调试器（C++: gdb/lldb，Python: pdb，Go: delve，Java: jdb）。  
- 自动编译（若需要）并进入调试会话。

### `ck time <file> [args...] [--flamegraph] [--top] [--timeout N]`
计时并统计内存峰值。  
- `--flamegraph`：生成火焰图（需 `py-spy`）  
- `--top`：显示最耗时函数（使用 `py-spy top` 或 cProfile）

### `ck bench <file> [--save] [--compare] [--iterations N]`
性能回归测试，保存基准或与历史基准比较。  
- `--save`：将当前运行结果保存为基准  
- `--compare`：与已保存的基准比较，超阈值自动报警

---

## OI 专用命令（王牌功能）

### `ck stress <main> <brute> --gen <gen> [选项]`
**对拍（数据生成 + 自动找反例）**，是整个工具的灵魂。

常用选项：
- `--cases N`：测试组数（默认 100）  
- `--timeout N`：每组超时秒数  
- `--shrink`：自动缩小反例数据规模  
- `--parallel`：启用多线程并行运行  
- `--eps 1e-6`：浮点数容差  
- `--sanitize`：主程序编译时启用 ASan  
- `--checker checker.cpp`：使用 SPJ（需编译型语言）

示例：
```bash
ck stress main.cpp brute.cpp --gen gen.py --cases 200 --shrink --eps 1e-9 --sanitize --checker checker.cpp --celebrate
```

---

### `ck test <file> --input-dir <dir> [选项]`
批量测试（支持 `.cktest` 数据包、子任务、SPJ）。  
- `--output-dir`：期望输出目录（默认自动推断）  
- `--cktest`：指定 `.cktest` 配置文件  
- `--memory-limit MB`：设置内存限制（仅 Unix）  
- `--sanitize`：启用 ASan  
- `--dry-run`：试运行

---

### `ck gen <gen_file> --cases N [--seed S]`
使用生成器批量造数据，输出到 `data/in/`。  
- `--seed`：设置随机种子  
- `--gen-args`：传递额外参数给生成器

---

### `ck judge --problem-config <config> --source <main>`
**本地 OI 评测机**：模拟 NOIP/CSP 评分规则，支持子任务捆绑、SPJ、内存限制，导出 HTML 报告。  
- `--problem-config`：JSON 格式题目配置（含 `subtasks`、`time_limit`、`memory_limit`、`checker` 等）  
- `--output-dir`：输出目录（默认 `data/out`）  
- `--html`：生成 HTML 报表

---

### `ck init [lang]`
生成 OI 风格的模板文件（`main.cpp` 等）并创建模板目录。

---

### `ck snippet list` / `ck snippet get <name> [--output file] [--insert] [--position marker]`
算法模板速查与插入。内置模板包括：`segtree`、`bit`、`kmp`、`exgcd`、`maxflow`、`dijkstra`、`lca`、`quick_pow`、`miller_rabin` 等。  
- `--insert`：追加到已有文件（而非覆盖）  
- `--position`：在文件中找到包含该标记的行，并在其后插入

---

### `ck contest start <config> --duration N [--cfg alternate]`
模拟比赛环境，自动监控源文件变化并保存快照。  
- `--cfg`：可指定备用配置（覆盖默认路径）  
- 结束自动生成比赛报告

---

### `ck fetch <problem_id> --platform luogu`
从 OJ 拉取样例数据（目前支持洛谷，需网络和 `requests` 库）。

---

### `ck submit <file> --problem <id> [--platform luogu] [--fast]`
提交代码到 OJ（依赖 `online-judge-tools`）。  
- `--fast`：从 `.codekit-oj.json` 读取平台和题目信息，无需手动指定

---

### `ck open <problem_id> --platform luogu`
在浏览器打开题目页面。

---

## AI 辅助命令

### `ck explain [file] --ask "问题"`
AI 解释代码或回答关于代码的问题（支持上下文感知）。  
- 若不指定文件，则自动扫描当前目录的代码文件。

### `ck fix [--file]`
运行 Lint 检查，将错误喂给 AI，自动生成修复补丁并（可选）应用。

---

### 环境/状态命令
- `ck env check-g++`：扫描系统 g++ 版本，自动更新配置为最新版  
- `ck env save` / `ck env restore`：保存/恢复环境指纹（编译器版本、依赖哈希等）  
- `ck mood set tired` / `ck mood get`：设置/查看“疲劳”状态，影响 `stress` 的测试组数上限

---

## 工具与辅助命令

| 命令 | 说明 |
|------|------|
| `ck backup [dst]` | 备份当前目录 |
| `ck restore <src>` | 从备份还原 |
| `ck archive --format zip/tar [--output]` | 打包项目 |
| `ck kill <pid>` | 终止进程 |
| `ck terminal` | 在新终端中打开当前目录 |
| `ck edit <file>` | 用默认编辑器打开文件 |
| `ck diff <file1> <file2> [--ignore-trailing-spaces] [--ignore-blank-lines]` | 比对两个文件 |
| `ck todo [--add "内容"] [--list] [--count] [--sort-by-date]` | 管理 TODO/FIXME 注释 |
| `ck where <symbol>` | 查找符号定义位置 |
| `ck timer [minutes]` | 启动番茄钟（默认 25 分钟） |
| `ck cd [path]` | 切换工作目录并保存到配置 |
| `ck chdir` | 同 `cd` |
| `ck config show/get/set/diff/reload` | 查看/修改配置 |
| `ck plugin list/install/reload` | 管理外部插件 |
| `ck doctor` | 环境诊断，自动检测缺失工具 |
| `ck self-test` | 运行自检，验证所有模块 |

---

## 全局选项

- `--verbose` / `-v`：显示详细调试信息  
- `--dry-run` / `-n`：试运行，仅打印要执行的操作，不实际运行  
- `--version`：显示版本号

---

## 配置文件与环境变量

### 配置文件位置
- 全局：`~/.codekit/config.json` 或 `~/.codekit/config.yaml`  
- 项目级：`./.codekit/config.json` 或 `./.codekit/config.yaml`（优先）

### 常用配置项（可通过 `ck config set <key> <value>` 修改）
- `oi.default_gpp`：默认 C++ 编译器（自动检测）  
- `oi.timeout`：对拍/测试默认超时（秒）  
- `oi.memory_limit_mb`：评测内存限制（MB）  
- `ai.provider`：AI 服务提供商（`openai`、`ollama`、`llama.cpp`）  
- `ai.api_key`：API 密钥（或通过环境变量 `CODEKIT_AI_KEY` 设置）  
- `ai.model`：模型名称（如 `gpt-4`、`llama2`）  
- `watch.exclude`：监控时忽略的文件模式  
- `terminal.default`：默认终端模拟器

### 环境变量覆盖
任何配置项都可通过环境变量 `CODEKIT_<路径>` 覆盖，例如：
```bash
export CODEKIT_oi_timeout=10
```

---

## 常见问题

**Q：运行 `ck run` 时提示找不到编译器？**  
A：确保已安装对应编译器（如 `g++`、`python`、`javac`），或运行 `ck doctor` 检查环境。

**Q：对拍时 `--shrink` 如何工作？**  
A：当发现 WA 时，会尝试二分减少输入数据规模（如裁剪行数、缩小 n 值），直到找到最小的可复现反例。

**Q：如何启用 AI 功能？**  
A：在配置中设置 `ai.provider` 和 `ai.api_key`（OpenAI），或配置本地 `ollama`/`llama.cpp` 的 URL。

**Q：`ck judge` 的题目配置格式？**  
A：参考以下 JSON 示例（保存为 `.codekit-problem.json`）：
```json
{
  "name": "求和",
  "time_limit": 1.0,
  "memory_limit": 256,
  "subtasks": [
    {
      "id": 1,
      "score": 30,
      "cases": ["1.in", "2.in"]
    },
    {
      "id": 2,
      "score": 70,
      "cases": ["3.in", "4.in", "5.in"]
    }
  ],
  "checker": "checker.cpp"
}
```
输入文件放在 `data/in/`，期望输出放在 `data/out/`（或 `data/ans/`），运行 `ck judge` 即可得到总分。

**Q：插件如何安装？**  
A：将 `.py` 文件放入 `~/.codekit/commands/`（命令插件）或 `~/.codekit/plugins/`（语言插件），然后执行 `ck plugin reload`。

**Q：`ck watch` 如何与 `--test` 配合？**  
A：`ck watch main.cpp --test --input-dir data/in` 会监控 `main.cpp`，一旦保存就自动编译并运行 `ck test` 的所有测试点，适合“边写边测”模式。

---

## 最后的话

CodeKit OI 是一款充满“极客浪漫”的本地工具，它的设计初衷是**把 OI 选手从繁琐的编译、调试、对拍中解放出来**，让你能更专注于算法本身。虽然它无法在正式赛场上使用，但它绝对是备战阶段的得力助手。

**愿 Teto 和 Miku 保佑你每次提交都是 Accepted！** 🎤🎶
# **正在更新最新文档,请稍等**
