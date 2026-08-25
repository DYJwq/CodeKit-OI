# CodeKit OI 插件开发文档

> 版本：OI-v4.2 | 适用对象：信息学竞赛选手、算法竞赛工具开发者

---

## 一、概述

CodeKit OI 的插件系统采用**双轨制**设计，支持两类插件扩展：

| 插件类型 | 用途 | 基类 |
|---------|------|------|
| **语言插件 (Language Handler)** | 为新的编程语言提供编译、运行、调试支持 | `LanguageHandler` / `CompiledLanguageHandler` |
| **命令插件 (Command Plugin)** | 向 `ck` 命令行添加自定义子命令 | `CommandPlugin` |

插件可放置在用户目录下的 `~/.codekit/plugins/`（语言插件）或 `~/.codekit/commands/`（命令插件）中，由 CodeKit 在启动时自动扫描加载。

---

## 二、语言插件 (Language Handler)

语言插件负责处理特定文件扩展名的编译、运行、打包等操作。CodeKit 内置了 C/C++、Python、Java、Go、Rust、C#、JavaScript、TypeScript、Shell、Dart、Swift、Ruby 等语言的支持，你可以通过编写插件来扩展更多语言。

### 2.1 基类说明

**`LanguageHandler`** —— 所有语言插件的抽象基类

```python
class LanguageHandler(ABC):
    name: str = "unnamed"           # 语言名称
    extensions: List[str] = []      # 支持的文件扩展名
    __deps__: List[str] = []        # 依赖列表（如 ["g++>=9"]）

    @abstractmethod
    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        """运行代码文件"""
        pass

    @abstractmethod
    def compile(self, file: Path) -> bool:
        """编译代码文件"""
        pass

    def check_dependencies(self) -> bool:
        """检查依赖是否满足"""
        return True

    def pack(self, file: Path, output: Optional[str] = None, options: List[str] = None) -> bool:
        """打包为可执行文件"""
        return False

    def clean(self, file: Optional[Path] = None) -> bool:
        """清理编译产物"""
        return True

    def build(self, file: Optional[Path] = None) -> bool:
        """构建项目"""
        return False

    def help(self) -> str:
        """返回帮助信息"""
        return f"{self.name} 插件，支持扩展名: {', '.join(self.extensions)}"
```

**`CompiledLanguageHandler`** —— 编译型语言的专用基类

```python
class CompiledLanguageHandler(LanguageHandler):
    compiler_cmd: str = None        # 编译器命令，如 'g++'
    std_flag: str = None            # 标准标志，如 '-std='
    output_flag: str = None         # 输出标志，如 '-o'
    sanitize_enabled: bool = False  # 是否支持 sanitize

    def compile(self, file: Path, sanitize: bool = False) -> bool:
        """编译并支持 AddressSanitizer"""
        # 自动处理编译命令、输出文件、sanitize 选项
```

### 2.2 内置语言插件示例

**C++ 插件**

```python
class CppHandler(CompiledLanguageHandler):
    name = "C++"
    extensions = ['.cpp', '.cxx', '.cc', '.c++']
    compiler_cmd = 'g++'
    std_flag = '-std='
    output_flag = '-o'
    __deps__ = ["g++>=9", "make>=4"]

    def _fallback_compile(self, file: Path, out: Path) -> bool:
        # 当 g++ 不可用时，尝试 MSVC cl 编译器
        if shutil.which('cl'):
            cmd = ['cl', '/EHsc', '/std:c++latest', str(file), f'/Fe:{out}']
            # ...
```

**Python 插件**

```python
class PythonHandler(LanguageHandler):
    name = "Python"
    extensions = ['.py', '.pyw']
    __deps__ = ["python>=3.6"]

    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        # 支持指定 Python 版本运行
        interpreter_cmd = self._get_interpreter_cmd(version)
        # ...

    def pack(self, file: Path, output: Optional[str] = None, options: List[str] = None) -> bool:
        # 使用 PyInstaller 打包
        if shutil.which('pyinstaller'):
            # ...
```

### 2.3 自定义语言插件开发

创建一个新的语言插件只需继承 `LanguageHandler` 或 `CompiledLanguageHandler` 并实现必要方法：

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义插件: MyLangHandler
放置于 ~/.codekit/plugins/mylang.py
"""
from CodeKit import LanguageHandler, Config, Console, Path, Optional, List

class MyLangHandler(LanguageHandler):
    name = "MyLang"
    extensions = ['.mylang']
    __deps__ = ["mylang-compiler>=1.0"]

    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        Console.info(f"Running {self.name} on {file}")
        # 实现运行逻辑
        return True

    def compile(self, file: Path) -> bool:
        Console.info(f"Compiling {file}")
        # 实现编译逻辑
        return True

# 必须导出 Handler 类
Handler = MyLangHandler
```

**关键约定**：

- 插件文件必须以 `.py` 结尾
- 必须定义一个继承自 `LanguageHandler` 的 `Handler` 类
- 插件将自动注册到 `PluginRegistry`

---

## 三、命令插件 (Command Plugin)

命令插件允许你向 CodeKit 添加自定义子命令，例如 `ck mycmd --option value`。

### 3.1 基类说明

```python
class CommandPlugin(ABC):
    name: str = None                # 命令名称（默认使用类名小写）

    def get_name(self) -> str:
        """返回命令名称"""
        if self.name:
            return self.name
        return self.__class__.__name__.lower()

    def get_parser(self) -> argparse.ArgumentParser:
        """返回命令行参数解析器"""
        parser = argparse.ArgumentParser(prog=self.get_name(), 
                                         description=f"自定义命令: {self.get_name()}")
        return parser

    @abstractmethod
    def run(self, parsed_args: argparse.Namespace, code_manager: 'CodeManager') -> bool:
        """执行命令逻辑"""
        pass

    def check_dependencies(self) -> bool:
        """检查依赖是否满足"""
        return True
```

### 3.2 自定义命令插件开发

```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义命令插件: hello
放置于 ~/.codekit/commands/hello.py
"""
import argparse
from CodeKit import CommandPlugin, CodeManager, Console, Path, config

class HelloCommand(CommandPlugin):
    name = "hello"

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.name, description="打招呼命令")
        parser.add_argument('--message', '-m', default='Hello', help='要输出的消息')
        parser.add_argument('--count', '-c', type=int, default=1, help='重复次数')
        return parser

    def run(self, parsed_args: argparse.Namespace, code_manager: CodeManager) -> bool:
        for _ in range(parsed_args.count):
            Console.info(f"自定义命令输出: {parsed_args.message}")
        return True

    def check_dependencies(self) -> bool:
        # 检查依赖，例如某个工具是否安装
        return True
```

安装后即可使用 `ck hello --message "Hi" --count 3` 调用。

---

## 四、插件管理

### 4.1 插件目录结构

```
~/.codekit/
├── plugins/
│   ├── available/          # 可用插件（可选）
│   └── enabled/            # 已启用插件（可选）
├── commands/               # 命令插件目录
└── ...
```

### 4.2 插件命令

| 命令 | 说明 |
|------|------|
| `ck plugin list` | 列出已安装的外部插件 |
| `ck plugin install ` | 从官方源或 URL 安装插件 |
| `ck plugin reload` | 热加载插件（无需重启 CodeKit） |
| `ck new --plugin ` | 创建语言插件模板 |
| `ck new --command ` | 创建命令插件模板 |

### 4.3 安全机制

CodeKit 对插件加载实施了安全限制：

- 插件只能从 `~/.codekit/plugins/` 及其子目录加载
- 可通过 `security.plugin_whitelist_only` 配置项控制是否仅允许白名单插件
- 插件加载时不会执行任意代码，需明确定义 `Handler` 或 `CommandPlugin` 子类

---

## 五、插件注册机制

### 5.1 语言插件注册

`PluginRegistry` 负责管理所有语言插件：

```python
class PluginRegistry:
    _handlers: Dict[str, LanguageHandler] = {}   # 扩展名 -> 处理器
    _handler_deps: Dict[str, List[str]] = {}     # 处理器 -> 依赖列表

    @classmethod
    def register(cls, handler_class):
        """注册一个语言插件"""
        instance = handler_class(config)
        if instance.check_dependencies():
            for ext in instance.extensions:
                cls._handlers[ext] = instance

    @classmethod
    def get_handler(cls, ext: str) -> Optional[LanguageHandler]:
        """根据扩展名获取对应的处理器"""
        return cls._handlers.get(ext.lower())
```

### 5.2 命令插件注册

`CommandRegistry` 负责管理命令插件：

```python
class CommandRegistry:
    _commands: Dict[str, CommandPlugin] = {}

    @classmethod
    def register(cls, plugin_class):
        """注册一个命令插件"""
        instance = plugin_class()
        if instance.check_dependencies():
            cls._commands[instance.get_name()] = instance

    @classmethod
    def get_command(cls, name: str) -> Optional[CommandPlugin]:
        return cls._commands.get(name)
```

---

## 六、内置插件列表

CodeKit OI v4.2 内置以下语言插件：

| 语言 | 扩展名 | 编译器/解释器 |
|------|--------|--------------|
| C++ | `.cpp`, `.cxx`, `.cc`, `.c++` | `g++` / `cl` |
| C | `.c` | `gcc` / `cl` |
| Python | `.py`, `.pyw` | `python` / `py` |
| C# | `.cs` | `csc` / `dotnet` |
| Java | `.java` | `javac` / `java` |
| Go | `.go` | `go` |
| Rust | `.rs` | `rustc` |
| JavaScript | `.js`, `.mjs`, `.cjs` | `node` |
| TypeScript | `.ts`, `.tsx` | `ts-node` (via npx) |
| Shell | `.sh`, `.bash`, `.bat`, `.cmd` | `bash` / `cmd` |
| Dart | `.dart` | `dart` |
| Swift | `.swift` | `swiftc` |
| Ruby | `.rb` | `ruby` |

---

## 七、开发最佳实践

1. **依赖声明**：在 `__deps__` 中声明所需的外部工具，`check_dependencies()` 会自动验证
2. **错误处理**：使用 `Console.info()`, `Console.success()`, `Console.warn()`, `Console.error()` 输出彩色日志
3. **安全执行**：使用 `safe_run()` 替代 `subprocess.run()`，自动进行命令白名单检查
4. **配置访问**：通过 `config.get('key', default)` 读取用户配置
5. **路径处理**：使用 `Path` 对象而非字符串拼接

---

## 八、总结

CodeKit OI 的插件系统提供了清晰的扩展接口：

- **语言插件**：通过继承 `LanguageHandler` 支持新语言，自动集成 `run`、`compile`、`pack` 等命令
- **命令插件**：通过继承 `CommandPlugin` 添加自定义子命令，与 CodeKit 核心功能无缝协作
- **热加载**：支持 `ck plugin reload` 无需重启即可生效新插件

插件机制使得 CodeKit OI 能够灵活适应不同竞赛环境和个性化需求，是信息学竞赛选手的得力助手。

