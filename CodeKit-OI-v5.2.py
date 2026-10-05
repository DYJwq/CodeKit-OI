#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CodeKit OI 特供版 – 专为信息学竞赛（OI）设计的代码管理工具
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
版本：OI-v5.2
新增功能（v5.2）：
  - 简化配置：judge / test 自动检测数据目录（data/in → data → .），
    无配置文件时自动生成子任务；--input-dir 变为可选
  - 修复 ddmin 终止条件的小 bug（granularity >= len(chunks) 改为 len(lines)）
  - 新增 `ck interact` 子指令：交互题支持
  - 新增 `ck rip` 子指令：纪念 fetch / upgrade
保留 v5.1 所有功能：
  - `--shrink` 使用 ddmin 增量调试
保留 v5.0 所有功能：
  - template_dir 默认值迁移到 ~/.codekit/templates
  - 全局 SIGINT handler
  - main() 顶层异常捕获，崩溃日志写入 ~/.codekit/logs/crash_YYYYMMDD.log
  - `anal_log` 子命令
  - 全局 --quiet/-q 开关
  - `ck judge --format json`
  - `ck snippet --from-file`
"""

LoveTeto: bool = True
LoveMiku: float = 3 / 4

import os
import sys
import subprocess as sp
import shutil
import time
import json
import argparse
import glob
import fnmatch
import platform
import importlib
import importlib.util
import urllib.request
import urllib.parse
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Callable, Any, Union
import re
import shlex
import hashlib
import tempfile
import atexit
import logging
import signal
from functools import lru_cache, wraps
from dataclasses import dataclass, field
from contextlib import contextmanager
import io
import threading
import queue
import copy
import math
import webbrowser
import random
import difflib
import traceback

# ======================== 可选依赖导入（缺失时降级） ========================
try:
    import yaml
except ImportError:
    yaml = None

try:
    import psutil
except ImportError:
    psutil = None

try:
    import resource
except ImportError:
    resource = None

try:
    import tqdm
except ImportError:
    tqdm = None

try:
    import requests
except ImportError:
    requests = None

try:
    from plyer import notification
except ImportError:
    notification = None

# ======================== 日志设置 =========================
logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
logger = logging.getLogger('CodeKit')

# ======================== 全局常量 =========================
if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
    SCRIPT_DIR = Path(sys._MEIPASS)
else:
    SCRIPT_DIR = Path(__file__).parent.resolve()

HOME = Path(os.path.expanduser('~'))
GLOBAL_CONFIG_DIR = HOME / '.codekit'
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / 'config.json'
GLOBAL_CONFIG_YAML = GLOBAL_CONFIG_DIR / 'config.yaml'
LEGACY_CONFIG_FILE = HOME / '.codemanager'
PLUGINS_DIR = GLOBAL_CONFIG_DIR / 'plugins'
PLUGINS_ENABLED_DIR = PLUGINS_DIR / 'enabled'
PLUGINS_AVAILABLE_DIR = PLUGINS_DIR / 'available'
COMMANDS_DIR = GLOBAL_CONFIG_DIR / 'commands'
SNIPPETS_DIR = GLOBAL_CONFIG_DIR / 'snippets'
CONTEST_DIR = GLOBAL_CONFIG_DIR / 'contests'
COUNTEREXAMPLE_DIR = Path.cwd() / '.codekit-counterexamples'
FAILURES_DIR = Path.cwd() / '.codekit-failures'
DEFAULT_WATCH_EXCLUDE = ['.git', '__pycache__', '*.tmp', '*.swp', '*.log', '*.pyc']
DEFAULT_DEBUGGER = 'gdb'
HISTORY_FILE = GLOBAL_CONFIG_DIR / 'history.json'
SNAPSHOT_DIR = GLOBAL_CONFIG_DIR / 'snapshots'
LOGS_DIR = GLOBAL_CONFIG_DIR / 'logs'

EXE_SUFFIX = '.exe' if sys.platform == 'win32' else ''
VERBOSE = False
DRY_RUN = False
QUIET = False

# ======================== 子进程跟踪与 SIGINT 处理器 ========================
_active_popen: List[sp.Popen] = []
_active_popen_lock = threading.Lock()
_sigint_installed = False


def _register_popen(proc: sp.Popen) -> None:
    try:
        with _active_popen_lock:
            _active_popen.append(proc)
    except Exception:
        pass


def _unregister_popen(proc: sp.Popen) -> None:
    try:
        with _active_popen_lock:
            try:
                _active_popen.remove(proc)
            except ValueError:
                pass
    except Exception:
        pass


def _cleanup_all_popen() -> None:
    try:
        with _active_popen_lock:
            procs = list(_active_popen)
    except Exception:
        procs = []
    for p in procs:
        try:
            if p.poll() is None:
                p.terminate()
        except Exception:
            pass
    deadline = time.time() + 1.5
    while time.time() < deadline:
        try:
            if all(p.poll() is not None for p in procs):
                break
        except Exception:
            break
        time.sleep(0.05)
    for p in procs:
        try:
            if p.poll() is None:
                p.kill()
        except Exception:
            pass
    try:
        with _active_popen_lock:
            _active_popen.clear()
    except Exception:
        pass


def _handle_sigint(signum, frame):
    try:
        try:
            sys.stderr.write("\n[Warning] 收到 SIGINT，正在终止所有子进程...\n")
            sys.stderr.flush()
        except Exception:
            pass
        _cleanup_all_popen()
    except Exception:
        pass
    raise KeyboardInterrupt()


def _install_sigint_handler() -> None:
    global _sigint_installed
    if _sigint_installed:
        return
    try:
        signal.signal(signal.SIGINT, _handle_sigint)
        _sigint_installed = True
    except (ValueError, OSError, AttributeError):
        pass


# ======================== 崩溃日志 ========================
def _write_crash_log(exc: BaseException) -> Optional[Path]:
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        log_file = LOGS_DIR / f'crash_{datetime.now().strftime("%Y%m%d")}.log'
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write("=" * 60 + "\n")
            f.write(f"Time: {datetime.now().isoformat()}\n")
            try:
                f.write(f"argv: {sys.argv}\n")
            except Exception:
                f.write("argv: <unavailable>\n")
            f.write(f"Python: {sys.version}\n")
            try:
                f.write(f"Platform: {platform.platform()}\n")
            except Exception:
                pass
            f.write(f"Exception: {type(exc).__name__}: {exc}\n")
            f.write("-" * 60 + "\n")
            f.write("Traceback:\n")
            try:
                traceback.print_exception(type(exc), exc, exc.__traceback__, file=f)
            except Exception:
                pass
            f.write("-" * 60 + "\n")
            f.write("Last 20 history entries:\n")
            try:
                hist_file = HOME / '.codekit_history'
                if hist_file.exists():
                    with open(hist_file, 'r', encoding='utf-8', errors='replace') as hf:
                        lines = hf.readlines()
                        for line in lines[-20:]:
                            f.write(line)
                        if lines and not lines[-1].endswith('\n'):
                            f.write('\n')
            except Exception:
                pass
            f.write("\n")
        return log_file
    except Exception:
        return None


# ======================== Quiet 流 ========================
class _QuietStream:
    def __init__(self, original):
        self._original = original

    def write(self, *args, **kwargs):
        return 0

    def writelines(self, *args, **kwargs):
        pass

    def flush(self):
        pass

    def isatty(self):
        try:
            return self._original.isatty()
        except Exception:
            return False

    def fileno(self):
        try:
            return self._original.fileno()
        except Exception:
            return -1

    def __getattr__(self, name):
        return getattr(self._original, name)


_quiet_installed = False
_original_stdout = None
_original_stderr = None


def _install_quiet_streams() -> None:
    global _quiet_installed, _original_stdout, _original_stderr
    if _quiet_installed:
        return
    _original_stdout = sys.stdout
    _original_stderr = sys.stderr
    sys.stdout = _QuietStream(_original_stdout)
    sys.stderr = _QuietStream(_original_stderr)
    _quiet_installed = True


# ======================== 彩色输出 ========================
class Color:
    RESET   = '\033[0m'
    RED     = '\033[91m'
    GREEN   = '\033[92m'
    YELLOW  = '\033[93m'
    BLUE    = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN    = '\033[96m'
    WHITE   = '\033[97m'
    BOLD    = '\033[1m'


class Console:
    _enabled = True
    _quiet = False

    @classmethod
    def set_color(cls, enabled: bool):
        cls._enabled = enabled

    @classmethod
    def set_quiet(cls, quiet: bool):
        cls._quiet = quiet
        try:
            if quiet:
                logger.setLevel(logging.CRITICAL + 1)
            else:
                logger.setLevel(logging.DEBUG if VERBOSE else logging.INFO)
        except Exception:
            pass

    @classmethod
    def _c(cls, text: str, color: str) -> str:
        return f"{color}{text}{Color.RESET}" if cls._enabled else text

    @classmethod
    def info(cls, msg: str):
        if cls._quiet:
            return
        print(cls._c(f"[Info] {msg}", Color.CYAN))
        try:
            logger.info(msg)
        except Exception:
            pass

    @classmethod
    def success(cls, msg: str):
        if cls._quiet:
            return
        print(cls._c(f"[OK] {msg}", Color.GREEN))
        try:
            logger.info(msg)
        except Exception:
            pass

    @classmethod
    def warn(cls, msg: str):
        if cls._quiet:
            return
        print(cls._c(f"[Warning] {msg}", Color.YELLOW))
        try:
            logger.warning(msg)
        except Exception:
            pass

    @classmethod
    def error(cls, msg: str):
        if cls._quiet:
            return
        print(cls._c(f"[Error] {msg}", Color.RED))
        try:
            logger.error(msg)
        except Exception:
            pass

    @classmethod
    def bold(cls, msg: str):
        if cls._quiet:
            return
        print(cls._c(msg, Color.BOLD))

    @classmethod
    def debug(cls, msg: str):
        if cls._quiet:
            return
        if VERBOSE:
            print(cls._c(f"[Debug] {msg}", Color.MAGENTA))
            try:
                logger.debug(msg)
            except Exception:
                pass


# ======================== 审计日志 ========================
def audit_log(cmd_line: str):
    try:
        history_file = HOME / '.codekit_history'
        with open(history_file, 'a', encoding='utf-8') as f:
            ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            f.write(f"[{ts}] {cmd_line}\n")
    except IOError:
        pass


# ======================== 安全输入辅助 ========================
def safe_input(prompt: str, default: str = 'n') -> str:
    """在非交互环境下返回默认值，避免 EOFError/KeyboardInterrupt。"""
    try:
        if not sys.stdin.isatty():
            return default
        return input(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        return default


# ======================== 自动检测输入目录（v5.2 新增） ========================
def _auto_detect_input_dir(base: Optional[Path] = None) -> Path:
    """自动检测输入数据目录。

    优先级：``data/in`` → ``data`` → 当前目录（``.``）。
    优先返回包含 ``*.in`` 文件的目录；若都不含，则返回第一个存在的目录，
    最后兜底返回当前工作目录。
    """
    base_dir = Path(base) if base else Path.cwd()
    candidates = [base_dir / 'data' / 'in', base_dir / 'data', base_dir]
    for cand in candidates:
        try:
            if cand.is_dir() and any(cand.glob('*.in')):
                return cand
        except Exception:
            continue
    for cand in candidates:
        try:
            if cand.is_dir():
                return cand
        except Exception:
            continue
    return base_dir


def _auto_detect_problem_config() -> Dict[str, Any]:
    """返回包含默认值的题目配置字典（v5.2 新增）。"""
    return {
        'name': Path.cwd().name or 'Unnamed Problem',
        'time_limit': 1.0,
        'memory_limit': 256,
        'input_dir': None,
        'output_dir': None,
        'subtasks': None,
        'checker': None,
        'scoring': 'oi',
    }


# ======================== 配置管理 ========================
sentinel = object()


class ConfigManager:
    _instance = None
    _last_load_time = 0.0

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        self._raw = {}
        self._last_saved = {}
        self._load_all()

    def _defaults(self) -> Dict[str, Any]:
        return {
            'ai': {
                'api_key': None,
                'provider': 'openai',
                'model': 'gpt-4',
                'base_url': None,
                'ollama_url': 'http://localhost:11434/api/generate',
                'llama_url': 'http://localhost:8080/completion',
                'context_depth': 3,
                'include_git_diff': True,
                'include_comments': True,
            },
            'plugins': {
                'dir': str(PLUGINS_DIR),
                'enabled_only': True,
                'auto_load': True,
                'allowed_origins': ['local']
            },
            'commands': {
                'dir': str(COMMANDS_DIR),
                'auto_load': True,
            },
            'watch': {
                'exclude': list(DEFAULT_WATCH_EXCLUDE),
                'poll_interval': 1.0,
                'use_polling': False,
                'recursive': True
            },
            'debug': {
                'debugger': DEFAULT_DEBUGGER,
                'install_hints': {
                    'gdb': 'sudo apt install gdb || sudo yum install gdb',
                    'lldb': 'sudo apt install lldb || sudo yum install lldb',
                    'valgrind': 'sudo apt install valgrind || sudo yum install valgrind',
                    'strace': 'sudo apt install strace || sudo yum install strace'
                }
            },
            'terminal': {
                'default': 'auto',
                'fallback': 'xterm',
                'detect_order': ['wezterm', 'alacritty', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'xterm']
            },
            'git': {
                'allow_commands': ['clone', 'pull', 'push', 'commit', 'status', 'log', 'fetch', 'checkout'],
                'deny_options': ['--upload-pack', '--receive-pack', '--exec']
            },
            'security': {
                'plugin_whitelist_only': True,
                'env_override_prefix': 'CODEKIT_'
            },
            'config': {
                'diff_on_load': False,
            },
            'gcc_version': 'c++17',
            'default_language': 'cpp',
            'backup_auto': 'false',
            'color_output': 'true',
            'work_dir': str(SCRIPT_DIR),
            'safe_clean': 'true',
            'clean_confirm': 'true',
            'template_dir': str(GLOBAL_CONFIG_DIR / 'templates'),
            'timeout': '60',
            'env_file': '.env',
            'upgrade_source': 'https://raw.githubusercontent.com/CodeKit/CodeKit/main/CodeKit.py',
            'project_meta_file': '.codekit-meta.json',
            'env_fingerprint_file': '.codekit-env.json',
            'snippets_dir': str(SNIPPETS_DIR),
            'contest_dir': str(CONTEST_DIR),
            'oi': {
                'gpp_versions': ['g++-14', 'g++-13', 'g++-12', 'g++-11', 'g++'],
                'default_gpp': 'g++',
                'timeout': 5,
                'memory_limit_mb': 512,
                'author': os.environ.get('USER', 'OIer'),
                # v5.2: 默认数据目录（自动检测的顺序）
                'default_input_dir': None,
                'default_output_dir': None,
            },
            'check': {
                'array_size_warning': 100000,
                'recursion_depth_warning': 1000000,
                'int_overflow_warning': True,
            },
            'copy': {
                'default_command': 'auto',
            },
            'fetch': {
                'cache_dir': str(GLOBAL_CONFIG_DIR / 'cache' / 'fetch'),
                'timeout': 10,
            },
            'submit': {
                'command_template': 'oj submit --language {language} --yes {url} {file}',
                'platforms': {
                    'luogu': {
                        'url_template': 'https://www.luogu.com.cn/problem/{problem}',
                        'language_map': {'cpp': 'cpp', 'c': 'c', 'python': 'python', 'java': 'java', 'go': 'go', 'rust': 'rust'}
                    },
                    'codeforces': {
                        'url_template': 'https://codeforces.com/problemset/problem/{contest}/{problem}',
                        'language_map': {'cpp': 'cpp', 'c': 'c', 'python': 'python', 'java': 'java', 'go': 'go', 'rust': 'rust'}
                    },
                    'atcoder': {
                        'url_template': 'https://atcoder.jp/contests/{contest}/tasks/{problem}',
                        'language_map': {'cpp': 'cpp', 'c': 'c', 'python': 'python', 'java': 'java', 'go': 'go', 'rust': 'rust'}
                    }
                }
            },
            'bench': {
                'baseline_file': '.codekit-bench.json',
                'iterations': 3,
                'threshold_percent': 20.0,
                'history_file': '.codekit-bench-history.json',
                'track_cases': 100,
            },
            'CommandFormat': [],
            'mood': {
                'state': 'normal',
                'tired_threshold_cases': 100,
            },
            'timer': {
                'default_duration': 25,
                'notification': True,
            },
            'polish': {
                'backup_suffix': '_polished',
                'auto_confirm': False,
            },
            'compile_flags': [],
        }

    def _load_all(self):
        self._raw = copy.deepcopy(self._defaults())
        self._load_from_files()
        self._apply_env_overrides()
        self._apply_legacy()
        self._apply_workdir()
        self._apply_color()
        self._last_saved = copy.deepcopy(self._raw)

    def _load_from_files(self):
        if GLOBAL_CONFIG_YAML.exists() and yaml:
            try:
                with open(GLOBAL_CONFIG_YAML, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if isinstance(data, dict):
                        self._merge(self._raw, data)
            except Exception as e:
                logger.warning(f"加载 YAML 配置失败: {e}")
        elif GLOBAL_CONFIG_FILE.exists():
            try:
                with open(GLOBAL_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self._merge(self._raw, data)
            except Exception as e:
                logger.warning(f"加载 JSON 配置失败: {e}")
        project_dir = Path.cwd() / '.codekit'
        for conf_name in ['local.json', 'config.json', 'config.yaml']:
            project_conf = project_dir / conf_name
            if project_conf.exists():
                try:
                    if conf_name.endswith('.yaml') and yaml:
                        with open(project_conf, 'r', encoding='utf-8') as f:
                            data = yaml.safe_load(f)
                    else:
                        with open(project_conf, 'r', encoding='utf-8') as f:
                            data = json.load(f)
                    if isinstance(data, dict):
                        self._merge(self._raw, data)
                except Exception as e:
                    logger.warning(f"加载项目配置 {project_conf} 失败: {e}")

    def _apply_env_overrides(self):
        prefix = self._raw['security']['env_override_prefix']
        for env_key, env_val in os.environ.items():
            if env_key.startswith(prefix):
                key_part = env_key[len(prefix):].lower()
                config_key = key_part.replace('__', '.')
                parts = config_key.split('.')
                if len(parts) == 1:
                    self._raw[parts[0]] = env_val
                else:
                    node = self._raw
                    for p in parts[:-1]:
                        if p not in node or not isinstance(node[p], dict):
                            node[p] = {}
                        node = node[p]
                    node[parts[-1]] = env_val

        env_key = os.getenv('CODEKIT_AI_KEY')
        if env_key:
            self._raw['ai']['api_key'] = env_key
        elif isinstance(self._raw.get('ai', {}).get('api_key'), str) and self._raw['ai']['api_key'].startswith('env:'):
            var = self._raw['ai']['api_key'][4:]
            self._raw['ai']['api_key'] = os.getenv(var, None)

    def _apply_legacy(self):
        if LEGACY_CONFIG_FILE.exists():
            try:
                with open(LEGACY_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if '=' in line:
                            k, v = line.split('=', 1)
                            if k == 'ai_api_key':
                                self._raw['ai']['api_key'] = v.strip()
                            elif k == 'plugins_dir':
                                self._raw['plugins']['dir'] = v.strip()
                            elif k == 'watch_exclude':
                                self._raw['watch']['exclude'] = [x.strip() for x in v.split(',')]
                            elif k == 'debugger':
                                self._raw['debug']['debugger'] = v.strip()
                            elif k == 'terminal':
                                self._raw['terminal']['default'] = v.strip()
                            elif k == 'gcc_version':
                                self._raw['gcc_version'] = v.strip()
                            elif k == 'work_dir':
                                self._raw['work_dir'] = v.strip()
                            elif k == 'template_dir':
                                self._raw['template_dir'] = v.strip()
                            elif k == 'timeout':
                                self._raw['timeout'] = v.strip()
                            elif k == 'env_file':
                                self._raw['env_file'] = v.strip()
                            else:
                                self._raw[k] = v.strip()
            except Exception as e:
                logger.warning(f'解析旧配置失败: {e}')

    def _apply_workdir(self):
        wd = self._raw.get('work_dir', '')
        if wd and Path(wd).exists():
            try:
                os.chdir(wd)
            except OSError:
                pass

    def _apply_color(self):
        color_val = self._raw.get('color_output', 'true')
        if isinstance(color_val, bool):
            enable = color_val
        else:
            enable = str(color_val).lower() == 'true'
        Console.set_color(enable)

    def _merge(self, base: Dict, override: Dict):
        for k, v in override.items():
            if k in base and isinstance(base[k], dict) and isinstance(v, dict):
                self._merge(base[k], v)
            else:
                base[k] = v

    def get(self, key: str, default=None):
        node = self._raw
        for part in key.split('.'):
            if isinstance(node, dict) and part in node:
                node = node[part]
            else:
                return default
        return node

    def __getitem__(self, key):
        val = self.get(key)
        if val is None:
            raise KeyError(key)
        return val

    def __contains__(self, key):
        return self.get(key, sentinel) is not sentinel

    def save(self):
        try:
            GLOBAL_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(GLOBAL_CONFIG_FILE, 'w', encoding='utf-8') as f:
                json.dump(self._raw, f, indent=2, ensure_ascii=False)
            self._last_saved = copy.deepcopy(self._raw)
        except Exception as e:
            Console.error(f'保存配置失败: {e}')

    def reload(self):
        old = copy.deepcopy(self._raw)
        self._load_all()
        if self.get('config.diff_on_load', False):
            self.diff(old, self._raw)
        Console.success("配置已热重载")

    def diff(self, old: Dict = None, new: Dict = None) -> None:
        if old is None:
            old = self._last_saved
        if new is None:
            new = self._raw
        old_str = json.dumps(old, indent=2, sort_keys=True, default=str).splitlines()
        new_str = json.dumps(new, indent=2, sort_keys=True, default=str).splitlines()
        diff = difflib.unified_diff(old_str, new_str, fromfile='旧配置', tofile='新配置', lineterm='')
        diff_lines = list(diff)
        if diff_lines:
            Console.bold("配置差异:")
            for line in diff_lines:
                if line.startswith('+'):
                    print(Console._c(line, Color.GREEN))
                elif line.startswith('-'):
                    print(Console._c(line, Color.RED))
                else:
                    print(line)
        else:
            Console.info("配置无变化")


config = ConfigManager()


# ======================== AI 服务 ========================
class AIService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.provider = config.get('ai.provider', 'openai')
        self.model = config.get('ai.model', 'gpt-4')
        self.api_key = config.get('ai.api_key')
        self.base_url = config.get('ai.base_url')
        if not self.base_url:
            if self.provider == 'ollama':
                self.base_url = config.get('ai.ollama_url', 'http://localhost:11434/api/generate')
            elif self.provider == 'llama.cpp':
                self.base_url = config.get('ai.llama_url', 'http://localhost:8080/completion')
            else:
                self.base_url = 'https://api.openai.com/v1/chat/completions'
        self.context_depth = config.get('ai.context_depth', 3)

    def _collect_context(self, cwd: Path) -> str:
        ctx_parts = []
        if self.config.get('ai.include_git_diff', True) and shutil.which('git'):
            try:
                diff_cmd = ['git', 'diff', '--staged']
                ret = sp.run(diff_cmd, capture_output=True, text=True, timeout=5)
                if ret.stdout.strip():
                    ctx_parts.append(f"### Git Staged Diff ###\n{ret.stdout[:500]}")
            except Exception:
                pass
        if self.context_depth > 0:
            tree_lines = []

            def walk_dir(path: Path, depth: int, prefix: str = ""):
                if depth > self.context_depth:
                    return
                try:
                    items = sorted(path.iterdir(), key=lambda x: (not x.is_dir(), x.name))
                    for idx, item in enumerate(items):
                        if item.name.startswith('.'):
                            continue
                        is_last = (idx == len(items) - 1)
                        tree_lines.append(f"{prefix}{'└── ' if is_last else '├── '}{item.name}{'/' if item.is_dir() else ''}")
                        if item.is_dir() and depth < self.context_depth:
                            walk_dir(item, depth + 1, prefix + ('    ' if is_last else '│   '))
                except PermissionError:
                    pass
            walk_dir(cwd, 0)
            if tree_lines:
                ctx_parts.append("### Project Structure ###\n" + "\n".join(tree_lines[:30]))
        if self.config.get('ai.include_comments', True):
            comments = []
            for ext in ['.py', '.cpp', '.c', '.java', '.js', '.ts', '.go', '.rs']:
                for f in cwd.glob(f'*{ext}')[:3]:
                    try:
                        lines = f.read_text(encoding='utf-8', errors='ignore').splitlines()
                        for line in lines[:30]:
                            stripped = line.strip()
                            if stripped.startswith('#') or stripped.startswith('//') or stripped.startswith('/*'):
                                comments.append(stripped)
                    except Exception:
                        pass
            if comments:
                ctx_parts.append("### Recent Comments ###\n" + "\n".join(comments[:10]))
        return "\n\n".join(ctx_parts)

    def generate(self, prompt: str, system_prompt: Optional[str] = None,
                 temperature: float = 0.7, max_tokens: int = 500,
                 context_aware: bool = True) -> str:
        if context_aware:
            context = self._collect_context(Path.cwd())
            if context:
                prompt = f"Context:\n{context}\n\nQuestion: {prompt}"
        try:
            if self.provider == 'openai':
                messages = []
                if system_prompt:
                    messages.append({'role': 'system', 'content': system_prompt})
                messages.append({'role': 'user', 'content': prompt})
                data = {
                    'model': self.model,
                    'messages': messages,
                    'temperature': temperature,
                    'max_tokens': max_tokens
                }
                headers = {'Authorization': f'Bearer {self.api_key}', 'Content-Type': 'application/json'}
                req = urllib.request.Request(self.base_url, data=json.dumps(data).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req, timeout=60) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    try:
                        return result['choices'][0]['message']['content'].strip()
                    except (KeyError, IndexError) as e:
                        raise RuntimeError(f"OpenAI 响应格式异常: {result}") from e
            elif self.provider == 'ollama':
                data = {
                    'model': self.model,
                    'prompt': prompt,
                    'stream': False,
                    'options': {
                        'temperature': temperature,
                        'num_predict': max_tokens
                    }
                }
                if system_prompt:
                    data['system'] = system_prompt
                headers = {'Content-Type': 'application/json'}
                req = urllib.request.Request(self.base_url, data=json.dumps(data).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return result.get('response', '').strip()
            elif self.provider == 'llama.cpp':
                data = {
                    'prompt': prompt,
                    'temperature': temperature,
                    'n_predict': max_tokens,
                    'stream': False
                }
                headers = {'Content-Type': 'application/json'}
                req = urllib.request.Request(self.base_url, data=json.dumps(data).encode('utf-8'), headers=headers)
                with urllib.request.urlopen(req, timeout=120) as resp:
                    result = json.loads(resp.read().decode('utf-8'))
                    return result.get('content', '').strip()
            else:
                raise ValueError(f"不支持的 AI provider: {self.provider}")
        except Exception as e:
            if LoveTeto:
                Console.error("Nee~! 这段代码我也不会，要不你问问 Miku？")
            raise RuntimeError(f"AI 生成失败: {e}") from e


# ======================== 安全守卫 ========================
class SecurityGuard:
    @staticmethod
    def is_plugin_allowed(plugin_path: str) -> bool:
        try:
            resolved = Path(plugin_path).resolve()
            plugins_root = Path(config.get('plugins.dir', str(PLUGINS_DIR))).resolve()
            allowed_dirs = [plugins_root / 'available', plugins_root / 'enabled']
            for d in allowed_dirs:
                if d in resolved.parents or resolved.parent == d:
                    return True
            if not config.get('security.plugin_whitelist_only', True):
                return plugins_root in resolved.parents or resolved.parent == plugins_root
            return False
        except Exception:
            return False

    @staticmethod
    def sanitize_git_args(args: List[str]) -> List[str]:
        if not args:
            return []
        allowed = config.get('git.allow_commands', ['clone', 'pull', 'push', 'commit', 'status', 'log', 'fetch', 'checkout'])
        deny_opts = config.get('git.deny_options', ['--upload-pack', '--receive-pack', '--exec'])
        cmd = args[0]
        if cmd not in allowed:
            raise ValueError(f'Git 子命令 "{cmd}" 不在白名单中')
        cleaned = [cmd]
        for arg in args[1:]:
            if re.search(r'[;&|`$(){}<>]', arg):
                raise ValueError(f'参数包含非法字符: {arg}')
            for opt in deny_opts:
                if arg.startswith(opt):
                    raise ValueError(f'禁止使用选项: {arg}')
            cleaned.append(arg)
        return cleaned

    @staticmethod
    def safe_path_join(base: Path, sub: str) -> Path:
        resolved = (base / sub).resolve()
        if not resolved.is_relative_to(base.resolve()):
            raise ValueError(f'路径超出基目录: {sub}')
        return resolved


# ======================== 安全执行 ========================
@dataclass
class RunResult:
    stdout: str
    stderr: str
    returncode: int
    command: List[str]


def safe_run(command: Union[str, List[str]], timeout: int = 60, check: bool = True,
             env: Optional[Dict] = None, cwd: Optional[str] = None,
             retry: int = 0, **kwargs) -> RunResult:
    """执行命令并返回结果。使用 Popen 以支持全局 SIGINT 终止。"""
    if isinstance(command, str):
        cmd_list = shlex.split(command)
    else:
        cmd_list = list(command)
    if not cmd_list:
        raise ValueError('空命令')
    if cmd_list[0] == 'git':
        cmd_list = SecurityGuard.sanitize_git_args(cmd_list[1:])
        cmd_list = ['git'] + cmd_list
    run_env = os.environ.copy()
    if env:
        run_env.update(env)
    dangerous_env = ['LD_PRELOAD', 'LD_LIBRARY_PATH', 'PYTHONPATH']
    for d in dangerous_env:
        run_env.pop(d, None)

    attempt = 0
    while True:
        run_kwargs = dict(kwargs)
        proc = sp.Popen(
            cmd_list,
            stdout=sp.PIPE,
            stderr=sp.PIPE,
            text=True,
            encoding='utf-8',
            errors='replace',
            env=run_env,
            cwd=cwd,
            **run_kwargs
        )
        _register_popen(proc)
        try:
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    proc.communicate(timeout=2)
                except Exception:
                    pass
                logger.error(f'命令超时 ({timeout}s): {" ".join(cmd_list)}')
                raise
        finally:
            _unregister_popen(proc)

        returncode = proc.returncode
        last_result = RunResult(
            stdout=stdout,
            stderr=stderr,
            returncode=returncode,
            command=cmd_list
        )
        if returncode != 0 and check:
            if attempt < retry:
                logger.warning(f'命令失败 (返回 {returncode}), 重试 {attempt + 1}/{retry}')
                attempt += 1
                time.sleep(1)
                continue
            raise sp.CalledProcessError(returncode, cmd_list, stdout, stderr)
        return last_result


# ======================== 内存限制辅助 ========================
def _make_memory_limiter(limit_mb: int):
    def _limit():
        try:
            import resource as _r
            limit_bytes = limit_mb * 1024 * 1024
            _r.setrlimit(_r.RLIMIT_AS, (limit_bytes, limit_bytes))
        except Exception:
            pass
    return _limit


def _get_memory_limit_preexec(limit_mb: Optional[int]):
    if sys.platform == 'win32':
        return None
    if not limit_mb or limit_mb <= 0:
        return None
    if resource is None:
        return None
    return _make_memory_limiter(limit_mb)


# ======================== 语言处理器 ========================
class LanguageHandler(ABC):
    name: str = "unnamed"
    extensions: List[str] = []
    __deps__: List[str] = []

    def __init__(self, config: ConfigManager):
        self.config = config

    @abstractmethod
    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        pass

    @abstractmethod
    def compile(self, file: Path, sanitize: bool = False) -> Tuple[bool, str]:
        pass

    def check_dependencies(self) -> bool:
        return True

    def pack(self, file: Path, output: Optional[str] = None, options: List[str] = None) -> bool:
        Console.error(f"{self.name} 不支持打包")
        return False

    def clean(self, file: Optional[Path] = None) -> bool:
        Console.info(f"{self.name} 没有定义额外的清理操作")
        return True

    def build(self, file: Optional[Path] = None) -> bool:
        Console.error(f"{self.name} 不支持 build 操作")
        return False

    def help(self) -> str:
        return f"{self.name} 插件，支持扩展名: {', '.join(self.extensions)}"


class CompiledLanguageHandler(LanguageHandler):
    compiler_cmd: str = None
    std_flag: str = None
    output_flag: str = None
    sanitize_enabled: bool = False

    def check_dependencies(self) -> bool:
        if self.compiler_cmd and shutil.which(self.compiler_cmd) is None:
            Console.error(f"未找到 {self.compiler_cmd}，请安装相应的编译器")
            return False
        return True

    def compile(self, file: Path, sanitize: bool = False) -> Tuple[bool, str]:
        out = file.with_suffix(EXE_SUFFIX)
        std = self.config.get('gcc_version', 'c++17') if self.std_flag else ''
        if self.compiler_cmd and shutil.which(self.compiler_cmd):
            cmd = [self.compiler_cmd, str(file)]
            extra_flags = self.config.get('compile_flags', [])
            if extra_flags:
                cmd.extend(extra_flags)
            if self.std_flag and std:
                if not any(f.startswith('-std=') for f in extra_flags):
                    cmd.append(self.std_flag + std)
            if self.output_flag:
                cmd.append(f"{self.output_flag}{out}")
            else:
                cmd.extend(['-o', str(out)])
            if sanitize:
                cmd.extend(['-fsanitize=address,undefined', '-g', '-fno-omit-frame-pointer'])
            Console.info(f"编译 {self.name}: {' '.join(cmd)}")
            ret = safe_run(cmd, check=False)
            if ret.returncode == 0:
                Console.success(f"编译成功: {out}")
                return True, ""
            else:
                Console.error("编译失败")
                return False, ret.stderr
        return self._fallback_compile(file, out)

    def _fallback_compile(self, file: Path, out: Path) -> Tuple[bool, str]:
        return False, "无法编译"

    def run(self, file: Path, args: List[str], version: str = None, sanitize: bool = False) -> bool:
        ok, err = self.compile(file, sanitize=sanitize)
        if not ok:
            return False
        out = file.with_suffix(EXE_SUFFIX)
        Console.info(f"运行 {out}")
        ret = safe_run([str(out)] + args)
        return ret.returncode == 0


class CppHandler(CompiledLanguageHandler):
    name = "C++"
    extensions = ['.cpp', '.cxx', '.cc', '.c++']
    compiler_cmd = 'g++'
    std_flag = '-std='
    output_flag = '-o'
    __deps__ = ["g++>=9", "make>=4"]

    def _fallback_compile(self, file: Path, out: Path) -> Tuple[bool, str]:
        if shutil.which('cl'):
            cmd = ['cl', '/EHsc', '/std:c++latest', str(file), f'/Fe:{out}']
            Console.info(f"编译 C++ (cl): {' '.join(cmd)}")
            ret = safe_run(cmd, check=False)
            if ret.returncode == 0:
                Console.success(f"编译成功: {out}")
                return True, ""
            return False, ret.stderr
        return False, "未找到兼容编译器"


class CHandler(CompiledLanguageHandler):
    name = "C"
    extensions = ['.c']
    compiler_cmd = 'gcc'
    std_flag = '-std='
    output_flag = '-o'
    __deps__ = ["gcc>=9"]

    def _fallback_compile(self, file: Path, out: Path) -> Tuple[bool, str]:
        if shutil.which('cl'):
            cmd = ['cl', '/std:c17', str(file), f'/Fe:{out}']
            Console.info(f"编译 C (cl): {' '.join(cmd)}")
            ret = safe_run(cmd, check=False)
            if ret.returncode == 0:
                Console.success(f"编译成功: {out}")
                return True, ""
            return False, ret.stderr
        return False, "未找到兼容编译器"


class PythonHandler(LanguageHandler):
    name = "Python"
    extensions = ['.py', '.pyw']
    __deps__ = ["python>=3.6"]

    def check_dependencies(self) -> bool:
        if shutil.which('py') is None and shutil.which('python') is None and shutil.which('python3') is None:
            Console.error("未找到 Python 解释器")
            return False
        return True

    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        interpreter_cmd = self._get_interpreter_cmd(version)
        Console.info(f"运行 Python: {file} (version: {version if version else 'default'})")
        cmd = interpreter_cmd + [str(file)] + args
        ret = safe_run(cmd)
        return ret.returncode == 0

    def _get_interpreter_cmd(self, version: str = None) -> List[str]:
        if version:
            if sys.platform == 'win32':
                if shutil.which('py'):
                    return ['py', f'-{version}']
                else:
                    cmd = f'python{version}'
                    if shutil.which(cmd):
                        return [cmd]
            else:
                cmd = f'python{version}'
                if shutil.which(cmd):
                    return [cmd]
                alt = f'python{version.split(".")[0]}'
                if shutil.which(alt):
                    return [alt]
            Console.warn(f"未找到指定版本的 Python: {version}，将使用默认解释器")
        if shutil.which('py'):
            return ['py']
        elif shutil.which('python'):
            return ['python']
        elif shutil.which('python3'):
            return ['python3']
        else:
            return ['python']

    def compile(self, file: Path, sanitize: bool = False) -> Tuple[bool, str]:
        Console.warn("Python 是解释型语言，无法编译")
        return False, "解释型语言无法编译"

    def pack(self, file: Path, output: Optional[str] = None, options: List[str] = None) -> bool:
        if shutil.which('pyinstaller') is None:
            Console.error("未安装 PyInstaller，请运行: pip install pyinstaller")
            return False
        cmd = ['pyinstaller', str(file)] + (options or [])
        Console.info(f"打包: {' '.join(cmd)}")
        ret = safe_run(cmd)
        if ret.returncode == 0:
            Console.success("打包完成！可执行文件位于 dist/ 目录")
            return True
        Console.error("打包失败")
        return False


# ======================== 插件注册表 ========================
class PluginRegistry:
    _handlers: Dict[str, LanguageHandler] = {}
    _handler_deps: Dict[str, List[str]] = {}
    _loaded_plugins: List[str] = []
    _initialized: bool = False

    @classmethod
    def register(cls, handler_class):
        try:
            instance = handler_class(config)
            deps = getattr(handler_class, '__deps__', [])
            if deps:
                cls._handler_deps[handler_class.__name__] = deps
            if instance.check_dependencies():
                for ext in instance.extensions:
                    cls._handlers[ext] = instance
                Console.debug(f"插件 {instance.name} 注册成功，扩展名: {instance.extensions}")
            else:
                Console.warn(f"插件 {instance.name} 依赖检查未通过，已跳过")
        except Exception as e:
            Console.error(f"注册插件 {handler_class.__name__} 失败: {e}")
            if VERBOSE:
                traceback.print_exc()

    @classmethod
    def get_handler(cls, ext: str) -> Optional[LanguageHandler]:
        return cls._handlers.get(ext.lower())

    @classmethod
    def get_all_handlers(cls):
        return set(cls._handlers.values())

    @classmethod
    def get_handler_deps(cls, handler_name: str) -> List[str]:
        return cls._handler_deps.get(handler_name, [])

    @classmethod
    def initialize(cls):
        if cls._initialized:
            cls.load_external_plugins()
            return
        cls.register(CppHandler)
        cls.register(CHandler)
        cls.register(PythonHandler)
        cls.load_external_plugins()
        cls._initialized = True

    @classmethod
    def load_external_plugins(cls, reload: bool = False):
        plugin_dir = Path(config.get('plugins.dir', str(PLUGINS_DIR)))
        if not plugin_dir.exists():
            return
        for py_file in plugin_dir.glob('*.py'):
            if not SecurityGuard.is_plugin_allowed(str(py_file)):
                continue
            if py_file.stem in cls._loaded_plugins:
                continue
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                module.__dict__.update({
                    'LanguageHandler': LanguageHandler,
                    'CompiledLanguageHandler': CompiledLanguageHandler,
                    'Config': ConfigManager,
                    'Console': Console,
                    'safe_run': safe_run,
                    'Path': Path,
                    'Optional': Optional,
                    'List': List,
                    'Tuple': Tuple,
                    'shutil': shutil,
                })
                spec.loader.exec_module(module)
                if hasattr(module, 'Handler'):
                    handler_class = getattr(module, 'Handler')
                    if issubclass(handler_class, LanguageHandler):
                        handler_class._external = True
                        cls.register(handler_class)
                        Console.debug(f"外部插件加载: {py_file.name}")
                        cls._loaded_plugins.append(py_file.stem)
                else:
                    Console.warn(f"插件文件 {py_file.name} 未定义 Handler 类")
            except Exception as e:
                Console.error(f"加载外部插件 {py_file.name} 失败: {e}")
                if VERBOSE:
                    traceback.print_exc()

    @classmethod
    def reload_plugins(cls):
        to_remove = []
        for ext, handler in cls._handlers.items():
            if hasattr(handler, '_external') and getattr(handler, '_external', False):
                to_remove.append(ext)
        for ext in to_remove:
            del cls._handlers[ext]
        cls._loaded_plugins.clear()
        cls.load_external_plugins(reload=True)
        Console.success("插件热加载完成")


# ======================== 命令插件基类与注册表 ========================
class CommandPlugin(ABC):
    name: str = None

    def get_name(self) -> str:
        if self.name:
            return self.name
        return self.__class__.__name__.lower()

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.get_name(), description=f"自定义命令: {self.get_name()}")
        return parser

    @abstractmethod
    def run(self, parsed_args: argparse.Namespace, code_manager: 'CodeManager') -> bool:
        pass

    def check_dependencies(self) -> bool:
        return True


class CommandRegistry:
    _commands: Dict[str, CommandPlugin] = {}

    @classmethod
    def register(cls, plugin_class):
        try:
            instance = plugin_class()
            if not instance.check_dependencies():
                Console.warn(f"命令插件 {instance.get_name()} 依赖检查未通过，已跳过")
                return
            name = instance.get_name()
            if name in cls._commands:
                Console.warn(f"命令 {name} 已存在，跳过重复注册")
                return
            cls._commands[name] = instance
            Console.debug(f"命令插件 {name} 注册成功")
        except Exception as e:
            Console.error(f"注册命令插件 {plugin_class.__name__} 失败: {e}")
            if VERBOSE:
                traceback.print_exc()

    @classmethod
    def get_command(cls, name: str) -> Optional[CommandPlugin]:
        return cls._commands.get(name)

    @classmethod
    def list_commands(cls) -> List[str]:
        return list(cls._commands.keys())

    @classmethod
    def load_external_commands(cls):
        cmd_dir = Path(config.get('commands.dir', str(COMMANDS_DIR)))
        if not cmd_dir.exists():
            return
        for py_file in cmd_dir.glob('*.py'):
            try:
                spec = importlib.util.spec_from_file_location(py_file.stem, py_file)
                if spec is None or spec.loader is None:
                    continue
                module = importlib.util.module_from_spec(spec)
                module.__dict__.update({
                    'CommandPlugin': CommandPlugin,
                    'CodeManager': 'CodeManager',
                    'Console': Console,
                    'config': config,
                    'Path': Path,
                    'Optional': Optional,
                    'List': List,
                    'Dict': Dict,
                    'argparse': argparse,
                    'safe_run': safe_run,
                })
                spec.loader.exec_module(module)
                for attr_name in dir(module):
                    attr = getattr(module, attr_name)
                    if (isinstance(attr, type) and
                            issubclass(attr, CommandPlugin) and
                            attr is not CommandPlugin):
                        cls.register(attr)
                        Console.debug(f"外部命令插件加载: {py_file.name} -> {attr.__name__}")
            except Exception as e:
                Console.error(f"加载外部命令插件 {py_file.name} 失败: {e}")
                if VERBOSE:
                    traceback.print_exc()


# ======================== 项目构建检测 ========================
class BuildSystem:
    @staticmethod
    def detect(root: Path) -> Optional[Dict]:
        if (root / 'CMakeLists.txt').exists():
            return {
                'type': 'cmake',
                'build_cmd': ['cmake', '--build', '.'],
                'run_cmd': None,
                'test_cmd': ['ctest'],
                'deps_file': None
            }
        if (root / 'Makefile').exists() or (root / 'makefile').exists():
            return {
                'type': 'make',
                'build_cmd': ['make'],
                'run_cmd': None,
                'test_cmd': ['make', 'test'],
                'deps_file': None
            }
        if (root / 'Cargo.toml').exists():
            return {
                'type': 'cargo',
                'build_cmd': ['cargo', 'build'],
                'run_cmd': ['cargo', 'run'],
                'test_cmd': ['cargo', 'test'],
                'deps_file': root / 'Cargo.toml'
            }
        if (root / 'package.json').exists():
            try:
                with open(root / 'package.json', 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                scripts = pkg.get('scripts', {})
                build_cmd = ['npm', 'run', 'build'] if 'build' in scripts else None
                run_cmd = ['npm', 'start'] if 'start' in scripts else ['npm', 'run', 'dev'] if 'dev' in scripts else None
                test_cmd = ['npm', 'test'] if 'test' in scripts else None
                return {
                    'type': 'npm',
                    'build_cmd': build_cmd,
                    'run_cmd': run_cmd,
                    'test_cmd': test_cmd,
                    'deps_file': root / 'package.json'
                }
            except Exception:
                pass
        if (root / 'go.mod').exists():
            return {
                'type': 'go',
                'build_cmd': ['go', 'build', './...'],
                'run_cmd': ['go', 'run', '.'],
                'test_cmd': ['go', 'test', './...'],
                'deps_file': root / 'go.mod'
            }
        if (root / 'requirements.txt').exists():
            return {
                'type': 'python',
                'build_cmd': None,
                'run_cmd': None,
                'test_cmd': ['pytest'] if shutil.which('pytest') else None,
                'deps_file': root / 'requirements.txt'
            }
        if (root / 'setup.py').exists() or (root / 'pyproject.toml').exists():
            return {
                'type': 'python',
                'build_cmd': None,
                'run_cmd': None,
                'test_cmd': ['pytest'] if shutil.which('pytest') else None,
                'deps_file': root / 'requirements.txt' if (root / 'requirements.txt').exists() else None
            }
        return None


# ======================== 服务层 ========================
class BuildService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def build(self) -> bool:
        proj = BuildSystem.detect(Path.cwd())
        if not proj:
            Console.error("未检测到支持的项目构建系统 (CMake/Make/Cargo/npm/Go)")
            return False
        if not proj.get('build_cmd'):
            Console.warn(f"项目类型 {proj['type']} 没有定义构建命令")
            return False
        Console.info(f"检测到 {proj['type']} 项目，执行构建: {' '.join(proj['build_cmd'])}")
        ret = safe_run(proj['build_cmd'])
        return ret.returncode == 0


class DependencyService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def check(self) -> bool:
        proj = BuildSystem.detect(Path.cwd())
        if not proj:
            Console.error("未检测到项目，无法检查依赖")
            return False
        deps_file = proj.get('deps_file')
        if not deps_file or not deps_file.exists():
            Console.info("没有找到依赖文件")
            return True
        try:
            content = deps_file.read_text(encoding='utf-8')
            Console.bold(f"依赖文件 {deps_file.name} 内容:")
            print(content)
            return True
        except Exception as e:
            Console.error(f"读取依赖文件失败: {e}")
            return False

    def install(self) -> bool:
        proj = BuildSystem.detect(Path.cwd())
        if not proj:
            Console.error("未检测到项目，无法安装依赖")
            return False
        deps_file = proj.get('deps_file')
        if not deps_file:
            Console.error("项目没有明确的依赖文件")
            return False
        cmd = None
        if proj['type'] == 'python' and deps_file.name == 'requirements.txt':
            cmd = ['pip', 'install', '-r', str(deps_file)]
        elif proj['type'] == 'npm' and deps_file.name == 'package.json':
            cmd = ['npm', 'install']
        elif proj['type'] == 'go' and deps_file.name == 'go.mod':
            cmd = ['go', 'mod', 'download']
        elif proj['type'] == 'cargo' and deps_file.name == 'Cargo.toml':
            cmd = ['cargo', 'fetch']
        else:
            Console.error(f"不支持依赖安装类型: {proj['type']}")
            return False
        Console.info(f"安装依赖: {' '.join(cmd)}")
        ret = safe_run(cmd)
        return ret.returncode == 0


class FormatService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def format(self, target: str) -> bool:
        target_path = Path(target)
        if target_path.is_file():
            return self._fmt_file(target_path)
        elif target_path.is_dir():
            success = True
            for root, dirs, files in os.walk(target_path):
                for f in files:
                    fp = Path(root) / f
                    handler = PluginRegistry.get_handler(fp.suffix)
                    if handler:
                        if not self._fmt_file(fp):
                            success = False
            return success
        else:
            Console.error(f"目标不存在: {target}")
            return False

    def _fmt_file(self, file: Path) -> bool:
        ext = file.suffix.lower()
        cmd = None
        if ext in ('.cpp', '.cxx', '.cc', '.c', '.h', '.hpp'):
            if shutil.which('clang-format'):
                cmd = ['clang-format', '-i', str(file)]
            else:
                Console.warn("clang-format 未安装，无法格式化 C/C++")
                return False
        elif ext == '.py':
            if shutil.which('black'):
                cmd = ['black', str(file)]
            else:
                Console.warn("black 未安装，无法格式化 Python")
                return False
        elif ext in ('.js', '.jsx', '.ts', '.tsx', '.json', '.css', '.html'):
            if shutil.which('prettier'):
                cmd = ['prettier', '--write', str(file)]
            else:
                Console.warn("prettier 未安装，无法格式化 JavaScript/TypeScript 等")
                return False
        elif ext == '.go':
            if shutil.which('gofmt'):
                cmd = ['gofmt', '-w', str(file)]
            else:
                Console.warn("gofmt 未安装，无法格式化 Go")
                return False
        elif ext == '.rs':
            if shutil.which('rustfmt'):
                cmd = ['rustfmt', str(file)]
            else:
                Console.warn("rustfmt 未安装，无法格式化 Rust")
                return False
        else:
            Console.warn(f"不支持格式化文件类型: {ext}")
            return False
        Console.info(f"格式化: {' '.join(cmd)}")
        ret = safe_run(cmd)
        if ret.returncode == 0:
            Console.success(f"格式化完成: {file}")
            return True
        Console.error(f"格式化失败: {file}")
        return False


class SearchService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def grep(self, pattern: str, extra_args: List[str] = None) -> bool:
        if shutil.which('rg'):
            cmd = ['rg', pattern] + (extra_args or [])
        else:
            if sys.platform == 'win32':
                cmd = ['findstr', '/s', '/i', '/n', pattern, '*.*']
            else:
                cmd = ['grep', '-r', '-n', '-E', pattern, '.']
        Console.info(f"搜索: {' '.join(cmd)}")
        ret = safe_run(cmd, check=False)
        if ret.stdout:
            print(ret.stdout)
        if ret.stderr:
            print(ret.stderr, file=sys.stderr)
        if ret.returncode == 0:
            return True
        Console.warn("搜索无结果或出错")
        return False

    def def_find(self, symbol: str) -> bool:
        if shutil.which('ctags'):
            tags_file = Path.cwd() / 'tags'
            if not tags_file.exists():
                Console.info("生成 tags 索引...")
                ret = safe_run(['ctags', '-R', '.'])
                if ret.returncode != 0:
                    Console.warn("ctags 生成索引失败")
                    return False
            try:
                with open(tags_file, 'r', encoding='utf-8') as f:
                    for line in f:
                        if line.startswith('!'):
                            continue
                        parts = line.split('\t')
                        if len(parts) >= 3 and parts[0] == symbol:
                            print(f"{parts[1]}: {parts[2]}")
                            return True
                Console.info(f"未找到符号 '{symbol}'")
                return False
            except Exception as e:
                Console.error(f"查找定义失败: {e}")
                return False
        else:
            patterns = [
                f"^\\s*(def|class|function|void|int|char|float|double)\\s+{symbol}\\b",
                f"^\\s*{symbol}\\s*\\(.*\\)",
                f"^\\s*{symbol}\\s*=",
            ]
            for pat in patterns:
                if shutil.which('rg'):
                    cmd = ['rg', '--type', 'all', '-n', pat, '.']
                else:
                    cmd = ['grep', '-r', '-n', '-E', pat, '.']
                Console.debug(f"查找定义模式: {pat}")
                ret = safe_run(cmd, check=False)
                if ret.stdout:
                    print(ret.stdout)
                    return True
            Console.info(f"未找到符号 '{symbol}'")
            return False

    def search_code(self, keyword: str):
        current_dir = Path.cwd()
        found = False
        for item in current_dir.iterdir():
            if item.is_file():
                if not PluginRegistry.get_handler(item.suffix):
                    continue
                try:
                    with open(item, 'r', encoding='utf-8', errors='ignore') as f:
                        for lineno, line in enumerate(f, 1):
                            if keyword in line:
                                if not found:
                                    Console.bold(f"\n🔍 搜索结果 \"{keyword}\":")
                                found = True
                                print(f"  {item}:{lineno}: " + line.rstrip())
                except Exception:
                    pass
        if not found:
            Console.info(f"未找到包含 \"{keyword}\" 的代码")


class StatsService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def stats(self, by_file: bool = False) -> bool:
        if shutil.which('cloc'):
            cmd = ['cloc', '.']
            if by_file:
                cmd.append('--by-file')
            ret = safe_run(cmd, check=False)
            if ret.stdout:
                print(ret.stdout)
                return True
            Console.error("cloc 执行失败")
            return False
        else:
            Console.warn("cloc 未安装，使用内置简单统计（仅行数）")
            total_lines = 0
            file_stats = []
            for root, dirs, files in os.walk('.'):
                dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'node_modules', 'target'}]
                for f in files:
                    fp = Path(root) / f
                    if not PluginRegistry.get_handler(fp.suffix):
                        continue
                    try:
                        with open(fp, 'r', encoding='utf-8', errors='ignore') as src:
                            lines = src.readlines()
                            total_lines += len(lines)
                            file_stats.append((fp, len(lines)))
                    except Exception:
                        pass
            if by_file:
                Console.bold("\n各文件行数:")
                for fp, cnt in sorted(file_stats, key=lambda x: -x[1]):
                    print(f"  {fp}: {cnt} 行")
            Console.success(f"总行数: {total_lines}")
            return True


class DebugService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def debug(self, file: str, args: List[str] = None) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        ext = path.suffix.lower()
        handler = PluginRegistry.get_handler(ext)
        if not handler:
            Console.error(f"不支持的文件类型: {ext}")
            return False

        if isinstance(handler, (CppHandler, CHandler)):
            ok, err = handler.compile(path)
            if not ok:
                Console.error("编译失败，无法调试")
                return False
            exe = path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("编译产物不存在")
                return False
            debugger = None
            if shutil.which('gdb'):
                debugger = ['gdb', str(exe)]
            elif shutil.which('lldb'):
                debugger = ['lldb', str(exe)]
            else:
                Console.error("未找到调试器 (gdb/lldb)")
                return False
            if debugger:
                Console.info(f"启动调试器: {' '.join(debugger)}")
                try:
                    sp.run(debugger + (args or []))
                    return True
                except Exception as e:
                    Console.error(f"调试器执行失败: {e}")
                    return False
        elif isinstance(handler, PythonHandler):
            interpreter = 'py' if shutil.which('py') else 'python'
            cmd = [interpreter, '-m', 'pdb', str(path)] + (args or [])
            Console.info(f"启动 Python 调试器: {' '.join(cmd)}")
            try:
                sp.run(cmd)
                return True
            except Exception as e:
                Console.error(f"调试器执行失败: {e}")
                return False
        else:
            Console.error(f"语言 {handler.name} 暂不支持调试")
            return False


class GitService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.ai_service = AIService(config)

    def git(self, args: List[str]) -> bool:
        safe_commands = {'status', 'add', 'commit', 'push', 'pull', 'log', 'diff', 'branch', 'checkout'}
        if args:
            cmd = args[0]
            if cmd not in safe_commands:
                Console.error(f"不安全的 Git 命令: {cmd}，仅允许: {', '.join(safe_commands)}")
                return False
        try:
            res = sp.run(['git'] + args, capture_output=True, text=True)
            if res.stdout:
                print(res.stdout.rstrip())
            if res.stderr and 'warning' not in res.stderr.lower():
                if res.returncode != 0:
                    Console.error(res.stderr.strip())
                    return False
                else:
                    print(res.stderr.rstrip())
            return True
        except FileNotFoundError:
            Console.error("未找到 Git，请安装并加入 PATH")
            return False

    def commit(self) -> bool:
        diff_cmd = ['git', 'diff', '--staged']
        ret = safe_run(diff_cmd, check=False)
        if ret.returncode != 0:
            Console.error("Git 命令执行失败")
            return False
        diff_out = ret.stdout
        if not diff_out.strip():
            Console.warn("没有暂存的更改，请先 git add")
            return False

        try:
            prompt = f"Generate a concise and informative git commit message for the following changes:\n\n{diff_out[:2000]}"
            message = self.ai_service.generate(prompt, temperature=0.7, max_tokens=150, context_aware=True)
            print(Console._c(f"AI 生成的消息:\n{message}", Color.GREEN))
            ans = safe_input("是否使用此消息提交? (y/N): ")
            if ans.lower() == 'y':
                ret = safe_run(['git', 'commit', '-m', message])
                if ret.returncode == 0:
                    Console.success("提交成功")
                    return True
                Console.error("提交失败")
                return False
            Console.info("取消提交")
            return True
        except Exception as e:
            Console.warn(f"AI 生成失败: {e}，回退到手动输入")

        files_changed = len(diff_out.splitlines())
        Console.info(f"检测到 {files_changed} 个文件更改")
        message = safe_input("请输入提交消息 (直接回车取消): ", default='')
        if message.strip():
            ret = safe_run(['git', 'commit', '-m', message])
            if ret.returncode == 0:
                Console.success("提交成功")
                return True
            Console.error("提交失败")
            return False
        Console.info("取消提交")
        return True

    def get_commit_time(self, filepath: str) -> Optional[datetime]:
        try:
            cmd = ['git', 'log', '-1', '--format=%ci', '--', filepath]
            res = sp.run(cmd, capture_output=True, text=True, timeout=5)
            if res.returncode == 0 and res.stdout.strip():
                dt_str = res.stdout.strip().split()[0] + ' ' + res.stdout.strip().split()[1]
                return datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S')
        except Exception:
            pass
        return None


class TaskService:
    def __init__(self, config: ConfigManager, code_manager):
        self.config = config
        self.code_manager = code_manager

    def task(self, name: str, args: List[str]) -> bool:
        proj_config = Path.cwd() / '.codemanager'
        if not proj_config.exists():
            Console.error(f"当前目录没有 .codemanager 配置文件")
            return False
        tasks = {}
        in_tasks = False
        try:
            with open(proj_config, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('[') and line.endswith(']'):
                        in_tasks = (line.lower() == '[tasks]')
                        continue
                    if in_tasks and '=' in line and not line.startswith(';'):
                        k, v = line.split('=', 1)
                        tasks[k.strip()] = v.strip()
        except Exception as e:
            Console.error(f"读取配置文件失败: {e}")
            return False
        if name not in tasks:
            Console.error(f"任务 '{name}' 未在 [tasks] 中定义")
            return False
        cmd_str = tasks[name]
        if cmd_str.startswith('ck:'):
            sub_cmd = cmd_str[3:].strip()
            return self._run_ck_command(sub_cmd, args)
        else:
            if '{args}' in cmd_str:
                cmd_str = cmd_str.replace('{args}', ' '.join(args))
            else:
                if args:
                    cmd_str += ' ' + ' '.join(args)
            Console.warn("执行自定义 shell 命令，请确保命令安全")
            try:
                cmd_parts = shlex.split(cmd_str)
                Console.info(f"执行任务: {' '.join(cmd_parts)}")
                ret = safe_run(cmd_parts, cwd=Path.cwd())
                return ret.returncode == 0
            except Exception as e:
                Console.error(f"任务执行失败: {e}")
                return False

    def _run_ck_command(self, cmd_str: str, args: List[str]) -> bool:
        if self.code_manager is None:
            Console.error("CodeManager 未初始化，无法执行 ck 命令")
            return False
        cmd_parts = cmd_str.split() + args if args else cmd_str.split()
        parser = create_parser()
        try:
            parsed = parser.parse_args(cmd_parts)
            if hasattr(parsed, 'command'):
                return self.code_manager.dispatch_command(parsed)
            else:
                Console.error(f"无效的 ck 子命令: {cmd_str}")
                return False
        except SystemExit:
            return False
        except Exception as e:
            Console.error(f"执行 ck 子命令失败: {e}")
            return False


class EnvService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.fingerprint_file = Path.cwd() / config.get('env_fingerprint_file', '.codekit-env.json')

    def load_env(self):
        env_file = self.config.get('env_file', '.env')
        current_dir = Path.cwd()
        for parent in [current_dir] + list(current_dir.parents):
            env_path = parent / env_file
            if env_path.exists():
                try:
                    with open(env_path, 'r', encoding='utf-8') as f:
                        for line in f:
                            line = line.strip()
                            if line and not line.startswith('#'):
                                if '=' in line:
                                    k, v = line.split('=', 1)
                                    v = self._expand_env(v)
                                    os.environ[k.strip()] = v.strip()
                    Console.debug(f"加载环境变量: {env_path}")
                    return
                except Exception as e:
                    Console.warn(f"加载 .env 文件失败: {e}")
        Console.debug("未找到 .env 文件")

    def _expand_env(self, value: str) -> str:
        pattern = re.compile(r'\$\{([^}]+)\}')

        def repl(match):
            var = match.group(1)
            return os.environ.get(var, '')
        return pattern.sub(repl, value)

    def list_env(self) -> bool:
        Console.bold("当前环境变量 (部分):")
        for k, v in sorted(os.environ.items()):
            if k.startswith(('PATH', 'PYTHON', 'NODE', 'GOPATH', 'JAVA_HOME')):
                continue
            print(f"  {k}={v}")
        return True

    def set_env(self, key: str, value: str) -> bool:
        env_file = Path.cwd() / (self.config.get('env_file', '.env'))
        lines = []
        found = False
        if env_file.exists():
            with open(env_file, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip().startswith(key + '='):
                        lines.append(f"{key}={value}\n")
                        found = True
                    else:
                        lines.append(line)
        if not found:
            lines.append(f"{key}={value}\n")
        with open(env_file, 'w', encoding='utf-8') as f:
            f.writelines(lines)
        Console.success(f"已设置环境变量 {key}={value} 并保存到 {env_file}")
        return True

    def save_fingerprint(self) -> bool:
        fingerprint = {
            'timestamp': datetime.now().isoformat(),
            'project': str(Path.cwd().resolve()),
            'python': {
                'version': sys.version,
                'executable': sys.executable
            },
            'compilers': {},
            'tools': {},
            'dependencies': {}
        }
        for cmd in ['gcc', 'g++', 'clang', 'clang++', 'rustc', 'go', 'javac', 'dotnet', 'swiftc', 'dart', 'ruby']:
            path = shutil.which(cmd)
            if path:
                try:
                    proc = sp.run([cmd, '--version'], capture_output=True, text=True, timeout=5)
                    version_line = proc.stdout.splitlines()[0] if proc.stdout else ''
                    fingerprint['compilers'][cmd] = {
                        'path': path,
                        'version': version_line.strip()
                    }
                except Exception:
                    pass
        for tool in ['make', 'cmake', 'cargo', 'npm', 'pip']:
            path = shutil.which(tool)
            if path:
                fingerprint['tools'][tool] = {'path': path}
        for dep_file in ['requirements.txt', 'package.json', 'go.mod', 'Cargo.toml', 'setup.py', 'pyproject.toml']:
            fpath = Path.cwd() / dep_file
            if fpath.exists():
                try:
                    with open(fpath, 'rb') as f:
                        hash_val = hashlib.sha256(f.read()).hexdigest()
                    fingerprint['dependencies'][dep_file] = hash_val
                except Exception:
                    pass
        env_vars = {}
        for k in ['PATH', 'PYTHONPATH', 'GOPATH', 'JAVA_HOME', 'NODE_PATH']:
            if k in os.environ:
                env_vars[k] = os.environ[k]
        fingerprint['environment_vars'] = env_vars

        try:
            with open(self.fingerprint_file, 'w', encoding='utf-8') as f:
                json.dump(fingerprint, f, indent=2, ensure_ascii=False)
            Console.success(f"环境指纹已保存到 {self.fingerprint_file}")
            return True
        except Exception as e:
            Console.error(f"保存环境指纹失败: {e}")
            return False

    def restore_fingerprint(self) -> bool:
        if not self.fingerprint_file.exists():
            Console.error(f"未找到环境指纹文件: {self.fingerprint_file}")
            return False
        try:
            with open(self.fingerprint_file, 'r', encoding='utf-8') as f:
                required = json.load(f)
        except Exception as e:
            Console.error(f"读取环境指纹失败: {e}")
            return False

        Console.bold("环境指纹恢复检查:")
        issues = 0
        suggestions = []

        req_py = required.get('python', {})
        if req_py:
            cur_ver = sys.version
            req_ver = req_py.get('version', '')
            if req_ver and req_ver not in cur_ver:
                Console.warn(f"Python 版本不匹配：要求 {req_ver}，当前 {cur_ver}")
                suggestions.append(f"建议安装 Python {req_ver}，可使用 pyenv 或系统包管理器")
                issues += 1

        req_compilers = required.get('compilers', {})
        for name, info in req_compilers.items():
            path = shutil.which(name)
            if not path:
                Console.warn(f"编译器 {name} 未找到（要求版本: {info.get('version', '未知')}）")
                if name in ['gcc', 'g++']:
                    if sys.platform == 'darwin':
                        suggestions.append(f"brew install {name}")
                    else:
                        suggestions.append(f"sudo apt install {name} 或 yum install {name}")
                elif name == 'clang':
                    suggestions.append("sudo apt install clang 或 brew install llvm")
                elif name == 'rustc':
                    suggestions.append("curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
                elif name == 'go':
                    suggestions.append("从 https://golang.org/dl/ 下载安装")
                elif name == 'javac':
                    suggestions.append("安装 OpenJDK，例如 sudo apt install openjdk-11-jdk")
                elif name == 'dotnet':
                    suggestions.append("从 https://dotnet.microsoft.com/download 安装")
                elif name == 'swiftc':
                    suggestions.append("从 https://swift.org/download/ 安装")
                elif name == 'dart':
                    suggestions.append("从 https://dart.dev/get-dart 安装")
                elif name == 'ruby':
                    suggestions.append("sudo apt install ruby 或 brew install ruby")
                issues += 1
            else:
                req_ver = info.get('version', '')
                if req_ver:
                    try:
                        proc = sp.run([name, '--version'], capture_output=True, text=True, timeout=5)
                        cur_ver = proc.stdout.splitlines()[0] if proc.stdout else ''
                        if req_ver not in cur_ver:
                            Console.warn(f"{name} 版本可能不匹配：要求 {req_ver}，当前 {cur_ver}")
                            suggestions.append(f"建议升级 {name} 到 {req_ver}")
                            issues += 1
                    except Exception:
                        pass

        req_tools = required.get('tools', {})
        for tool in req_tools.keys():
            if not shutil.which(tool):
                Console.warn(f"工具 {tool} 未找到")
                if tool == 'make':
                    suggestions.append("sudo apt install make 或 yum install make")
                elif tool == 'cmake':
                    suggestions.append("sudo apt install cmake 或 brew install cmake")
                elif tool == 'cargo':
                    suggestions.append("安装 Rust 时附带 cargo")
                elif tool == 'npm':
                    suggestions.append("安装 Node.js 时附带 npm")
                elif tool == 'pip':
                    suggestions.append("确保 Python 的 pip 已安装")
                issues += 1

        req_deps = required.get('dependencies', {})
        for dep_file, hash_val in req_deps.items():
            fpath = Path.cwd() / dep_file
            if not fpath.exists():
                Console.warn(f"依赖文件 {dep_file} 缺失")
                issues += 1
            else:
                try:
                    with open(fpath, 'rb') as f:
                        cur_hash = hashlib.sha256(f.read()).hexdigest()
                    if cur_hash != hash_val:
                        Console.warn(f"{dep_file} 内容发生变化，可能依赖版本不一致")
                        suggestions.append(f"请检查 {dep_file} 与指纹记录是否一致")
                        issues += 1
                except Exception:
                    pass

        if issues == 0:
            Console.success("环境检查通过，所有组件匹配指纹记录")
        else:
            Console.warn(f"发现 {issues} 个问题，建议采取以下措施:")
            for s in set(suggestions):
                Console.info(f"  - {s}")
            ans = safe_input("是否尝试自动安装/修复？(y/N): ")
            if ans.lower() == 'y':
                self._auto_fix_suggestions(suggestions)

        return issues == 0

    def _auto_fix_suggestions(self, suggestions: List[str]):
        install_cmds = []
        for s in suggestions:
            if s.startswith('sudo apt install'):
                install_cmds.append(s)
            elif s.startswith('brew install'):
                install_cmds.append(s)
            elif s.startswith('yum install'):
                install_cmds.append(s)
            elif s.startswith('curl') and 'rustup' in s:
                install_cmds.append(s)
        if not install_cmds:
            Console.info("没有可自动执行的安装命令，请手动处理")
            return
        Console.bold("将执行以下命令:")
        for cmd in install_cmds:
            print(f"  {cmd}")
        confirm = safe_input("确认执行? (y/N): ")
        if confirm.lower() == 'y':
            for cmd in install_cmds:
                Console.info(f"执行: {cmd}")
                try:
                    sp.run(cmd, shell=True, check=True, timeout=300)
                    Console.success(f"执行成功: {cmd}")
                except Exception as e:
                    Console.error(f"执行失败: {e}")
        else:
            Console.info("取消自动修复")

    def check_gpp(self) -> bool:
        Console.info("正在检测系统中的 g++ 版本...")
        gpp_candidates = []
        base_names = ['g++-14', 'g++-13', 'g++-12', 'g++-11', 'g++']
        for name in base_names:
            path = shutil.which(name)
            if path:
                m = re.search(r'g\+\+-(\d+)', name)
                if m:
                    ver = int(m.group(1))
                elif name == 'g++':
                    try:
                        proc = sp.run([name, '--version'], capture_output=True, text=True, timeout=2)
                        out = proc.stdout or ''
                        m2 = re.search(r'(\d+)\.(\d+)\.(\d+)', out)
                        if m2:
                            ver = int(m2.group(1))
                        else:
                            ver = 0
                    except Exception:
                        ver = 0
                else:
                    ver = 0
                if ver > 0:
                    gpp_candidates.append((ver, path, name))

        if not gpp_candidates:
            Console.error("未找到任何 g++ 编译器")
            return False

        gpp_candidates.sort(key=lambda x: x[0], reverse=True)
        best_ver, best_path, best_name = gpp_candidates[0]

        self.config._raw['oi']['default_gpp'] = best_name
        self.config.save()
        Console.success(f"已选择最新 g++ 版本: {best_name} (路径: {best_path})")
        Console.info(f"配置已更新: oi.default_gpp = {best_name}")
        return True


class LintService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def lint(self, target: Optional[str] = None) -> Tuple[bool, List[str]]:
        proj = BuildSystem.detect(Path.cwd())
        lang = proj['type'] if proj else None
        if lang is None:
            extensions = {'.py': 'python', '.js': 'javascript', '.ts': 'typescript',
                          '.cpp': 'cpp', '.c': 'c', '.go': 'go', '.rs': 'rust'}
            for ext in extensions:
                if list(Path.cwd().glob(f'*{ext}')):
                    lang = extensions[ext]
                    break
        if lang is None:
            Console.error("无法检测项目语言，请指定")
            return False, []

        linter_cmd = None
        if lang == 'python':
            if shutil.which('pylint'):
                linter_cmd = ['pylint', '.'] if not target else ['pylint', target]
            elif shutil.which('flake8'):
                linter_cmd = ['flake8', '.'] if not target else ['flake8', target]
            else:
                Console.warn("未找到 pylint 或 flake8，建议安装: pip install pylint")
                return False, []
        elif lang in ('javascript', 'typescript'):
            if shutil.which('eslint'):
                linter_cmd = ['eslint', '.'] if not target else ['eslint', target]
            else:
                Console.warn("未找到 eslint，建议安装: npm install -g eslint")
                return False, []
        elif lang in ('cpp', 'c'):
            if shutil.which('clang-tidy'):
                linter_cmd = ['clang-tidy', '--checks=*', '.'] if not target else ['clang-tidy', '--checks=*', target]
            else:
                Console.warn("未找到 clang-tidy，建议安装: apt install clang-tidy 或 brew install llvm")
                return False, []
        elif lang == 'go':
            if shutil.which('staticcheck'):
                linter_cmd = ['staticcheck', './...'] if not target else ['staticcheck', target]
            elif shutil.which('golint'):
                linter_cmd = ['golint', './...'] if not target else ['golint', target]
            else:
                Console.warn("未找到 staticcheck 或 golint，建议安装: go install honnef.co/go/tools/cmd/staticcheck@latest")
                return False, []
        elif lang == 'rust':
            if shutil.which('cargo'):
                linter_cmd = ['cargo', 'clippy'] if not target else ['cargo', 'clippy', '--', target]
            else:
                Console.warn("未找到 cargo，请安装 Rust")
                return False, []
        else:
            Console.error(f"不支持的语言: {lang}")
            return False, []

        Console.info(f"运行代码检查: {' '.join(linter_cmd)}")
        ret = safe_run(linter_cmd, check=False)
        if ret.stdout:
            print(ret.stdout)
        if ret.stderr:
            print(ret.stderr, file=sys.stderr)
        errors = ret.stderr.splitlines() if ret.stderr else []
        if ret.returncode == 0:
            Console.success("代码检查通过")
            return True, []
        Console.error("代码检查发现问题")
        return False, errors


class ScaffoldService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def init_project(self, template: str) -> bool:
        tpl_dir = Path(self.config.get('template_dir', str(GLOBAL_CONFIG_DIR / 'templates')))
        template_path = tpl_dir / template
        if not template_path.exists():
            Console.error(f"模板 '{template}' 不存在于 {tpl_dir}")
            return False
        target = Path.cwd()
        conflicts = []
        for src_file in template_path.rglob('*'):
            rel = src_file.relative_to(template_path)
            dst = target / rel
            if dst.exists():
                conflicts.append(dst)
        if conflicts:
            Console.warn(f"以下文件已存在，将跳过:")
            for c in conflicts:
                print(f"  {c}")
            ans = safe_input("是否继续? (y/N): ")
            if ans.lower() != 'y':
                Console.info("取消初始化")
                return False
        project_name = target.name

        def replace_placeholders(content: str) -> str:
            content = content.replace('{{PROJECT_NAME}}', project_name)
            content = content.replace('{{PROJECT_NAME_LOWER}}', project_name.lower())
            content = content.replace('{{PROJECT_NAME_UPPER}}', project_name.upper())
            content = content.replace('{{YEAR}}', str(datetime.now().year))
            return content

        for src_file in template_path.rglob('*'):
            rel = src_file.relative_to(template_path)
            dst = target / rel
            if dst.exists():
                continue
            if src_file.is_dir():
                dst.mkdir(parents=True, exist_ok=True)
            else:
                try:
                    content = src_file.read_text(encoding='utf-8')
                    content = replace_placeholders(content)
                    dst.write_text(content, encoding='utf-8')
                except Exception as e:
                    Console.warn(f"复制文件 {src_file} 失败: {e}")
        Console.success(f"项目初始化完成，模板: {template}")
        return True


class ChecksumService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def checksum(self, file: str, algo: str = 'sha256') -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        hash_func = hashlib.new(algo)
        try:
            with open(path, 'rb') as f:
                for chunk in iter(lambda: f.read(8192), b''):
                    hash_func.update(chunk)
            digest = hash_func.hexdigest()
            print(f"{algo.upper()} ({path}): {digest}")
            return True
        except Exception as e:
            Console.error(f"计算哈希失败: {e}")
            return False

    def freeze(self) -> bool:
        lock_data = {}
        for dep_file in ['requirements.txt', 'package.json', 'go.mod', 'Cargo.toml']:
            path = Path.cwd() / dep_file
            if path.exists():
                try:
                    with open(path, 'rb') as f:
                        hash_val = hashlib.sha256(f.read()).hexdigest()
                    lock_data[dep_file] = hash_val
                except Exception as e:
                    Console.warn(f"读取 {dep_file} 失败: {e}")
        if not lock_data:
            Console.warn("未找到依赖文件")
            return True
        lock_file = Path.cwd() / '.codekit-lock.json'
        try:
            with open(lock_file, 'w', encoding='utf-8') as f:
                json.dump(lock_data, f, indent=2)
            Console.success(f"锁文件已生成: {lock_file}")
            return True
        except Exception as e:
            Console.error(f"写入锁文件失败: {e}")
            return False


class DoctorService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.meta_file = Path.cwd() / config.get('project_meta_file', '.codekit-meta.json')

    def diagnose(self) -> bool:
        Console.bold("🔍 CodeKit 环境诊断")
        Console.info(f"项目目录: {Path.cwd()}")
        issues = 0
        suggestions = []

        tools = {
            'git': '版本控制',
            'make': '构建工具',
            'cmake': '构建工具',
            'gcc': 'C 编译器',
            'g++': 'C++ 编译器',
            'python': 'Python 解释器',
            'node': 'Node.js',
            'npm': 'Node.js 包管理器',
            'go': 'Go 编译器',
            'rustc': 'Rust 编译器',
            'cargo': 'Rust 包管理器',
            'javac': 'Java 编译器',
            'java': 'Java 运行时',
            'dotnet': '.NET SDK',
            'swiftc': 'Swift 编译器',
            'dart': 'Dart SDK',
            'ruby': 'Ruby 解释器',
        }
        missing = []
        for tool, desc in tools.items():
            if shutil.which(tool):
                Console.debug(f"{tool} 已安装")
            else:
                missing.append((tool, desc))
        if missing:
            Console.warn(f"缺失 {len(missing)} 个工具:")
            for tool, desc in missing:
                print(f"  - {tool} ({desc})")
                if tool == 'git':
                    suggestions.append("sudo apt install git 或 brew install git")
                elif tool in ('gcc', 'g++'):
                    suggestions.append("sudo apt install gcc g++ 或 brew install gcc")
                elif tool == 'python':
                    suggestions.append("从 python.org 下载或使用 pyenv")
                elif tool == 'node':
                    suggestions.append("从 nodejs.org 下载或使用 nvm")
                elif tool == 'npm':
                    suggestions.append("Node.js 自带 npm")
                elif tool == 'go':
                    suggestions.append("从 golang.org 下载")
                elif tool in ('rustc', 'cargo'):
                    suggestions.append("curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh")
                elif tool == 'javac':
                    suggestions.append("sudo apt install openjdk-11-jdk 或 yum install java-11-openjdk-devel")
                elif tool == 'java':
                    suggestions.append("同上")
                elif tool == 'dotnet':
                    suggestions.append("从 dotnet.microsoft.com 下载")
                elif tool == 'swiftc':
                    suggestions.append("从 swift.org 下载或安装 Xcode")
                elif tool == 'dart':
                    suggestions.append("从 dart.dev 下载")
                elif tool == 'ruby':
                    suggestions.append("sudo apt install ruby 或 brew install ruby")
                issues += 1

        if self.meta_file.exists():
            try:
                with open(self.meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
                last_success = meta.get('last_successful_build')
                if last_success:
                    Console.info(f"上次成功构建时间: {last_success.get('timestamp', '未知')}")
                    compiler = last_success.get('compiler', '未知')
                    version = last_success.get('version', '')
                    if compiler and version:
                        Console.info(f"上次使用的编译器: {compiler} {version}")
                        if shutil.which(compiler):
                            Console.success(f"{compiler} 当前可用")
                        else:
                            Console.warn(f"{compiler} 当前不可用，建议安装对应版本")
                            suggestions.append(f"请安装 {compiler} (版本 {version})")
                            issues += 1
            except Exception as e:
                Console.debug(f"读取项目元数据失败: {e}")

        env_file = Path.cwd() / self.config.get('env_fingerprint_file', '.codekit-env.json')
        if env_file.exists():
            Console.info("检测到环境指纹文件，可运行 'ck env restore' 进行一致性检查")

        for var in ['PATH', 'PYTHONPATH', 'GOPATH', 'JAVA_HOME']:
            if var in os.environ:
                Console.debug(f"{var} = {os.environ[var]}")
            else:
                if var in ['JAVA_HOME', 'GOPATH']:
                    Console.warn(f"{var} 未设置，可能影响相关工具")

        if issues == 0:
            Console.success("环境健康，未发现问题")
        else:
            Console.warn(f"发现 {issues} 个问题，建议:")
            for s in set(suggestions):
                Console.info(f"  - {s}")
            ans = safe_input("是否尝试自动修复部分问题? (y/N): ")
            if ans.lower() == 'y':
                self._auto_fix(suggestions)
        return issues == 0

    def _auto_fix(self, suggestions: List[str]):
        install_cmds = []
        for s in suggestions:
            if s.startswith('sudo apt install'):
                install_cmds.append(s)
            elif s.startswith('brew install'):
                install_cmds.append(s)
            elif s.startswith('yum install'):
                install_cmds.append(s)
            elif s.startswith('curl') and 'rustup' in s:
                install_cmds.append(s)
        if not install_cmds:
            Console.info("没有可自动执行的修复命令，请手动处理")
            return
        Console.bold("将执行以下命令:")
        for cmd in install_cmds:
            print(f"  {cmd}")
        confirm = safe_input("确认执行? (y/N): ")
        if confirm.lower() == 'y':
            for cmd in install_cmds:
                Console.info(f"执行: {cmd}")
                try:
                    sp.run(cmd, shell=True, check=True, timeout=300)
                    Console.success(f"执行成功: {cmd}")
                except Exception as e:
                    Console.error(f"执行失败: {e}")
        else:
            Console.info("取消自动修复")

    def record_successful_build(self, compiler: str, version: str):
        try:
            meta = {}
            if self.meta_file.exists():
                with open(self.meta_file, 'r', encoding='utf-8') as f:
                    meta = json.load(f)
            meta['last_successful_build'] = {
                'timestamp': datetime.now().isoformat(),
                'compiler': compiler,
                'version': version
            }
            with open(self.meta_file, 'w', encoding='utf-8') as f:
                json.dump(meta, f, indent=2)
        except Exception as e:
            Console.debug(f"记录构建信息失败: {e}")

    def hard(self, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行环境压力测试")
            return True

        Console.bold("\n🔥 运行极限环境压力测试 (hard mode) ...")
        report = []
        report.append("=" * 60)
        report.append(f"OI 适配报告 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        report.append("=" * 60)

        stack_limit = "未知"
        if sys.platform != 'win32' and resource is not None:
            try:
                ret = sp.run(['sh', '-c', 'ulimit -s'], capture_output=True, text=True, timeout=5)
                if ret.returncode == 0 and ret.stdout.strip():
                    stack_limit = ret.stdout.strip() + " KB"
                else:
                    try:
                        soft, hard = resource.getrlimit(resource.RLIMIT_STACK)
                        stack_limit = f"{soft // 1024} KB (软限制), {hard // 1024} KB (硬限制)"
                    except Exception:
                        stack_limit = "无法获取"
            except Exception:
                stack_limit = "无法获取"
        else:
            stack_limit = "Windows 暂不支持获取栈限制" if sys.platform == 'win32' else "resource 模块不可用"
        report.append(f"栈空间上限: {stack_limit}")

        recurse_test_code = r'''
#include <stdio.h>
void rec(int n) { if (n == 0) return; rec(n-1); }
int main() {
    int depth = 0;
    for (int i = 1; i <= 1000000; i <<= 1) {
        rec(i);
        depth = i;
    }
    printf("%d", depth);
    return 0;
}
'''

        def compile_and_run(src_code, timeout=5):
            tf_path = None
            exe_path = None
            try:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as tf:
                    tf.write(src_code)
                    tf_path = tf.name
                exe_path = tf_path + EXE_SUFFIX
                ret = safe_run(['gcc', tf_path, '-o', exe_path], timeout=10)
                if ret.returncode != 0:
                    return None
                ret2 = safe_run([exe_path], timeout=timeout, check=False)
                if ret2.returncode == 0:
                    return ret2.stdout.strip()
                else:
                    return None
            except Exception:
                return None
            finally:
                if tf_path:
                    try:
                        os.unlink(tf_path)
                    except Exception:
                        pass
                if exe_path:
                    try:
                        if os.path.exists(exe_path):
                            os.unlink(exe_path)
                    except Exception:
                        pass

        rec_depth = compile_and_run(recurse_test_code)
        if rec_depth is not None:
            report.append(f"最大安全递归深度: {rec_depth} (约)")

        o2_test_code = r'''
#include <stdio.h>
#include <time.h>
int main() {
    clock_t start = clock();
    volatile int x = 0;
    for (int i = 0; i < 100000000; i++) x += i;
    clock_t end = clock();
    printf("%.3f", (double)(end - start) / CLOCKS_PER_SEC);
    return 0;
}
'''
        tf_path = None
        exe_no_o2 = None
        exe_o2 = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as tf:
                tf.write(o2_test_code)
                tf_path = tf.name
            exe_no_o2 = tf_path + '_noO2' + EXE_SUFFIX
            exe_o2 = tf_path + '_O2' + EXE_SUFFIX
            ret_no = safe_run(['gcc', tf_path, '-o', exe_no_o2], timeout=10)
            ret_o2 = safe_run(['gcc', tf_path, '-O2', '-o', exe_o2], timeout=10)
            if ret_no.returncode == 0 and ret_o2.returncode == 0:
                run_no = safe_run([exe_no_o2], timeout=10, check=False)
                run_o2 = safe_run([exe_o2], timeout=10, check=False)
                if run_no.returncode == 0 and run_o2.returncode == 0:
                    time_no = float(run_no.stdout.strip())
                    time_o2 = float(run_o2.stdout.strip())
                    speedup = time_no / time_o2 if time_o2 > 0 else 0
                    report.append(f"O2 优化加速比: {speedup:.2f}x (无O2: {time_no:.3f}s, O2: {time_o2:.3f}s)")
                else:
                    report.append("O2 测试运行失败")
            else:
                report.append("O2 测试编译失败")
        except Exception as e:
            report.append(f"O2 测试异常: {e}")
        finally:
            for f in [tf_path, exe_no_o2, exe_o2]:
                if f:
                    try:
                        os.unlink(f)
                    except Exception:
                        pass

        malloc_test_code = r'''
#include <stdio.h>
#include <stdlib.h>
#include <time.h>
int main() {
    clock_t start = clock();
    const int N = 1000000;
    for (int i = 0; i < N; i++) {
        int *p = (int*)malloc(sizeof(int));
        if (p) free(p);
    }
    clock_t end = clock();
    printf("%.3f", (double)(end - start) / CLOCKS_PER_SEC);
    return 0;
}
'''
        tf_path = None
        exe_malloc = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.c', delete=False) as tf:
                tf.write(malloc_test_code)
                tf_path = tf.name
            exe_malloc = tf_path + '_malloc' + EXE_SUFFIX
            ret_m = safe_run(['gcc', tf_path, '-o', exe_malloc], timeout=10)
            if ret_m.returncode == 0:
                run_m = safe_run([exe_malloc], timeout=10, check=False)
                if run_m.returncode == 0:
                    report.append(f"100万次 malloc/free 耗时: {run_m.stdout.strip()}s")
                else:
                    report.append("内存分配测试运行失败")
            else:
                report.append("内存分配测试编译失败")
        except Exception as e:
            report.append(f"内存分配测试异常: {e}")
        finally:
            for f in [tf_path, exe_malloc]:
                if f:
                    try:
                        os.unlink(f)
                    except Exception:
                        pass

        report.append(f"临时目录: {tempfile.gettempdir()}")
        report.append(f"Python 版本: {sys.version}")
        report.append(f"平台: {platform.platform()}")

        try:
            usage = shutil.disk_usage(Path.cwd())
            free_gb = usage.free / (1024 ** 3)
            report.append(f"当前磁盘剩余空间: {free_gb:.2f} GB")
        except Exception:
            pass

        for line in report:
            print(line)
        report_file = Path.cwd() / '.codekit-hard-report.txt'
        report_file.write_text('\n'.join(report), encoding='utf-8')
        Console.success(f"报告已保存到 {report_file}")
        return True


# ======================== 统一失败库 (FailureLibrary) ========================
class FailureLibrary:
    """统一管理各类失败：编译错误、WA 反例、RE 现场"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.root = Path.cwd() / '.codekit-failures'
        self.index_file = self.root / 'index.json'
        self.compile_dir = self.root / 'compile'
        self.wa_dir = self.root / 'wa'
        self.re_dir = self.root / 're'
        self._ensure_dirs()
        self._index = self._load_index()

    def _ensure_dirs(self):
        for d in [self.root, self.compile_dir, self.wa_dir, self.re_dir]:
            d.mkdir(parents=True, exist_ok=True)

    def _load_index(self) -> Dict:
        if self.index_file.exists():
            try:
                data = json.loads(self.index_file.read_text(encoding='utf-8'))
                if isinstance(data, dict) and 'entries' in data:
                    return data
            except Exception:
                pass
        return {'entries': []}

    def _save_index(self):
        try:
            self.index_file.write_text(
                json.dumps(self._index, indent=2, ensure_ascii=False),
                encoding='utf-8'
            )
        except Exception as e:
            Console.warn(f"保存失败索引出错: {e}")

    def _gen_id(self, prefix: str) -> str:
        ts = datetime.now().strftime('%Y%m%d_%H%M%S_%f')[:-3]
        return f"{prefix}_{ts}"

    def _register_entry(self, entry: Dict):
        self._index.setdefault('entries', []).append(entry)
        self._save_index()

    def add_compile_failure(self, source_file: Path, error_text: str,
                            ai_explanation: Optional[str] = None) -> str:
        fid = self._gen_id('compile')
        fdir = self.compile_dir / fid
        fdir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source_file, fdir / source_file.name)
        except Exception:
            pass
        (fdir / 'error.err').write_text(error_text or '', encoding='utf-8')
        if ai_explanation:
            (fdir / 'ai.txt').write_text(ai_explanation, encoding='utf-8')

        summary = '编译错误'
        for line in (error_text or '').splitlines():
            line = line.strip()
            if line:
                summary = line[:200]
                break

        try:
            src_resolved = str(source_file.resolve())
        except Exception:
            src_resolved = str(source_file)

        entry = {
            'id': fid,
            'type': 'compile',
            'timestamp': datetime.now().isoformat(),
            'source_file': src_resolved,
            'source_name': source_file.name,
            'path': str(fdir.relative_to(self.root)),
            'summary': summary,
            'has_ai': ai_explanation is not None,
        }
        self._register_entry(entry)
        return fid

    def add_wa_failure(self, source_file: Path, input_data: str,
                       main_out: str, brute_out: str,
                       error: str = '', source_type: str = 'stress') -> str:
        fid = self._gen_id('wa')
        fdir = self.wa_dir / fid
        fdir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source_file, fdir / source_file.name)
        except Exception:
            pass
        (fdir / 'input.txt').write_text(input_data or '', encoding='utf-8')
        (fdir / 'main_out.txt').write_text(main_out or '', encoding='utf-8')
        (fdir / 'brute_out.txt').write_text(brute_out or '', encoding='utf-8')
        meta = {
            'id': fid,
            'type': 'wa',
            'source_type': source_type,
            'source_file': str(source_file),
            'error': error,
            'timestamp': datetime.now().isoformat(),
        }
        (fdir / 'meta.json').write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        entry = {
            'id': fid,
            'type': 'wa',
            'timestamp': datetime.now().isoformat(),
            'source_file': str(source_file),
            'source_name': source_file.name,
            'path': str(fdir.relative_to(self.root)),
            'summary': error or 'WA 反例',
            'source_type': source_type,
        }
        self._register_entry(entry)
        return fid

    def add_re_failure(self, source_file: Path, input_data: str, stderr: str,
                       returncode: int = 0, sanitizer: bool = False,
                       source_type: str = 'stress') -> str:
        fid = self._gen_id('re')
        fdir = self.re_dir / fid
        fdir.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copy2(source_file, fdir / source_file.name)
        except Exception:
            pass
        (fdir / 'input.txt').write_text(input_data or '', encoding='utf-8')
        (fdir / 'stderr.txt').write_text(stderr or '', encoding='utf-8')
        meta = {
            'id': fid,
            'type': 're',
            'source_type': source_type,
            'source_file': str(source_file),
            'returncode': returncode,
            'sanitizer': sanitizer,
            'timestamp': datetime.now().isoformat(),
        }
        (fdir / 'meta.json').write_text(
            json.dumps(meta, indent=2, ensure_ascii=False), encoding='utf-8'
        )
        summary = f"RE returncode={returncode}"
        if sanitizer:
            summary += " [ASan]"
        entry = {
            'id': fid,
            'type': 're',
            'timestamp': datetime.now().isoformat(),
            'source_file': str(source_file),
            'source_name': source_file.name,
            'path': str(fdir.relative_to(self.root)),
            'summary': summary,
            'source_type': source_type,
        }
        self._register_entry(entry)
        return fid

    def list_failures(self, type_filter: Optional[str] = None) -> List[Dict]:
        entries = self._index.get('entries', [])
        if type_filter:
            entries = [e for e in entries if e.get('type') == type_filter]
        return entries

    def list_command(self, type_filter: Optional[str] = None) -> bool:
        entries = self.list_failures(type_filter)
        if not entries:
            Console.info("没有历史失败记录")
            return True
        Console.bold(f"\n共 {len(entries)} 条失败记录:")
        print(f"{'ID':<34} {'类型':<10} {'时间':<20} 摘要")
        print("-" * 110)
        for e in entries:
            ts = e.get('timestamp', '')[:19].replace('T', ' ')
            summary = e.get('summary', '')[:50]
            typ = e.get('type', '?')
            typ_color = {
                'compile': Color.YELLOW,
                'wa': Color.RED,
                're': Color.MAGENTA,
            }.get(typ, Color.WHITE)
            typ_str = Console._c(f"{typ:<8}", typ_color)
            print(f"{e.get('id', '?'):<34} {typ_str} {ts:<20} {summary}")
        return True

    def show_failure(self, fid: str) -> bool:
        entries = self._index.get('entries', [])
        entry = next((e for e in entries if e.get('id') == fid), None)
        if not entry:
            matches = [e for e in entries if e.get('id', '').startswith(fid)]
            if len(matches) == 1:
                entry = matches[0]
            elif len(matches) > 1:
                Console.warn(f"ID 前缀匹配到 {len(matches)} 条记录，请提供更完整的 ID:")
                for m in matches:
                    print(f"  {m['id']}")
                return False
        if not entry:
            Console.error(f"未找到失败记录: {fid}")
            return False

        fdir = self.root / entry['path']
        if not fdir.exists():
            Console.error(f"记录目录不存在: {fdir}")
            return False

        Console.bold(f"\n=== 失败记录 {entry['id']} ===")
        Console.info(f"类型: {entry.get('type')}")
        Console.info(f"时间: {entry.get('timestamp')}")
        Console.info(f"源文件: {entry.get('source_file')}")
        if entry.get('source_type'):
            Console.info(f"来源: {entry.get('source_type')}")
        Console.info(f"摘要: {entry.get('summary', '')}")

        Console.bold("\n--- 文件列表 ---")
        for f in sorted(fdir.iterdir()):
            if f.is_file():
                print(f"  {f.name} ({f.stat().st_size} bytes)")

        if entry['type'] == 'compile':
            err_file = fdir / 'error.err'
            if err_file.exists():
                Console.bold("\n--- 编译错误 ---")
                print(err_file.read_text(encoding='utf-8'))
            ai_file = fdir / 'ai.txt'
            if ai_file.exists():
                Console.bold("\n--- AI 分析 ---")
                print(ai_file.read_text(encoding='utf-8'))
        elif entry['type'] == 'wa':
            for fn in ['input.txt', 'main_out.txt', 'brute_out.txt']:
                f = fdir / fn
                if f.exists():
                    Console.bold(f"\n--- {fn} ---")
                    content = f.read_text(encoding='utf-8')
                    if len(content) > 800:
                        content = content[:800] + f"\n... (共 {len(content)} 字符)"
                    print(content)
        elif entry['type'] == 're':
            for fn in ['input.txt', 'stderr.txt']:
                f = fdir / fn
                if f.exists():
                    Console.bold(f"\n--- {fn} ---")
                    content = f.read_text(encoding='utf-8')
                    if len(content) > 1500:
                        content = content[:1500] + f"\n... (共 {len(content)} 字符)"
                    print(content)
        return True

    def retry_failures(self, type_filter: Optional[str] = None) -> bool:
        entries = self.list_failures(type_filter)
        if not entries:
            Console.info("没有失败记录可重试")
            return True

        Console.info(f"共 {len(entries)} 条失败记录，开始重试...")
        success_count = 0
        fail_count = 0
        for entry in entries:
            fid = entry['id']
            fdir = self.root / entry['path']
            Console.bold(f"\n--- 重试 {fid} ({entry['type']}) ---")

            if entry['type'] == 'compile':
                src_files = [f for f in fdir.iterdir()
                             if f.is_file() and f.suffix.lower() in ('.cpp', '.c', '.cc', '.cxx', '.c++')]
                if not src_files:
                    Console.warn("未找到源码文件，跳过")
                    continue
                src = src_files[0]
                handler = PluginRegistry.get_handler(src.suffix)
                if not handler:
                    Console.warn(f"不支持的文件类型: {src.suffix}")
                    continue
                ok, err = handler.compile(src)
                if ok:
                    Console.success("编译通过 ✓")
                    success_count += 1
                else:
                    Console.error("编译仍失败")
                    fail_count += 1
            elif entry['type'] == 'wa':
                src_files = [f for f in fdir.iterdir()
                             if f.is_file() and f.suffix.lower() in ('.cpp', '.c', '.cc', '.cxx', '.c++', '.py')]
                if not src_files:
                    Console.warn("未找到源码文件，跳过")
                    continue
                src = src_files[0]
                handler = PluginRegistry.get_handler(src.suffix)
                if not handler:
                    Console.warn(f"不支持的文件类型: {src.suffix}")
                    continue
                if isinstance(handler, CompiledLanguageHandler):
                    ok, err = handler.compile(src)
                    if not ok:
                        Console.error("编译失败")
                        fail_count += 1
                        continue
                input_file = fdir / 'input.txt'
                brute_file = fdir / 'brute_out.txt'
                if not input_file.exists():
                    Console.warn("未找到输入文件，跳过")
                    continue
                try:
                    if isinstance(handler, PythonHandler):
                        interpreter = 'py' if shutil.which('py') else 'python'
                        cmd = [interpreter, str(src)]
                    else:
                        exe_path = src.with_suffix(EXE_SUFFIX)
                        if not exe_path.exists():
                            Console.error("可执行文件不存在")
                            fail_count += 1
                            continue
                        cmd = [str(exe_path)]
                    with open(input_file, 'r', encoding='utf-8') as inf:
                        proc = sp.run(cmd, stdin=inf, stdout=sp.PIPE, stderr=sp.PIPE,
                                      text=True, timeout=10, check=False)
                    if proc.returncode != 0:
                        Console.error(f"仍 RE (returncode={proc.returncode})")
                        fail_count += 1
                        continue
                    main_out = proc.stdout.strip()
                    if brute_file.exists():
                        expected = brute_file.read_text(encoding='utf-8').strip()
                        if main_out == expected:
                            Console.success("已修复 (输出匹配) ✓")
                            success_count += 1
                        else:
                            Console.error("仍然 WA")
                            fail_count += 1
                    else:
                        Console.info(f"无暴力输出，当前输出: {main_out[:100]}")
                        success_count += 1
                except sp.TimeoutExpired:
                    Console.error("仍 TLE")
                    fail_count += 1
                except Exception as e:
                    Console.error(f"重试异常: {e}")
                    fail_count += 1
            elif entry['type'] == 're':
                src_files = [f for f in fdir.iterdir()
                             if f.is_file() and f.suffix.lower() in ('.cpp', '.c', '.cc', '.cxx', '.c++')]
                if not src_files:
                    Console.warn("未找到源码文件，跳过")
                    continue
                src = src_files[0]
                handler = PluginRegistry.get_handler(src.suffix)
                if not handler:
                    continue
                ok, err = handler.compile(src)
                if not ok:
                    Console.error("编译失败")
                    fail_count += 1
                    continue
                input_file = fdir / 'input.txt'
                if not input_file.exists():
                    Console.warn("未找到输入文件，跳过")
                    continue
                exe_path = src.with_suffix(EXE_SUFFIX)
                if not exe_path.exists():
                    Console.error("可执行文件不存在")
                    fail_count += 1
                    continue
                try:
                    with open(input_file, 'r', encoding='utf-8') as inf:
                        proc = sp.run([str(exe_path)], stdin=inf,
                                      stdout=sp.PIPE, stderr=sp.PIPE,
                                      text=True, timeout=10, check=False)
                    if proc.returncode == 0:
                        Console.success("不再 RE ✓")
                        success_count += 1
                    else:
                        Console.error(f"仍 RE returncode={proc.returncode}")
                        fail_count += 1
                except sp.TimeoutExpired:
                    Console.error("仍 TLE")
                    fail_count += 1
                except Exception as e:
                    Console.error(f"重试异常: {e}")
                    fail_count += 1

        Console.bold(f"\n重试完成: 成功 {success_count}, 失败 {fail_count}")
        return fail_count == 0


# ======================== 动态模块导入 (ImportService) ========================
class ImportService:
    """ck import 子命令的服务。

    优先级: module_list > CommandFormat > Command

    行为矩阵::

        模式    --lazy  --persistence  行为
        非交互  ❌      ✅             立即导入，立即拷贝到加载目录
        非交互  ✅      ❌             报错
        非交互  ✅      ✅             报错
        交互    ❌      ✅             立即导入，立即拷贝
        交互    ✅      ❌             塞缓存，用时加载
        交互    ✅      ✅             塞缓存；真正加载的那一刻才拷贝
    """

    def __init__(self, config: ConfigManager):
        self.config = config
        self.cmd_dir = Path(config.get('commands.dir', str(COMMANDS_DIR)))
        self._imported: Dict[str, Dict[str, Any]] = {}
        self._lazy_cache: Dict[str, Dict[str, Any]] = {}
        self._is_interactive = False

    def set_interactive(self, flag: bool):
        self._is_interactive = flag

    def is_interactive(self) -> bool:
        return self._is_interactive

    def is_module_command(self, name: Optional[str]) -> bool:
        if not name or name == 'import':
            return False
        return name in self._imported or name in self._lazy_cache

    def list_imported(self) -> List[str]:
        return list(self._imported.keys())

    def list_pending(self) -> List[str]:
        return list(self._lazy_cache.keys())

    def load_module_file(self, path: Path, persistence: bool = False) -> bool:
        path = Path(path).resolve()
        if not path.exists():
            Console.error(f"模块文件不存在: {path}")
            return False
        if path.suffix.lower() != '.py':
            Console.error(f"仅支持 .py 文件: {path}")
            return False

        try:
            spec = importlib.util.spec_from_file_location(path.stem, path)
            if spec is None or spec.loader is None:
                Console.error(f"无法为 {path.name} 创建模块规范")
                return False
            module = importlib.util.module_from_spec(spec)
            module.__dict__.update({
                'CommandPlugin': CommandPlugin,
                'Console': Console,
                'config': config,
                'Path': Path,
                'Optional': Optional,
                'List': List,
                'Dict': Dict,
                'Tuple': Tuple,
                'argparse': argparse,
                'safe_run': safe_run,
            })
            spec.loader.exec_module(module)
        except Exception as e:
            Console.error(f"加载模块 {path.name} 失败: {e}")
            if VERBOSE:
                traceback.print_exc()
            return False

        found = False
        for attr_name in dir(module):
            attr = getattr(module, attr_name)
            if (isinstance(attr, type) and
                    issubclass(attr, CommandPlugin) and
                    attr is not CommandPlugin):
                try:
                    instance = attr()
                    if not instance.check_dependencies():
                        Console.warn(f"命令插件 {attr.__name__} 依赖检查未通过，已跳过")
                        continue
                    name = instance.get_name()
                    CommandRegistry._commands[name] = instance
                    self._imported[name] = {
                        'file': path,
                        'class': attr,
                        'module': module,
                    }
                    Console.success(f"已导入命令: {name} (来自 {path.name})")
                    found = True
                except Exception as e:
                    Console.error(f"注册命令插件 {attr.__name__} 失败: {e}")

        if not found:
            Console.warn(f"模块 {path.name} 中未找到 CommandPlugin 子类")

        if persistence:
            try:
                self.cmd_dir.mkdir(parents=True, exist_ok=True)
                dst = self.cmd_dir / path.name
                if dst.exists() and dst.resolve() != path.resolve():
                    ans = safe_input(f"目标文件 {dst} 已存在，覆盖? (y/N): ")
                    if ans.lower() != 'y':
                        Console.info("跳过拷贝到加载目录")
                        return found
                shutil.copy2(path, dst)
                Console.info(f"已拷贝到加载目录: {dst}")
            except Exception as e:
                Console.error(f"拷贝到加载目录失败: {e}")
                return False

        return found

    def try_resolve_lazy_for(self, command_name: str) -> bool:
        """如果 command_name 匹配缓存条目，则加载一个懒加载模块。"""
        if command_name not in self._lazy_cache:
            return False
        info = self._lazy_cache.pop(command_name)
        Console.info(f"懒加载触发: {info['path'].name}")
        return self.load_module_file(info['path'], persistence=info.get('persistence', False))

    def import_command(self, modules: List[str], lazy: bool = False,
                       persistence: bool = False, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将导入以下模块:")
            for m in modules:
                Console.info(f"  {m} (lazy={lazy}, persistence={persistence})")
            return True

        if lazy and not self._is_interactive:
            Console.error("--lazy 仅在交互模式下可用")
            return False

        success = True
        for m in modules:
            path = Path(m).resolve()
            if not path.exists():
                Console.error(f"模块文件不存在: {m}")
                success = False
                continue

            if lazy:
                key = path.stem
                if key in self._lazy_cache:
                    Console.warn(f"缓存中已存在同名模块 {key}，将被覆盖")
                self._lazy_cache[key] = {
                    'path': path,
                    'persistence': persistence,
                }
                Console.info(f"已加入缓存（使用时加载）: {path.name}")
            else:
                if not self.load_module_file(path, persistence=persistence):
                    success = False

        return success


# ======================== ddmin 增量调试 (v5.1，v5.2 修复 bug) ========================
def split_into(data: str, granularity: int) -> List[str]:
    """把 data 按行切分成 granularity 个 chunk，chunk 拼接即为原 data。

    为兼容 ddmin 中的 ``''.join(chunks[:i] + chunks[i+1:])``，
    每个 chunk 都保留其行尾换行符。
    """
    if granularity <= 1:
        return [data] if data else []
    lines = data.splitlines(keepends=True)
    if not lines:
        return [data] if data else []
    n = len(lines)
    chunk_size = max(1, (n + granularity - 1) // granularity)
    chunks = []
    for i in range(0, n, chunk_size):
        chunks.append(''.join(lines[i:i + chunk_size]))
    if not chunks:
        return [data]
    return chunks


def ddmin(input_data: str, test_fn: Callable[[str], bool]) -> str:
    """经典 ddmin 算法：在保证 test_fn(data) 为 True 的前提下，最小化 input_data。

    参数:
        input_data: 初始反例输入。
        test_fn: 接受候选数据，返回 True 表示“仍是反例”。

    返回:
        最小化后的数据字符串。若无法进一步缩减则返回原始数据。

    v5.2 修复:
        原实现在 ``granularity >= len(chunks)`` 时提前退出循环，但
        ``split_into`` 由于使用了 ``ceil(n/g)`` 的块大小，导致实际
        生成的 chunk 数可能小于 ``granularity``（例如 n=100, g=8 时
        chunk 数可能只有 8 或更少），从而过早停止，错过进一步缩减。
        正确终止条件应是与「行数」比较：``granularity >= len(lines)``。
    """
    data = input_data
    if not data:
        return data
    granularity = 2
    # 安全检查：初始反例必须成立
    try:
        if not test_fn(data):
            return data
    except Exception:
        return data

    max_iter = 10000  # 防御性上限，避免极端情况下卡死
    iters = 0
    while True:
        iters += 1
        if iters > max_iter:
            Console.warn(f"ddmin 达到最大迭代次数 ({max_iter})，提前结束")
            break
        lines = data.splitlines()
        if len(lines) <= 1:
            break
        chunks = split_into(data, granularity)
        if len(chunks) <= 1:
            break
        reduced = False
        for i, _chunk in enumerate(chunks):
            candidate = ''.join(chunks[:i] + chunks[i + 1:])
            if candidate == data:
                continue
            try:
                if test_fn(candidate):
                    data = candidate
                    granularity = max(2, granularity - 1)
                    reduced = True
                    break
            except Exception:
                continue
        if not reduced:
            # v5.2 修复：终止条件应基于行数，而不是实际 chunk 数
            if granularity >= len(lines):
                break
            granularity *= 2
    return data


# ======================== 对拍服务 (StressService) ========================
class StressService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.counterexample_dir = Path.cwd() / '.codekit-counterexamples'
        self.counterexample_dir.mkdir(parents=True, exist_ok=True)
        self.failure_lib = FailureLibrary(config)

    def _load_counterexamples(self) -> List[Tuple[Path, Path]]:
        result = []
        for entry in self.failure_lib.list_failures('wa'):
            fdir = self.failure_lib.root / entry['path']
            inp = fdir / 'input.txt'
            bo = fdir / 'brute_out.txt'
            if inp.exists() and bo.exists():
                result.append((inp, bo))
        for cex in sorted(self.counterexample_dir.glob('*.in')):
            ans = cex.with_suffix('.ans')
            if ans.exists():
                result.append((cex, ans))
        return result

    def _save_counterexample(self, input_data: str, main_out: str, brute_out: str,
                             source_file: Optional[Path] = None) -> Path:
        src = source_file if source_file else (Path.cwd() / 'main.cpp')
        fid = self.failure_lib.add_wa_failure(
            src, input_data, main_out, brute_out,
            error='WA', source_type='stress'
        )
        Console.info(f"反例已归档到统一失败库: {fid}")
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        fname = f"ce_{timestamp}.in"
        path = self.counterexample_dir / fname
        with open(path, 'w', encoding='utf-8') as f:
            f.write(input_data)
        ans_path = self.counterexample_dir / f"ce_{timestamp}.ans"
        ans_path.write_text(brute_out, encoding='utf-8')
        out_path = self.counterexample_dir / f"ce_{timestamp}.out"
        out_path.write_text(main_out, encoding='utf-8')
        return path

    def _run_counterexamples(self, main_exe: Path, brute_exe: Path, timeout: int,
                             eps: Optional[float],
                             checker_cmd: Optional[List[str]] = None) -> Tuple[bool, List[Dict]]:
        counterexamples = self._load_counterexamples()
        if not counterexamples:
            return True, []
        Console.info(f"正在运行 {len(counterexamples)} 个历史反例...")
        failed = []
        for input_file, expected_file in counterexamples:
            if not input_file.exists() or not expected_file.exists():
                continue
            input_data = input_file.read_text(encoding='utf-8')
            expected = expected_file.read_text(encoding='utf-8').strip()
            temp_out = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False)
            temp_out_name = temp_out.name
            temp_out.close()
            try:
                with open(input_file, 'r', encoding='utf-8') as inf:
                    proc = sp.run([str(main_exe)], stdin=inf, stdout=open(temp_out_name, 'w'),
                                  stderr=sp.PIPE, text=True, timeout=timeout, check=False)
                if proc.returncode != 0:
                    failed.append({'input': input_data, 'main_out': '', 'brute_out': expected,
                                   'error': f'RE returncode {proc.returncode}'})
                    continue
                with open(temp_out_name, 'r', encoding='utf-8') as f:
                    main_out = f.read().strip()
                if checker_cmd:
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as fin:
                        fin.write(input_data)
                        fin_name = fin.name
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.out', delete=False) as fout:
                        fout.write(main_out)
                        fout_name = fout.name
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.ans', delete=False) as fans:
                        fans.write(expected)
                        fans_name = fans.name
                    try:
                        ret_check = safe_run(checker_cmd + [fin_name, fout_name, fans_name],
                                             check=False, timeout=timeout)
                        if ret_check.returncode != 0:
                            failed.append({'input': input_data, 'main_out': main_out,
                                           'brute_out': expected, 'error': 'SPJ判定失败'})
                    finally:
                        os.unlink(fin_name)
                        os.unlink(fout_name)
                        os.unlink(fans_name)
                elif eps is not None:
                    try:
                        main_nums = list(map(float, main_out.split()))
                        brute_nums = list(map(float, expected.split()))
                        if len(main_nums) != len(brute_nums):
                            failed.append({'input': input_data, 'main_out': main_out,
                                           'brute_out': expected, 'error': '长度不同'})
                            continue
                        mismatch = False
                        for a, b in zip(main_nums, brute_nums):
                            if not math.isclose(a, b, abs_tol=eps):
                                mismatch = True
                                break
                        if mismatch:
                            failed.append({'input': input_data, 'main_out': main_out,
                                           'brute_out': expected, 'error': f'差值 > {eps}'})
                    except ValueError:
                        if main_out != expected:
                            failed.append({'input': input_data, 'main_out': main_out,
                                           'brute_out': expected, 'error': '字符串不同'})
                else:
                    if main_out != expected:
                        failed.append({'input': input_data, 'main_out': main_out,
                                       'brute_out': expected, 'error': '字符串不同'})
            except sp.TimeoutExpired:
                failed.append({'input': input_data, 'main_out': '', 'brute_out': expected,
                               'error': '超时'})
            except Exception as e:
                failed.append({'input': input_data, 'main_out': '', 'brute_out': expected,
                               'error': str(e)})
            finally:
                try:
                    os.unlink(temp_out_name)
                except Exception:
                    pass
        return len(failed) == 0, failed

    def _compile_checker(self, checker_path: Path) -> Optional[List[str]]:
        if not checker_path.exists():
            Console.error(f"Checker 文件不存在: {checker_path}")
            return None
        handler = PluginRegistry.get_handler(checker_path.suffix)
        if not handler:
            Console.error(f"不支持 checker 文件类型: {checker_path.suffix}")
            return None
        if isinstance(handler, CompiledLanguageHandler):
            Console.info(f"编译 Checker: {checker_path}")
            ok, err = handler.compile(checker_path)
            if not ok:
                Console.error("Checker 编译失败")
                return None
            exe = checker_path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("Checker 可执行文件未生成")
                return None
            return [str(exe)]
        else:
            Console.error("Checker 必须为编译型语言")
            return None

    def _compile_cpp(self, code: str) -> bool:
        fname = None
        exe = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.cpp', delete=False) as tf:
                tf.write(code)
                fname = tf.name
            exe = fname + EXE_SUFFIX
            ret = safe_run(['g++', fname, '-o', exe], timeout=10, check=False)
            return ret.returncode == 0
        except Exception:
            return False
        finally:
            if fname:
                try:
                    os.unlink(fname)
                except Exception:
                    pass
            if exe and os.path.exists(exe):
                try:
                    os.unlink(exe)
                except Exception:
                    pass

    def _check_python_syntax(self, code: str) -> bool:
        import py_compile
        fname = None
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tf:
                tf.write(code)
                fname = tf.name
            py_compile.compile(fname, doraise=True)
            return True
        except Exception:
            return False
        finally:
            if fname:
                try:
                    os.unlink(fname)
                except Exception:
                    pass

    def _generate_bruteforce(self, main_file: Path) -> Optional[Path]:
        try:
            main_content = main_file.read_text(encoding='utf-8')
        except Exception:
            Console.error("读取主文件失败")
            return None

        desc = ""
        desc_patterns = [
            r'//\s*题目[：:]\s*(.+?)(?:\n|$)',
            r'/\*\s*题目[：:]\s*(.+?)\s*\*/',
            r'#\s*题目[：:]\s*(.+?)(?:\n|$)',
            r'//\s*Problem[：:]\s*(.+?)(?:\n|$)',
        ]
        for pat in desc_patterns:
            m = re.search(pat, main_content, re.IGNORECASE | re.DOTALL)
            if m:
                desc = m.group(1).strip()
                break
        if not desc:
            m = re.match(r'/\*([\s\S]*?)\*/', main_content)
            if m:
                desc = m.group(1).strip()
            else:
                desc = "未提供题目描述，请自行补充。"

        prompt = f"""请根据以下题目描述，生成一个 C++ 暴力解法程序（朴素算法），时间复杂度可以较高，但必须正确。
题目描述：
{desc}

要求：
- 使用 #include <bits/stdc++.h> 和 using namespace std;
- main 函数读取标准输入，输出标准输出
- 代码简洁，添加必要的注释
- 请确保代码可以直接编译运行，无语法错误，并且包含 main 函数。
- 只输出代码，不要有任何额外文字
"""
        try:
            ai = AIService(self.config)
            response = ai.generate(prompt, temperature=0.3, max_tokens=800, context_aware=False)
            code_blocks = re.findall(r'```(?:cpp|c\+\+)?\n(.*?)```', response, re.DOTALL)
            if code_blocks:
                code = code_blocks[0]
            else:
                code = response
            code = re.sub(r'^```(?:cpp|c\+\+)?\s*', '', code, flags=re.MULTILINE)
            code = re.sub(r'```\s*$', '', code, flags=re.MULTILINE)
            if not code.strip():
                Console.error("AI 生成的暴力代码为空")
                return None

            if not self._compile_cpp(code):
                Console.error("AI 生成的暴力代码编译失败，请手动提供暴力程序")
                return None

            brute_path = Path.cwd() / 'brute_auto.cpp'
            brute_path.write_text(code, encoding='utf-8')
            Console.success(f"AI 生成暴力代码并编译通过: {brute_path}")
            return brute_path
        except Exception as e:
            Console.error(f"AI 生成暴力失败: {e}")
            return None

    def _generate_generator(self, main_file: Path) -> Optional[Path]:
        try:
            main_content = main_file.read_text(encoding='utf-8')
        except Exception:
            Console.error("读取主文件失败")
            return None

        desc = ""
        desc_patterns = [
            r'//\s*题目[：:]\s*(.+?)(?:\n|$)',
            r'/\*\s*题目[：:]\s*(.+?)\s*\*/',
            r'#\s*题目[：:]\s*(.+?)(?:\n|$)',
            r'//\s*Problem[：:]\s*(.+?)(?:\n|$)',
        ]
        for pat in desc_patterns:
            m = re.search(pat, main_content, re.IGNORECASE | re.DOTALL)
            if m:
                desc = m.group(1).strip()
                break
        if not desc:
            desc = "未提供题目描述，请自行补充。"

        prompt = f"""请根据以下题目描述，生成一个 Python 随机数据生成器，用于对拍测试。
题目描述：
{desc}

要求：
- 生成符合题目输入格式的随机数据
- 使用 sys.stdout.write 输出
- 可以接受命令行参数（如 --seed, --n 等）来控制数据规模，但要有合理的默认值
- 输出到标准输出
- 请确保代码语法正确，可直接运行。
- 只输出代码，不要有任何额外文字
- 文件名建议为 gen_auto.py
"""
        try:
            ai = AIService(self.config)
            response = ai.generate(prompt, temperature=0.4, max_tokens=600, context_aware=False)
            code_blocks = re.findall(r'```(?:python)?\n(.*?)```', response, re.DOTALL)
            if code_blocks:
                code = code_blocks[0]
            else:
                code = response
            code = re.sub(r'^```(?:python)?\s*', '', code, flags=re.MULTILINE)
            code = re.sub(r'```\s*$', '', code, flags=re.MULTILINE)
            if not code.strip():
                Console.error("AI 生成的生成器为空")
                return None

            if not self._check_python_syntax(code):
                Console.error("AI 生成的生成器存在语法错误，请手动提供生成器")
                return None

            gen_path = Path.cwd() / 'gen_auto.py'
            gen_path.write_text(code, encoding='utf-8')
            Console.success(f"AI 生成数据生成器并语法检查通过: {gen_path}")
            return gen_path
        except Exception as e:
            Console.error(f"AI 生成生成器失败: {e}")
            return None

    def stress(self, main_file: str, brute_file: str, gen_file: str,
               cases: int = 100, timeout: int = None, gen_args: List[str] = None,
               shrink: bool = False, parallel: bool = False, workers: int = 4,
               eps: Optional[float] = None, sanitize: bool = False,
               checker: Optional[str] = None, celebrate: bool = False, dry_run: bool = False,
               auto_generate: bool = False, replay: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将对拍执行以下操作:")
            Console.info(f"  主程序: {main_file}")
            Console.info(f"  暴力程序: {brute_file}")
            Console.info(f"  生成器: {gen_file}")
            Console.info(f"  测试组数: {cases}")
            Console.info(f"  超时: {timeout if timeout else self.config.get('oi.timeout', 5)}s")
            Console.info(f"  选项: shrink={shrink} (ddmin), parallel={parallel}, sanitize={sanitize}, checker={checker}, celebrate={celebrate}, auto={auto_generate}, replay={replay}")
            return True

        main_path = Path(main_file)
        if not main_path.exists():
            Console.error(f"主程序文件不存在: {main_file}")
            return False

        if replay:
            main_handler = PluginRegistry.get_handler(main_path.suffix)
            if not main_handler:
                Console.error(f"不支持的主程序类型: {main_path.suffix}")
                return False
            Console.info(f"编译主程序: {main_file} (sanitize={sanitize})")
            ok, err = main_handler.compile(main_path, sanitize=sanitize)
            if not ok:
                Console.error("主程序编译失败")
                return False
            main_exe = main_path.with_suffix(EXE_SUFFIX)
            if not main_exe.exists():
                Console.error("主程序可执行文件未生成")
                return False

            brute_exe = None
            if brute_file and Path(brute_file).exists():
                brute_path = Path(brute_file)
                brute_handler = PluginRegistry.get_handler(brute_path.suffix)
                if brute_handler:
                    Console.info(f"编译暴力程序: {brute_file}")
                    ok, err = brute_handler.compile(brute_path)
                    if ok:
                        brute_exe = brute_path.with_suffix(EXE_SUFFIX)
                        if not brute_exe.exists():
                            Console.warn("暴力程序可执行文件未生成，重放将跳过暴力比较")
                            brute_exe = None
                    else:
                        Console.warn("暴力程序编译失败，重放将跳过暴力比较")
                else:
                    Console.warn(f"不支持暴力程序类型: {brute_path.suffix}")
            else:
                Console.warn("未提供暴力程序，重放将只运行主程序，不进行比较（如果有期望输出则比较）")

            checker_cmd = None
            if checker:
                checker_cmd = self._compile_checker(Path(checker))
                if checker_cmd is None:
                    return False

            timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 5))
            ok, fails = self._run_counterexamples(main_exe, brute_exe, timeout_val, eps, checker_cmd)
            if ok:
                Console.success("所有历史反例通过")
            else:
                Console.warn(f"有 {len(fails)} 个历史反例失败")
                for f in fails:
                    Console.error(f"  输入: {f['input'][:100]}... 错误: {f.get('error', '')}")
            return ok

        if auto_generate:
            if brute_file == 'brute_auto.cpp' or not Path(brute_file).exists():
                gen_brute = self._generate_bruteforce(main_path)
                if gen_brute:
                    brute_file = str(gen_brute)
                else:
                    Console.error("自动生成暴力失败，请手动提供暴力程序")
                    return False
            if gen_file == 'gen_auto.py' or not Path(gen_file).exists():
                gen_gen = self._generate_generator(main_path)
                if gen_gen:
                    gen_file = str(gen_gen)
                else:
                    Console.error("自动生成生成器失败，请手动提供生成器")
                    return False
            Console.success("AI 自动生成对拍三件套完成，开始对拍...")

        brute_path = Path(brute_file)
        gen_path = Path(gen_file)
        if not brute_path.exists():
            Console.error(f"暴力程序文件不存在: {brute_file}")
            return False
        if not gen_path.exists():
            Console.error(f"生成器文件不存在: {gen_file}")
            return False

        checker_cmd = None
        if checker:
            checker_cmd = self._compile_checker(Path(checker))
            if checker_cmd is None:
                return False

        main_handler = PluginRegistry.get_handler(main_path.suffix)
        brute_handler = PluginRegistry.get_handler(brute_path.suffix)
        if not main_handler or not brute_handler:
            Console.error("不支持的文件类型")
            return False

        Console.info(f"编译主程序: {main_file} (sanitize={sanitize})")
        ok, err = main_handler.compile(main_path, sanitize=sanitize)
        if not ok:
            Console.error("主程序编译失败")
            return False
        main_exe = main_path.with_suffix(EXE_SUFFIX)
        if not main_exe.exists():
            Console.error("主程序可执行文件未生成")
            return False

        Console.info(f"编译暴力程序: {brute_file}")
        ok, err = brute_handler.compile(brute_path)
        if not ok:
            Console.error("暴力程序编译失败")
            return False
        brute_exe = brute_path.with_suffix(EXE_SUFFIX)
        if not brute_exe.exists():
            Console.error("暴力程序可执行文件未生成")
            return False

        gen_cmd = self._prepare_gen_cmd(gen_path)
        if gen_cmd is None:
            return False

        timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 5))
        Console.info(f"开始对拍，测试 {cases} 组数据，超时 {timeout_val}s" +
                     (f"，容差 eps={eps}" if eps is not None else "") +
                     (f"，使用 SPJ: {checker}" if checker else ""))

        ok, fails = self._run_counterexamples(main_exe, brute_exe, timeout_val, eps, checker_cmd)
        if not ok:
            Console.warn(f"历史反例中有 {len(fails)} 个失败:")
            for f in fails:
                Console.error(f"  输入: {f['input'][:100]}... 错误: {f.get('error', '')}")

        temp_dir = tempfile.mkdtemp(prefix='codekit_stress_')
        results = []
        failed = False
        try:
            Console.info("生成输入数据...")
            input_files = []
            pbar = tqdm.tqdm(total=cases, desc="生成数据", unit="组") if tqdm is not None else None
            for i in range(1, cases + 1):
                input_file = Path(temp_dir) / f"input_{i}.txt"
                with open(input_file, 'w', encoding='utf-8') as f:
                    try:
                        gen_proc = sp.run(gen_cmd + (gen_args or []),
                                          stdout=f, stderr=sp.PIPE, text=True,
                                          timeout=timeout_val, check=False)
                        if gen_proc.returncode != 0:
                            Console.error(f"生成器运行失败 (第 {i} 组): {gen_proc.stderr}")
                            failed = True
                            break
                    except sp.TimeoutExpired:
                        Console.error(f"生成器超时 (第 {i} 组)")
                        failed = True
                        break
                if failed:
                    break
                input_files.append(input_file)
                if pbar is not None:
                    pbar.update(1)
            if pbar is not None:
                pbar.close()
            if failed:
                return False

            Console.info("运行程序并收集输出...")
            if parallel:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    futures = []
                    for idx, inf in enumerate(input_files):
                        futures.append(executor.submit(self._run_single_case, idx + 1, inf, main_exe,
                                                       brute_exe, timeout_val, temp_dir, eps, checker_cmd))
                    pbar = tqdm.tqdm(total=len(futures), desc="对拍进度", unit="组") if tqdm is not None else None
                    for fut in as_completed(futures):
                        result = fut.result()
                        results.append(result)
                        if pbar is not None:
                            pbar.update(1)
                    if pbar is not None:
                        pbar.close()
                results.sort(key=lambda x: x['index'])
            else:
                pbar = tqdm.tqdm(total=len(input_files), desc="对拍进度", unit="组") if tqdm is not None else None
                for idx, inf in enumerate(input_files):
                    result = self._run_single_case(idx + 1, inf, main_exe, brute_exe,
                                                   timeout_val, temp_dir, eps, checker_cmd)
                    results.append(result)
                    if pbar is not None:
                        pbar.update(1)
                if pbar is not None:
                    pbar.close()

            Console.bold("\n" + "=" * 60)
            Console.bold("对拍统计报告")
            Console.bold("=" * 60)

            total = len(results)
            passed = 0
            failed_cases = []
            max_time = 0.0
            max_mem = 0.0
            for r in results:
                if r['status'] == 'AC':
                    passed += 1
                    if r['main_time'] > max_time:
                        max_time = r['main_time']
                    if r.get('main_mem', 0) > max_mem:
                        max_mem = r.get('main_mem', 0)
                elif r['status'] in ('WA', 'TLE', 'RE', 'ERROR'):
                    failed_cases.append(r)

            Console.info(f"总测试组数: {total}")
            Console.info(f"通过组数: {passed}")
            Console.info(f"通过率: {passed / total * 100:.2f}%")
            Console.info(f"最慢测试点耗时: {max_time:.3f}s")
            if max_mem > 0:
                Console.info(f"最大内存峰值: {max_mem:.2f} MB")

            if failed_cases:
                Console.warn(f"失败组数: {len(failed_cases)}")
                for case in failed_cases:
                    Console.bold(f"\n失败 Case #{case['index']}: {case['status']}")
                    if case['status'] == 'WA':
                        Console.info("输入:")
                        print(case['input'])
                        Console.info("主程序输出:")
                        print(case['main_out'])
                        Console.info("暴力程序输出:")
                        print(case['brute_out'])
                        self._save_counterexample(case['input'], case['main_out'],
                                                  case['brute_out'], source_file=main_path)
                    elif case['status'] == 'TLE':
                        Console.info("输入:")
                        print(case['input'])
                        Console.warn("主程序超时")
                    elif case['status'] == 'RE':
                        Console.info("输入:")
                        print(case['input'])
                        Console.error(f"主程序返回码: {case.get('returncode', '?')}")
                        if case.get('main_err'):
                            if 'ERROR: AddressSanitizer' in case['main_err']:
                                Console.error("检测到 AddressSanitizer 报告:")
                                print(case['main_err'])
                            else:
                                Console.error(case['main_err'])
                        try:
                            fid = self.failure_lib.add_re_failure(
                                main_path,
                                case.get('input', ''),
                                case.get('main_err', '') or '',
                                returncode=case.get('returncode', 0),
                                sanitizer='AddressSanitizer' in (case.get('main_err', '') or ''),
                                source_type='stress'
                            )
                            Console.info(f"RE 现场已归档: {fid}")
                        except Exception as e:
                            Console.warn(f"归档 RE 现场失败: {e}")

                if shrink and len(failed_cases) > 0:
                    Console.bold("\n使用 ddmin 增量调试缩小反例...")
                    first_fail = failed_cases[0]
                    shrink_result = self._shrink_case(
                        main_exe, brute_exe, gen_cmd, gen_args,
                        first_fail['input'], timeout_val, temp_dir, eps, checker_cmd
                    )
                    if shrink_result:
                        Console.bold("\n最小反例已找到 (ddmin):")
                        Console.info("输入:")
                        print(shrink_result['input'])
                        Console.info("主程序输出:")
                        print(shrink_result['main_out'])
                        Console.info("暴力程序输出:")
                        print(shrink_result['brute_out'])
                        self._save_counterexample(shrink_result['input'],
                                                  shrink_result['main_out'],
                                                  shrink_result['brute_out'],
                                                  source_file=main_path)
                    else:
                        Console.info("ddmin 未能进一步缩小反例（已是最小或未命中 WA）")
            else:
                Console.success("所有测试通过！")
                if celebrate:
                    self._celebrate()

            return len(failed_cases) == 0 and ok

        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def _prepare_gen_cmd(self, gen_path: Path):
        gen_suffix = gen_path.suffix.lower()
        if gen_suffix == '.py':
            interpreter = 'py' if shutil.which('py') else ('python' if shutil.which('python') else 'python3')
            return [interpreter, str(gen_path)]
        else:
            gen_handler = PluginRegistry.get_handler(gen_suffix)
            if gen_handler and isinstance(gen_handler, CompiledLanguageHandler):
                Console.info(f"编译生成器: {gen_path}")
                ok, err = gen_handler.compile(gen_path)
                if not ok:
                    Console.error("生成器编译失败")
                    return None
                gen_exe = gen_path.with_suffix(EXE_SUFFIX)
                if not gen_exe.exists():
                    Console.error("生成器可执行文件未生成")
                    return None
                return [str(gen_exe)]
            else:
                Console.error(f"生成器文件类型 {gen_suffix} 不支持，请使用 .py 或编译型语言")
                return None

    def _run_single_case(self, idx: int, input_file: Path, main_exe: Path, brute_exe: Path,
                         timeout: int, temp_dir: str, eps: Optional[float],
                         checker_cmd: Optional[List[str]] = None) -> Dict:
        result = {
            'index': idx,
            'status': 'AC',
            'input': '',
            'main_out': '',
            'brute_out': '',
            'main_time': 0.0,
            'main_mem': 0.0,
            'main_err': '',
            'returncode': 0,
        }
        try:
            input_data = input_file.read_text(encoding='utf-8')
            result['input'] = input_data

            main_out_file = Path(temp_dir) / f"main_{idx}.txt"
            main_start = time.time()
            try:
                with open(input_file, 'r', encoding='utf-8') as inf:
                    with open(main_out_file, 'w', encoding='utf-8') as f:
                        proc_main = sp.run([str(main_exe)], stdin=inf, stdout=f,
                                           stderr=sp.PIPE, text=True, timeout=timeout, check=False)
                main_elapsed = time.time() - main_start
                result['main_time'] = main_elapsed
                result['main_err'] = proc_main.stderr
                result['returncode'] = proc_main.returncode
                if main_out_file.exists():
                    result['main_out'] = main_out_file.read_text(encoding='utf-8').strip()
                if proc_main.returncode != 0:
                    result['status'] = 'RE'
                    return result
            except sp.TimeoutExpired:
                result['status'] = 'TLE'
                result['main_err'] = f"Timeout > {timeout}s"
                return result

            brute_out_file = Path(temp_dir) / f"brute_{idx}.txt"
            try:
                with open(input_file, 'r', encoding='utf-8') as inf:
                    with open(brute_out_file, 'w', encoding='utf-8') as f:
                        proc_brute = sp.run([str(brute_exe)], stdin=inf, stdout=f,
                                            stderr=sp.PIPE, text=True, timeout=timeout, check=False)
                if proc_brute.returncode != 0:
                    result['status'] = 'ERROR'
                    result['brute_out'] = f"Brute exited with {proc_brute.returncode}"
                    return result
                if brute_out_file.exists():
                    result['brute_out'] = brute_out_file.read_text(encoding='utf-8').strip()
            except sp.TimeoutExpired:
                result['status'] = 'ERROR'
                result['brute_out'] = "Brute timeout"
                return result

            if checker_cmd is not None:
                with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as fin:
                    fin.write(input_data)
                    fin_name = fin.name
                with tempfile.NamedTemporaryFile(mode='w', suffix='.out', delete=False) as fout:
                    fout.write(result['main_out'])
                    fout_name = fout.name
                with tempfile.NamedTemporaryFile(mode='w', suffix='.ans', delete=False) as fans:
                    fans.write(result['brute_out'])
                    fans_name = fans.name
                try:
                    ret_check = safe_run(checker_cmd + [fin_name, fout_name, fans_name],
                                         check=False, timeout=timeout)
                    if ret_check.returncode != 0:
                        result['status'] = 'WA'
                finally:
                    os.unlink(fin_name)
                    os.unlink(fout_name)
                    os.unlink(fans_name)
            elif eps is not None:
                try:
                    main_nums = list(map(float, result['main_out'].split()))
                    brute_nums = list(map(float, result['brute_out'].split()))
                    if len(main_nums) != len(brute_nums):
                        result['status'] = 'WA'
                        return result
                    for a, b in zip(main_nums, brute_nums):
                        if not math.isclose(a, b, abs_tol=eps):
                            result['status'] = 'WA'
                            return result
                except ValueError:
                    if result['main_out'] != result['brute_out']:
                        result['status'] = 'WA'
            else:
                if result['main_out'] != result['brute_out']:
                    result['status'] = 'WA'
            return result
        except Exception as e:
            result['status'] = 'ERROR'
            result['main_err'] = str(e)
            return result

    def _shrink_case(self, main_exe: Path, brute_exe: Path, gen_cmd: List[str],
                     gen_args: List[str], input_data: str, timeout: int, work_dir: str,
                     eps: Optional[float], checker_cmd: Optional[List[str]] = None) -> Optional[Dict]:
        """使用 ddmin 增量调试把反例缩减到最小。

        v5.1 起，把原来的“按比例截断 / 按 n= 替换”策略替换为经典 ddmin：
          - granularity 从 2 起步；
          - 尝试删除每个 chunk，如果能保持“仍是反例”，则接受并降低 granularity；
          - 否则提高 granularity 细分，直到 granularity >= 行数（v5.2 修复）。

        v5.2 修复说明:
            原实现的终止条件是 ``granularity >= len(chunks)``，但由于
            ``split_into`` 采用 ``ceil(n/g)`` 分块，实际 chunk 数可能小于
            granularity（例如 n=100, g=8 时只有 8 个 chunk 甚至更少），
            从而导致 ddmin 过早终止。修复后终止条件基于原始行数。
        """
        if not input_data:
            return None

        # 使用固定临时文件承载候选输入，避免与其它逻辑冲突
        test_input = Path(work_dir) / "_shrink_test_input.txt"

        def test_fn(candidate: str) -> bool:
            """True 表示 candidate 仍然是反例（WA）。"""
            try:
                test_input.write_text(candidate, encoding='utf-8')
            except Exception:
                return False
            try:
                res = self._run_single_case(
                    0, test_input, main_exe, brute_exe,
                    timeout, work_dir, eps, checker_cmd
                )
            except Exception:
                return False
            # 仅当仍是 WA 时，接受为反例（保持与原“截断”一致的语义）
            return res.get('status') == 'WA'

        # 初始必须能复现 WA
        if not test_fn(input_data):
            Console.warn("ddmin: 初始输入未命中 WA，跳过缩小")
            return None

        Console.info(f"ddmin 开始，初始长度 {len(input_data)} 字符 / {len(input_data.splitlines())} 行")
        try:
            minimized = ddmin(input_data, test_fn)
        except Exception as e:
            Console.warn(f"ddmin 执行异常: {e}")
            return None

        if minimized == input_data:
            Console.info("ddmin 未找到更小的反例")
            return None

        # 收集最小化后的输出
        try:
            test_input.write_text(minimized, encoding='utf-8')
            final = self._run_single_case(
                0, test_input, main_exe, brute_exe,
                timeout, work_dir, eps, checker_cmd
            )
        except Exception as e:
            Console.warn(f"ddmin 结果复验失败: {e}")
            return None

        if final.get('status') != 'WA':
            Console.warn("ddmin 结果复验不再是 WA，放弃")
            return None

        Console.info(
            f"ddmin 完成: {len(input_data)} -> {len(minimized)} 字符 "
            f"({len(input_data.splitlines())} -> {len(minimized.splitlines())} 行)"
        )
        return {
            'input': minimized,
            'main_out': final.get('main_out', ''),
            'brute_out': final.get('brute_out', ''),
        }

    def _celebrate(self):
        ascii_art = [
            r"""
   ／l、
  （ﾟ､ ｡ ７
   l、 ~ヽ
   じしf_,)ノ
""",
            r"""
　 　 ／⌒ヽ
　 　 （´・ω・）
　 　 （　　　）
　 　 ｜　｜
　 （＿_）＿）
""",
            r"""
　 ∧_∧
　( ･ω･)
　/　○＼
　/　　　ヽ
　|　 　 ｜
　ヽ　　_/
"""
        ]
        lyrics = [
            "Nee~! 这次是 Teto 帮你的！",
            "Miku 说：你做得很好！",
            "Love Teto! Love Miku!",
            "代码全 AC，Teto 很开心～",
            "Nee~ 今天也是美好的一天！"
        ]
        if random.random() < 0.5:
            art = random.choice(ascii_art)
            print(Console._c(art, Color.CYAN))
        else:
            lyric = random.choice(lyrics)
            print(Console._c("♪ " + lyric, Color.MAGENTA))


# ======================== 交互题服务 (v5.2 新增) ========================
class InteractService:
    """交互题支持。

    工作方式：
      1. 编译选手程序和交互器
      2. 运行交互器，把选手程序可执行文件路径作为 ``argv[1]`` 传入
      3. 交互器通过管道 / 子进程负责与选手程序通信
      4. 交互器的退出码即为最终结果（0 表示通过）

    约定（交互器需遵循）：
      - ``argv[1]``：选手程序可执行文件路径
      - ``stdin``：可选输入数据文件（通过 ``--input`` 提供）
      - 交互器完全负责子进程 / 管道通信与最终判定
    """

    def __init__(self, config: ConfigManager):
        self.config = config

    def interact(self, player: str, interactor: str,
                 input_file: Optional[str] = None,
                 timeout: Optional[int] = None,
                 player_args: Optional[List[str]] = None,
                 interactor_args: Optional[List[str]] = None,
                 dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 交互题运行:")
            Console.info(f"  选手程序: {player}")
            Console.info(f"  交互器:   {interactor}")
            Console.info(f"  输入文件: {input_file if input_file else '无'}")
            Console.info(f"  超时:     {timeout if timeout else self.config.get('oi.timeout', 5)}s")
            Console.info(f"  选手参数: {player_args if player_args else '无'}")
            Console.info(f"  交互参数: {interactor_args if interactor_args else '无'}")
            return True

        player_path = Path(player)
        interactor_path = Path(interactor)

        if not player_path.exists():
            Console.error(f"选手程序不存在: {player}")
            return False
        if not interactor_path.exists():
            Console.error(f"交互器不存在: {interactor}")
            return False

        player_handler = PluginRegistry.get_handler(player_path.suffix)
        interactor_handler = PluginRegistry.get_handler(interactor_path.suffix)
        if not player_handler:
            Console.error(f"不支持的选手程序类型: {player_path.suffix}")
            return False
        if not interactor_handler:
            Console.error(f"不支持的交互器类型: {interactor_path.suffix}")
            return False

        # ---- 编译选手程序 ----
        if isinstance(player_handler, CompiledLanguageHandler):
            Console.info(f"编译选手程序: {player}")
            ok, err = player_handler.compile(player_path)
            if not ok:
                Console.error("选手程序编译失败")
                if err:
                    print(err)
                return False
            player_exec = player_path.with_suffix(EXE_SUFFIX)
        elif isinstance(player_handler, PythonHandler):
            # Python 脚本，把脚本路径传给交互器（交互器需自行用解释器启动）
            player_exec = player_path.resolve()
        else:
            player_exec = player_path.resolve()

        # ---- 编译交互器 ----
        interactor_py_script = None
        if isinstance(interactor_handler, CompiledLanguageHandler):
            Console.info(f"编译交互器: {interactor}")
            ok, err = interactor_handler.compile(interactor_path)
            if not ok:
                Console.error("交互器编译失败")
                if err:
                    print(err)
                return False
            interactor_exec = interactor_path.with_suffix(EXE_SUFFIX)
        elif isinstance(interactor_handler, PythonHandler):
            interactor_py_script = interactor_path.resolve()
            interactor_exec = interactor_path.resolve()
        else:
            interactor_exec = interactor_path.resolve()

        # ---- 构建交互器启动命令 ----
        if interactor_py_script is not None:
            if shutil.which('py'):
                interpreter = 'py'
            elif shutil.which('python'):
                interpreter = 'python'
            else:
                interpreter = 'python3'
            cmd: List[str] = [interpreter, str(interactor_py_script)]
        else:
            cmd = [str(interactor_exec)]

        # 约定：argv[1] 为选手程序可执行文件路径
        cmd.append(str(player_exec))

        # 交互器额外参数
        if interactor_args:
            cmd.extend(interactor_args)

        # 选手程序参数（放在选手程序路径后，由交互器解析，建议使用 = 分割）
        if player_args:
            cmd.extend(player_args)

        timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 5))

        Console.info(f"启动交互器: {' '.join(cmd)}")

        input_fh = None
        proc = None
        try:
            if input_file:
                input_path = Path(input_file)
                if not input_path.exists():
                    Console.error(f"输入文件不存在: {input_file}")
                    return False
                input_fh = open(input_path, 'r', encoding='utf-8')

            start_time = time.time()
            try:
                proc = sp.Popen(
                    cmd,
                    stdin=input_fh if input_fh else sp.DEVNULL,
                    stdout=sp.PIPE,
                    stderr=sp.PIPE,
                    text=True,
                    encoding='utf-8',
                    errors='replace',
                    cwd=str(Path.cwd()),
                )
                _register_popen(proc)
            except Exception as e:
                Console.error(f"启动交互器失败: {e}")
                return False

            try:
                stdout, stderr = proc.communicate(timeout=timeout_val)
            except sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                try:
                    stdout, stderr = proc.communicate(timeout=2)
                except Exception:
                    stdout, stderr = '', ''
                Console.error(f"交互超时 (> {timeout_val}s)")
                return False
            finally:
                _unregister_popen(proc)

            elapsed = time.time() - start_time
            Console.info(f"交互耗时: {elapsed:.3f}s")

            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)

            if proc.returncode == 0:
                Console.success("交互完成，结果正常 (returncode=0)")
                return True
            else:
                Console.error(f"交互器返回码: {proc.returncode}")
                return False
        except Exception as e:
            Console.error(f"交互运行失败: {e}")
            if VERBOSE:
                traceback.print_exc()
            return False
        finally:
            if input_fh:
                try:
                    input_fh.close()
                except Exception:
                    pass


class TestService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.failure_lib = FailureLibrary(config)

    def _set_memory_limit_warn(self, limit_mb: int):
        if limit_mb is None or limit_mb <= 0:
            return
        if sys.platform == 'win32':
            Console.warn("Windows 不支持内存限制，忽略 --memory-limit")

    def test(self, main_file: str, input_dir: str = None, output_dir: str = None,
             timeout: int = None, compare_exact: bool = True,
             cktest_file: str = None, sanitize: bool = False,
             memory_limit_mb: Optional[int] = None, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行以下测试:")
            Console.info(f"  主程序: {main_file}")
            Console.info(f"  输入目录: {input_dir if input_dir else '(自动检测)'}")
            Console.info(f"  输出目录: {output_dir if output_dir else '自动查找'}")
            Console.info(f"  超时: {timeout if timeout else self.config.get('oi.timeout', 5)}s")
            Console.info(f"  内存限制: {memory_limit_mb if memory_limit_mb else '默认'} MB")
            Console.info(f"  sanitize: {sanitize}")
            Console.info(f"  数据包: {cktest_file if cktest_file else '无'}")
            return True

        main_path = Path(main_file)
        if not main_path.exists():
            Console.error(f"主程序文件不存在: {main_file}")
            return False
        handler = PluginRegistry.get_handler(main_path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {main_path.suffix}")
            return False

        if isinstance(handler, CompiledLanguageHandler):
            Console.info(f"编译主程序: {main_file} (sanitize={sanitize})")
            ok, err = handler.compile(main_path, sanitize=sanitize)
            if not ok:
                Console.error("编译失败")
                return False
            exe = main_path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("可执行文件未生成")
                return False
        else:
            exe = main_path

        # v5.2: 输入目录变为可选，自动检测 data/in → data → .
        if input_dir:
            in_dir = Path(input_dir)
        else:
            in_dir = _auto_detect_input_dir()
            Console.info(f"自动检测到输入目录: {in_dir}")
        if not in_dir.exists() or not in_dir.is_dir():
            Console.error(f"输入目录不存在或不是目录: {in_dir}")
            return False

        if output_dir:
            out_dir = Path(output_dir)
        else:
            possible = [in_dir.parent / 'out', in_dir.parent / 'ans',
                        in_dir / 'out', in_dir / 'ans', in_dir]
            out_dir = None
            for p in possible:
                if p.exists() and p.is_dir():
                    out_dir = p
                    break
            if out_dir is None:
                Console.warn("未找到输出目录，将仅运行程序不比较（只显示输出）")

        timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 5))
        if memory_limit_mb is None:
            memory_limit_mb = self.config.get('oi.memory_limit_mb', 512)
        self._set_memory_limit_warn(memory_limit_mb)
        preexec = _get_memory_limit_preexec(memory_limit_mb)

        test_suite = self._load_cktest(cktest_file, in_dir)
        if test_suite is None:
            ck_file = in_dir / '.cktest'
            if ck_file.exists():
                test_suite = self._load_cktest(str(ck_file), in_dir)
        if test_suite is None:
            Console.info("未找到 .cktest 数据包，使用默认测试模式")
            return self._run_normal_test(exe, in_dir, out_dir, timeout_val, compare_exact,
                                         preexec, main_path)

        Console.info(f"加载数据包: {test_suite.get('name', 'unnamed')}，共 {len(test_suite.get('cases', []))} 个测试点")
        score_total = 0
        score_obtained = 0
        results = []
        total_time = 0.0
        max_mem = 0.0

        spj_cmd = None
        if 'checker' in test_suite:
            checker_path = Path(test_suite['checker'])
            if checker_path.exists():
                checker_handler = PluginRegistry.get_handler(checker_path.suffix)
                if checker_handler and isinstance(checker_handler, CompiledLanguageHandler):
                    Console.info(f"编译 SPJ: {checker_path}")
                    ok, err = checker_handler.compile(checker_path)
                    if ok:
                        spj_exe = checker_path.with_suffix(EXE_SUFFIX)
                        if spj_exe.exists():
                            spj_cmd = [str(spj_exe)]
                    else:
                        Console.warn("SPJ 编译失败，回退到普通比较")
                else:
                    Console.warn("SPJ 文件类型不支持，回退到普通比较")
            else:
                Console.warn(f"SPJ 检查器 {checker_path} 不存在，回退到普通比较")

        for case in test_suite.get('cases', []):
            case_name = case.get('name', f"Case {case.get('id', '?')}")
            input_file = in_dir / case.get('input', '')
            if not input_file.exists():
                Console.warn(f"输入文件 {input_file} 不存在，跳过")
                continue
            expected_file = None
            if 'output' in case and out_dir:
                expected_file = out_dir / case['output']
            elif out_dir:
                base = input_file.stem
                for ext in ['.out', '.ans']:
                    cand = out_dir / f"{base}{ext}"
                    if cand.exists():
                        expected_file = cand
                        break

            temp_out = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False)
            temp_out_name = temp_out.name
            temp_out.close()
            start_time = time.time()
            err_msg = ''
            status = 'OK'
            output = ''
            expected_val = None
            proc = None
            elapsed = 0.0
            try:
                with open(input_file, 'r', encoding='utf-8') as inf:
                    proc = sp.run([str(exe)], stdin=inf, stdout=open(temp_out_name, 'w'),
                                  stderr=sp.PIPE, text=True, timeout=timeout_val, check=False,
                                  preexec_fn=preexec)
                elapsed = time.time() - start_time
                if proc.returncode != 0:
                    status = 'RE'
                    output = ''
                    err_msg = proc.stderr or ''
                else:
                    with open(temp_out_name, 'r', encoding='utf-8') as f:
                        output = f.read().strip()
                    if spj_cmd is not None and expected_file and expected_file.exists():
                        spj_input = input_file.read_text(encoding='utf-8')
                        expected = expected_file.read_text(encoding='utf-8')
                        expected_val = expected
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as fin:
                            fin.write(spj_input)
                            fin_name = fin.name
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.out', delete=False) as fout:
                            fout.write(output)
                            fout_name = fout.name
                        with tempfile.NamedTemporaryFile(mode='w', suffix='.ans', delete=False) as fans:
                            fans.write(expected)
                            fans_name = fans.name
                        try:
                            ret_spj = safe_run(spj_cmd + [fin_name, fout_name, fans_name],
                                               check=False, timeout=timeout_val)
                            if ret_spj.returncode == 0:
                                status = 'AC'
                            else:
                                status = 'WA'
                        finally:
                            os.unlink(fin_name)
                            os.unlink(fout_name)
                            os.unlink(fans_name)
                    elif expected_file and expected_file.exists():
                        expected = expected_file.read_text(encoding='utf-8').strip()
                        expected_val = expected
                        if output == expected:
                            status = 'AC'
                        else:
                            status = 'WA'
                    else:
                        status = 'OK'
            except sp.TimeoutExpired:
                status = 'TLE'
                elapsed = timeout_val
                output = ''
                err_msg = 'Timeout'
            except Exception as e:
                status = 'ERROR'
                elapsed = 0.0
                output = ''
                err_msg = str(e)
            finally:
                try:
                    os.unlink(temp_out_name)
                except Exception:
                    pass

            mem_mb = 0.0

            case_score = case.get('score', 0)
            score_total += case_score
            if status == 'AC':
                score_obtained += case_score

            input_data = input_file.read_text(encoding='utf-8') if input_file.exists() else ''

            results.append({
                'name': case_name,
                'status': status,
                'time': elapsed,
                'memory': mem_mb,
                'score': case_score,
                'output': output,
                'expected': expected_val,
                'input': input_data,
                'err': err_msg,
            })

            if status == 'WA':
                try:
                    self.failure_lib.add_wa_failure(
                        main_path, input_data, output, expected_val or '',
                        error='WA (cktest)', source_type='test'
                    )
                except Exception as e:
                    Console.warn(f"归档 WA 失败: {e}")
            elif status == 'RE':
                try:
                    self.failure_lib.add_re_failure(
                        main_path, input_data, err_msg,
                        returncode=0, sanitizer='AddressSanitizer' in err_msg,
                        source_type='test'
                    )
                except Exception as e:
                    Console.warn(f"归档 RE 失败: {e}")

            if elapsed > total_time:
                total_time = elapsed
            if mem_mb > max_mem:
                max_mem = mem_mb

        Console.bold("\n" + "=" * 60)
        Console.bold("测试结果")
        Console.bold("=" * 60)
        for r in results:
            status_color = Color.GREEN if r['status'] == 'AC' else Color.RED if r['status'] in ('WA', 'RE', 'TLE') else Color.YELLOW
            status_str = Console._c(r['status'], status_color)
            time_str = f"{r['time']:.3f}s"
            mem_str = f"{r['memory']:.1f}MB" if r['memory'] > 0 else "N/A"
            score_str = f"{r['score']}" if r['score'] > 0 else ""
            line = f"{r['name']:<20} {status_str:<8} {time_str:<10} {mem_str:<12} {score_str}"
            if r['status'] == 'WA':
                line += Console._c(" ✗", Color.RED)
            elif r['status'] == 'AC':
                line += Console._c(" ✓", Color.GREEN)
            print(line)
            if r['status'] == 'WA' and r.get('expected') is not None:
                Console.info(f"  期望: {r['expected'][:100]}")
                Console.info(f"  输出: {r['output'][:100]}")
            elif r['status'] == 'RE':
                Console.error(f"  错误: {r.get('err', '')}")
        Console.bold("-" * 60)
        Console.info(f"总得分: {score_obtained}/{score_total}")
        Console.info(f"总耗时: {total_time:.3f}s")
        Console.info(f"最大内存: {max_mem:.1f}MB" if max_mem > 0 else "最大内存: N/A")
        return score_obtained == score_total

    def _load_cktest(self, cktest_file: str, in_dir: Path) -> Optional[Dict]:
        if not cktest_file:
            return None
        path = Path(cktest_file)
        if not path.exists():
            return None
        try:
            content = path.read_text(encoding='utf-8')
            if path.suffix.lower() in ('.yaml', '.yml') and yaml:
                data = yaml.safe_load(content)
            else:
                data = json.loads(content)
            if not isinstance(data, dict) or 'cases' not in data:
                Console.warn(".cktest 文件格式无效，缺少 'cases' 字段")
                return None
            for idx, case in enumerate(data.get('cases', [])):
                if 'id' not in case:
                    case['id'] = idx + 1
                if 'input' not in case:
                    case['input'] = f"{case.get('id', idx + 1)}.in"
                if 'score' not in case:
                    case['score'] = 0
            return data
        except Exception as e:
            Console.warn(f"加载 .cktest 失败: {e}")
            return None

    def _run_normal_test(self, exe: Path, in_dir: Path, out_dir: Optional[Path],
                         timeout: int, compare_exact: bool, preexec, main_path: Path) -> bool:
        input_files = sorted(in_dir.glob('*.in'))
        if not input_files:
            Console.error("输入目录中没有 .in 文件")
            return False

        passed = 0
        total = len(input_files)
        for in_file in input_files:
            base = in_file.stem
            expected_file = None
            candidates = []
            if out_dir:
                candidates.extend([out_dir / f"{base}.out", out_dir / f"{base}.ans"])
            candidates.extend([in_file.with_suffix('.out'), in_file.with_suffix('.ans')])
            for cand in candidates:
                if cand.exists():
                    expected_file = cand
                    break

            temp_out = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False)
            temp_out_name = temp_out.name
            temp_out.close()
            err_msg = ''
            try:
                with open(in_file, 'r', encoding='utf-8') as inf:
                    proc = sp.run([str(exe)], stdin=inf, stdout=open(temp_out_name, 'w'),
                                  stderr=sp.PIPE, text=True, timeout=timeout, check=False,
                                  preexec_fn=preexec)
                if proc.returncode != 0:
                    Console.error(f"{base}: 运行时错误 (返回码 {proc.returncode})")
                    if proc.stderr:
                        print(proc.stderr)
                    try:
                        input_data = in_file.read_text(encoding='utf-8')
                        self.failure_lib.add_re_failure(
                            main_path, input_data, proc.stderr or '',
                            returncode=proc.returncode,
                            sanitizer='AddressSanitizer' in (proc.stderr or ''),
                            source_type='test'
                        )
                    except Exception:
                        pass
                    continue
                with open(temp_out_name, 'r', encoding='utf-8') as f:
                    output = f.read().strip()
            except sp.TimeoutExpired:
                Console.error(f"{base}: 超时 (> {timeout}s)")
                continue
            except Exception as e:
                Console.error(f"{base}: 运行异常: {e}")
                continue
            finally:
                try:
                    os.unlink(temp_out_name)
                except Exception:
                    pass

            if expected_file is not None:
                try:
                    expected = expected_file.read_text(encoding='utf-8').strip()
                    if output == expected:
                        Console.success(f"{base}: AC")
                        passed += 1
                    else:
                        Console.error(f"{base}: WA")
                        Console.info(f"  输出: {output[:100]}")
                        Console.info(f"  期望: {expected[:100]}")
                        try:
                            input_data = in_file.read_text(encoding='utf-8')
                            self.failure_lib.add_wa_failure(
                                main_path, input_data, output, expected,
                                error='WA (批量测试)', source_type='test'
                            )
                        except Exception:
                            pass
                except Exception as e:
                    Console.error(f"{base}: 读取期望输出失败: {e}")
            else:
                Console.info(f"{base}: 输出:\n{output}")

        Console.success(f"批量测试完成: {passed}/{total} 通过")
        return passed == total


class GenService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def generate(self, gen_file: str, cases: int = 1, output_prefix: str = None,
                 args: List[str] = None, seed: Optional[int] = None, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行以下数据生成:")
            Console.info(f"  生成器: {gen_file}")
            Console.info(f"  组数: {cases}")
            Console.info(f"  输出前缀: {output_prefix if output_prefix else 'data'}")
            Console.info(f"  种子: {seed if seed is not None else '随机'}")
            return True

        gen_path = Path(gen_file)
        if not gen_path.exists():
            Console.error(f"生成器文件不存在: {gen_file}")
            return False

        gen_suffix = gen_path.suffix.lower()
        if gen_suffix == '.py':
            interpreter = 'py' if shutil.which('py') else ('python' if shutil.which('python') else 'python3')
            gen_cmd = [interpreter, str(gen_path)]
        else:
            gen_handler = PluginRegistry.get_handler(gen_suffix)
            if gen_handler and isinstance(gen_handler, CompiledLanguageHandler):
                Console.info(f"编译生成器: {gen_file}")
                ok, err = gen_handler.compile(gen_path)
                if not ok:
                    Console.error("生成器编译失败")
                    return False
                gen_exe = gen_path.with_suffix(EXE_SUFFIX)
                if not gen_exe.exists():
                    Console.error("生成器可执行文件未生成")
                    return False
                gen_cmd = [str(gen_exe)]
            else:
                Console.error(f"生成器文件类型 {gen_suffix} 不支持，请使用 .py 或编译型语言")
                return False

        env = os.environ.copy()
        if seed is not None:
            env['CODEKIT_SEED'] = str(seed)
            Console.info(f"设置随机种子: {seed}")

        out_dir = Path.cwd() / 'data' / 'in'
        out_dir.mkdir(parents=True, exist_ok=True)
        if output_prefix is None:
            output_prefix = 'data'
        Console.info(f"生成 {cases} 组数据到 {out_dir}" + (f"，种子 {seed}" if seed is not None else ""))

        timeout_val = int(self.config.get('oi.timeout', 5))
        for i in range(1, cases + 1):
            out_file = out_dir / f"{output_prefix}{i:03d}.in"
            with open(out_file, 'w', encoding='utf-8') as f:
                try:
                    proc = sp.run(gen_cmd + (args or []),
                                  stdout=f, stderr=sp.PIPE, text=True,
                                  timeout=timeout_val, check=False, env=env)
                    if proc.returncode != 0:
                        Console.error(f"生成第 {i} 组数据失败: {proc.stderr}")
                        return False
                except sp.TimeoutExpired:
                    Console.error(f"生成器超时 (第 {i} 组)")
                    return False
        Console.success(f"成功生成 {cases} 组数据")
        return True


class TimeService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def time_run(self, file: str, args: List[str] = None, timeout: int = None,
                 flamegraph: bool = False, top: bool = False, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行计时/性能分析:")
            Console.info(f"  程序: {file}")
            Console.info(f"  参数: {args if args else '无'}")
            Console.info(f"  超时: {timeout if timeout else self.config.get('oi.timeout', 10)}s")
            Console.info(f"  火焰图: {flamegraph}")
            Console.info(f"  Top模式: {top}")
            return True

        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        handler = PluginRegistry.get_handler(path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {path.suffix}")
            return False

        if isinstance(handler, CompiledLanguageHandler):
            Console.info(f"编译: {file}")
            ok, err = handler.compile(path)
            if not ok:
                Console.error("编译失败")
                return False
            exe = path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("可执行文件未生成")
                return False
        else:
            exe = path

        timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 10))

        if top:
            if shutil.which('py-spy'):
                Console.info("运行 py-spy top (实时采样)...")
                cmd = ['py-spy', 'top', '--subprocesses', '--', str(exe)] + (args or [])
                try:
                    sp.run(cmd, timeout=timeout_val * 2)
                    return True
                except Exception as e:
                    Console.error(f"py-spy top 失败: {e}")
                    return False
            else:
                Console.info("py-spy 未安装，使用 cProfile 进行性能分析...")
                import cProfile
                import pstats
                import io as _io
                profiler = cProfile.Profile()
                try:
                    if isinstance(handler, CompiledLanguageHandler):
                        Console.warn("cProfile 只适用于 Python，对于编译型程序无法进行函数级分析，降级为计时")
                        return self._simple_time(exe, args, timeout_val)
                    else:
                        profiler.enable()
                        ret = safe_run([str(exe)] + (args or []), timeout=timeout_val, check=False)
                        profiler.disable()
                        stream = _io.StringIO()
                        ps = pstats.Stats(profiler, stream=stream).sort_stats('cumtime')
                        ps.print_stats(10)
                        print(stream.getvalue())
                        return ret.returncode == 0
                except Exception as e:
                    Console.error(f"性能分析失败: {e}")
                    return False

        if flamegraph:
            if not shutil.which('py-spy'):
                Console.error("py-spy 未安装，请运行: pip install py-spy")
                return False
            output_svg = f"flamegraph_{path.stem}.svg"
            Console.info(f"生成火焰图到 {output_svg} ...")
            cmd = ['py-spy', 'record', '-o', output_svg, '--', str(exe)] + (args or [])
            ret = safe_run(cmd, timeout=timeout_val * 2)
            if ret.returncode == 0:
                Console.success(f"火焰图已生成: {output_svg}")
                return True
            else:
                Console.error("生成火焰图失败")
                return False

        return self._simple_time(exe, args, timeout_val)

    def _simple_time(self, exe: Path, args: List[str], timeout: int) -> bool:
        start_time = time.time()
        proc = None
        try:
            cmd = [str(exe)] + (args or [])
            proc = sp.Popen(cmd, stdin=sp.DEVNULL, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
            _register_popen(proc)
            try:
                stdout, stderr = proc.communicate(timeout=timeout)
            except sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                Console.error(f"程序超时 (> {timeout}s)")
                return False
            elapsed = time.time() - start_time
            retcode = proc.returncode

            mem_usage_mb = 0.0
            if sys.platform == 'win32' and psutil is not None:
                try:
                    p = psutil.Process(proc.pid)
                    mem_usage_mb = p.memory_info().peak_wset / (1024 * 1024)
                except Exception:
                    pass
            elif sys.platform in ('linux', 'darwin') and resource is not None:
                try:
                    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
                    mem_usage_mb = ru.ru_maxrss / 1024.0
                except Exception:
                    pass

            if retcode == 0:
                Console.success("程序运行成功")
            else:
                Console.error(f"程序返回码: {retcode}")
            Console.info(f"耗时: {elapsed:.3f}s")
            if mem_usage_mb > 0:
                Console.info(f"内存峰值: {mem_usage_mb:.2f} MB")
            else:
                Console.warn("无法获取内存信息（可能需要安装 psutil 或使用 Linux）")
            if stdout:
                print(stdout)
            if stderr:
                print(stderr, file=sys.stderr)
            return retcode == 0
        except Exception as e:
            Console.error(f"运行失败: {e}")
            return False
        finally:
            if proc is not None:
                _unregister_popen(proc)

    def measure(self, file: str, args: List[str] = None, timeout: int = None) -> Tuple[int, float, float, str, str]:
        path = Path(file)
        if not path.exists():
            raise FileNotFoundError(f"文件不存在: {file}")
        handler = PluginRegistry.get_handler(path.suffix)
        if not handler:
            raise ValueError(f"不支持的文件类型: {path.suffix}")

        if isinstance(handler, CompiledLanguageHandler):
            ok, err = handler.compile(path)
            if not ok:
                raise RuntimeError("编译失败")
            exe = path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                raise RuntimeError("可执行文件未生成")
            cmd_prefix = [str(exe)]
        else:
            if isinstance(handler, PythonHandler):
                interpreter = 'py' if shutil.which('py') else ('python' if shutil.which('python') else 'python3')
                cmd_prefix = [interpreter, str(path)]
            else:
                cmd_prefix = [str(path)]
            exe = path

        timeout_val = timeout if timeout is not None else int(self.config.get('oi.timeout', 10))
        start_time = time.time()
        proc = None
        try:
            cmd = cmd_prefix + (args or [])
            proc = sp.Popen(cmd, stdin=sp.DEVNULL, stdout=sp.PIPE, stderr=sp.PIPE, text=True)
            _register_popen(proc)

            try:
                stdout, stderr = proc.communicate(timeout=timeout_val)
            except sp.TimeoutExpired:
                try:
                    proc.kill()
                except Exception:
                    pass
                raise TimeoutError(f"程序超时 (> {timeout_val}s)")
            elapsed = time.time() - start_time
            retcode = proc.returncode

            mem_usage_mb = 0.0
            if sys.platform == 'win32' and psutil is not None:
                try:
                    p = psutil.Process(proc.pid)
                    mem_usage_mb = p.memory_info().peak_wset / (1024 * 1024)
                except Exception:
                    pass
            elif sys.platform in ('linux', 'darwin') and resource is not None:
                try:
                    ru = resource.getrusage(resource.RUSAGE_CHILDREN)
                    mem_usage_mb = ru.ru_maxrss / 1024.0
                except Exception:
                    pass
            return retcode, elapsed, mem_usage_mb, stdout, stderr
        except TimeoutError:
            raise
        except Exception as e:
            raise RuntimeError(f"运行失败: {e}")
        finally:
            if proc is not None:
                _unregister_popen(proc)


# ======================== 算法模板速查服务 ========================
class SnippetService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.snippets_dir = Path(self.config.get('snippets_dir', str(SNIPPETS_DIR)))
        self._ensure_dir()

    def _ensure_dir(self):
        self.snippets_dir.mkdir(parents=True, exist_ok=True)
        try:
            if not any(self.snippets_dir.iterdir()):
                self._init_builtin_snippets()
        except Exception:
            pass

    def _init_builtin_snippets(self):
        snippets = {
            'segtree': '''
// 线段树（区间求和，单点修改）
#include <bits/stdc++.h>
using namespace std;
const int MAXN = 100005;
int tree[4*MAXN], a[MAXN];

void build(int node, int l, int r) {
    if (l == r) { tree[node] = a[l]; return; }
    int mid = (l+r)/2;
    build(node*2, l, mid);
    build(node*2+1, mid+1, r);
    tree[node] = tree[node*2] + tree[node*2+1];
}

void update(int node, int l, int r, int pos, int val) {
    if (l == r) { tree[node] = val; return; }
    int mid = (l+r)/2;
    if (pos <= mid) update(node*2, l, mid, pos, val);
    else update(node*2+1, mid+1, r, pos, val);
    tree[node] = tree[node*2] + tree[node*2+1];
}

int query(int node, int l, int r, int ql, int qr) {
    if (ql <= l && r <= qr) return tree[node];
    int mid = (l+r)/2, res = 0;
    if (ql <= mid) res += query(node*2, l, mid, ql, qr);
    if (qr > mid) res += query(node*2+1, mid+1, r, ql, qr);
    return res;
}
''',
            'bit': '''
// 树状数组（单点修改，前缀和）
#include <bits/stdc++.h>
using namespace std;
const int MAXN = 100005;
int bit[MAXN], n;

void add(int idx, int val) {
    while (idx <= n) {
        bit[idx] += val;
        idx += idx & -idx;
    }
}

int sum(int idx) {
    int res = 0;
    while (idx > 0) {
        res += bit[idx];
        idx -= idx & -idx;
    }
    return res;
}

int query(int l, int r) {
    return sum(r) - sum(l-1);
}
''',
            'kmp': '''
// KMP 字符串匹配
#include <bits/stdc++.h>
using namespace std;

vector<int> prefix_function(const string& s) {
    int n = s.size();
    vector<int> pi(n);
    for (int i = 1; i < n; i++) {
        int j = pi[i-1];
        while (j > 0 && s[i] != s[j]) j = pi[j-1];
        if (s[i] == s[j]) j++;
        pi[i] = j;
    }
    return pi;
}

vector<int> kmp_match(const string& text, const string& pattern) {
    vector<int> pi = prefix_function(pattern);
    vector<int> matches;
    int j = 0;
    for (int i = 0; i < (int)text.size(); i++) {
        while (j > 0 && text[i] != pattern[j]) j = pi[j-1];
        if (text[i] == pattern[j]) j++;
        if (j == (int)pattern.size()) {
            matches.push_back(i - j + 1);
            j = pi[j-1];
        }
    }
    return matches;
}
''',
            'exgcd': '''
// 扩展欧几里得算法
#include <bits/stdc++.h>
using namespace std;
using ll = long long;

ll exgcd(ll a, ll b, ll &x, ll &y) {
    if (b == 0) { x = 1; y = 0; return a; }
    ll x1, y1;
    ll d = exgcd(b, a % b, x1, y1);
    x = y1;
    y = x1 - (a / b) * y1;
    return d;
}
''',
            'maxflow': '''
// Dinic 最大流
#include <bits/stdc++.h>
using namespace std;
struct Edge { int to, rev, cap; };
vector<vector<Edge>> g;
vector<int> level, iter;

void add_edge(int from, int to, int cap) {
    g[from].push_back({to, (int)g[to].size(), cap});
    g[to].push_back({from, (int)g[from].size()-1, 0});
}

bool bfs(int s, int t) {
    fill(level.begin(), level.end(), -1);
    queue<int> q;
    level[s] = 0; q.push(s);
    while (!q.empty()) {
        int v = q.front(); q.pop();
        for (auto &e : g[v]) {
            if (e.cap > 0 && level[e.to] < 0) {
                level[e.to] = level[v] + 1;
                q.push(e.to);
            }
        }
    }
    return level[t] >= 0;
}

int dfs(int v, int t, int f) {
    if (v == t) return f;
    for (int &i = iter[v]; i < (int)g[v].size(); i++) {
        Edge &e = g[v][i];
        if (e.cap > 0 && level[v] < level[e.to]) {
            int d = dfs(e.to, t, min(f, e.cap));
            if (d > 0) {
                e.cap -= d;
                g[e.to][e.rev].cap += d;
                return d;
            }
        }
    }
    return 0;
}

int max_flow(int s, int t, int n) {
    int flow = 0;
    level.resize(n); iter.resize(n);
    const int INF = 1e9;
    while (bfs(s, t)) {
        fill(iter.begin(), iter.end(), 0);
        int f;
        while ((f = dfs(s, t, INF)) > 0) {
            flow += f;
        }
    }
    return flow;
}
''',
            'dijkstra': '''
// 堆优化 Dijkstra
#include <bits/stdc++.h>
using namespace std;
using pii = pair<int, int>;
const int INF = 1e9;
vector<vector<pii>> g;
vector<int> dist;

void dijkstra(int s) {
    priority_queue<pii, vector<pii>, greater<pii>> pq;
    fill(dist.begin(), dist.end(), INF);
    dist[s] = 0;
    pq.push({0, s});
    while (!pq.empty()) {
        auto [d, u] = pq.top(); pq.pop();
        if (d != dist[u]) continue;
        for (auto [v, w] : g[u]) {
            if (dist[v] > dist[u] + w) {
                dist[v] = dist[u] + w;
                pq.push({dist[v], v});
            }
        }
    }
}
''',
            'floyd': '''
// Floyd-Warshall 全源最短路
#include <bits/stdc++.h>
using namespace std;
const int INF = 1e9;
int d[105][105];

void floyd(int n) {
    for (int k = 0; k < n; k++)
        for (int i = 0; i < n; i++)
            for (int j = 0; j < n; j++)
                if (d[i][k] + d[k][j] < d[i][j])
                    d[i][j] = d[i][k] + d[k][j];
}
''',
            'lca': '''
// 树上倍增 LCA
#include <bits/stdc++.h>
using namespace std;
const int MAXN = 100005;
const int LOG = 20;
vector<int> g[MAXN];
int up[MAXN][LOG], depth[MAXN];

void dfs(int u, int p) {
    up[u][0] = p;
    for (int i = 1; i < LOG; i++)
        up[u][i] = up[up[u][i-1]][i-1];
    for (int v : g[u]) {
        if (v == p) continue;
        depth[v] = depth[u] + 1;
        dfs(v, u);
    }
}

int lca(int u, int v) {
    if (depth[u] < depth[v]) swap(u, v);
    int diff = depth[u] - depth[v];
    for (int i = 0; i < LOG; i++)
        if (diff & (1 << i)) u = up[u][i];
    if (u == v) return u;
    for (int i = LOG-1; i >= 0; i--) {
        if (up[u][i] != up[v][i]) {
            u = up[u][i];
            v = up[v][i];
        }
    }
    return up[u][0];
}
''',
            'quick_pow': '''
// 快速幂 (模意义)
using ll = long long;
ll mod_pow(ll a, ll b, ll mod) {
    ll res = 1;
    while (b) {
        if (b & 1) res = res * a % mod;
        a = a * a % mod;
        b >>= 1;
    }
    return res;
}
''',
            'gcd': '''
// 最大公约数
int gcd(int a, int b) { return b == 0 ? a : gcd(b, a % b); }
''',
            'miller_rabin': '''
// Miller-Rabin 素数测试
#include <bits/stdc++.h>
using namespace std;
using ll = long long;
ll mod_mul(ll a, ll b, ll mod) {
    ll res = 0;
    while (b) {
        if (b & 1) res = (res + a) % mod;
        a = (a + a) % mod;
        b >>= 1;
    }
    return res;
}
ll mod_pow(ll a, ll d, ll mod) {
    ll res = 1;
    while (d) {
        if (d & 1) res = mod_mul(res, a, mod);
        a = mod_mul(a, a, mod);
        d >>= 1;
    }
    return res;
}
bool is_prime(ll n) {
    if (n < 2) return false;
    if (n % 2 == 0) return n == 2;
    ll d = n - 1, s = 0;
    while (d % 2 == 0) { d /= 2; s++; }
    for (ll a : {2, 3, 5, 7, 11, 13, 17, 19, 23, 29}) {
        if (a >= n) continue;
        ll x = mod_pow(a, d, n);
        if (x == 1 || x == n - 1) continue;
        bool cont = false;
        for (int r = 1; r < s; r++) {
            x = mod_mul(x, x, n);
            if (x == n - 1) { cont = true; break; }
        }
        if (cont) continue;
        return false;
    }
    return true;
}
'''
        }
        for name, code in snippets.items():
            fname = self.snippets_dir / f"{name}.txt"
            fname.write_text(code, encoding='utf-8')
        Console.debug(f"内置算法模板初始化完成，共 {len(snippets)} 个")

    def list_snippets(self) -> bool:
        self._ensure_dir()
        files = list(self.snippets_dir.glob('*.txt'))
        if not files:
            Console.info("没有找到任何算法模板")
            return True
        Console.bold("\n可用的算法模板:")
        for f in sorted(files):
            print(f"  {f.stem}")
        Console.info(f"\n共 {len(files)} 个模板")
        return True

    def add_from_file(self, file_path: str, name: Optional[str] = None) -> bool:
        """从外部文件导入模板到 snippets 目录。"""
        src = Path(file_path)
        if not src.exists() or not src.is_file():
            Console.error(f"文件不存在: {file_path}")
            return False
        self._ensure_dir()
        if not name:
            name = src.stem
        name = re.sub(r'[^\w\-.]+', '_', str(name)).strip('_')
        if not name:
            Console.error("无效的模板名称")
            return False
        dst = self.snippets_dir / f"{name}.txt"
        if dst.exists():
            ans = safe_input(f"模板 '{name}' 已存在，覆盖? (y/N): ")
            if ans.lower() != 'y':
                Console.info("取消导入")
                return True
        try:
            content = src.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            Console.error(f"读取文件失败: {e}")
            return False
        try:
            dst.write_text(content, encoding='utf-8')
            Console.success(f"模板已导入: {name} -> {dst}")
            return True
        except Exception as e:
            Console.error(f"写入模板失败: {e}")
            return False

    def get_snippet(self, name: str, output_file: str = None, insert: bool = False,
                    position: str = None, variables: Dict[str, str] = None) -> bool:
        self._ensure_dir()
        snippet_file = self.snippets_dir / f"{name}.txt"
        if not snippet_file.exists():
            Console.error(f"模板 '{name}' 不存在")
            return False
        content = snippet_file.read_text(encoding='utf-8')
        if variables is None:
            variables = {}
        author = self.config.get('oi.author', os.environ.get('USER', 'OIer'))
        variables.setdefault('AUTHOR', author)
        variables.setdefault('DATE', datetime.now().strftime('%Y-%m-%d'))
        variables.setdefault('YEAR', str(datetime.now().year))
        for key, val in variables.items():
            content = content.replace(f'{{{{ {key} }}}}', val).replace(f'{{{{{key}}}}}', val)

        if output_file:
            target = Path(output_file)
            if insert:
                if target.exists():
                    current = target.read_text(encoding='utf-8')
                    if position:
                        lines = current.splitlines()
                        new_lines = []
                        marker_line = None
                        for idx, line in enumerate(lines):
                            new_lines.append(line)
                            if position in line:
                                marker_line = idx
                                new_lines.append(content)
                        if marker_line is not None:
                            target.write_text('\n'.join(new_lines), encoding='utf-8')
                            Console.success(f"模板已插入到标记行 '{position}' 之后")
                            return True
                        else:
                            Console.warn(f"未找到标记行 '{position}'，追加到末尾")
                    target.write_text(current + "\n" + content, encoding='utf-8')
                    Console.success(f"模板已追加到 {output_file}")
                else:
                    target.write_text(content, encoding='utf-8')
                    Console.success(f"模板已写入 {output_file}")
            else:
                target.write_text(content, encoding='utf-8')
                Console.success(f"模板已写入 {output_file}")
        else:
            print(content)
        return True


# ======================== 竞赛模式服务 ========================
class ContestService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.contest_dir = Path(self.config.get('contest_dir', str(CONTEST_DIR)))
        self.contest_dir.mkdir(parents=True, exist_ok=True)

    def start(self, config_file: str, duration: int, dry_run: bool = False, cfg: Optional[str] = None) -> bool:
        conf_path = Path(cfg) if cfg else Path(config_file)
        if not conf_path.exists():
            Console.error(f"比赛配置文件不存在: {conf_path}")
            return False

        if dry_run:
            Console.info("[Dry-run] 将启动比赛:")
            Console.info(f"  配置文件: {conf_path}")
            Console.info(f"  时长: {duration}s")
            return True

        try:
            with open(conf_path, 'r', encoding='utf-8') as f:
                contest_conf = json.load(f)
        except Exception as e:
            Console.error(f"读取比赛配置失败: {e}")
            return False

        name = contest_conf.get('name', 'Unnamed Contest')
        scoring = contest_conf.get('scoring', 'oi').lower()
        if scoring not in ('oi', 'ioi', 'acm'):
            Console.warn(f"未知赛制 '{scoring}'，将使用 'oi'")
            scoring = 'oi'

        if 'duration' not in contest_conf and ('start_time' in contest_conf and 'end_time' in contest_conf):
            start = datetime.fromisoformat(contest_conf['start_time'])
            end = datetime.fromisoformat(contest_conf['end_time'])
            duration = int((end - start).total_seconds())
            if duration <= 0:
                Console.error("比赛结束时间必须晚于开始时间")
                return False
        elif 'duration' in contest_conf:
            duration = contest_conf['duration']
        else:
            Console.error("比赛配置缺少 duration 或 start_time/end_time")
            return False

        auto_submit = contest_conf.get('auto_submit', False)
        readonly_data = contest_conf.get('readonly_data', True)
        hash_check = contest_conf.get('hash_check', True)
        auto_backup = contest_conf.get('auto_backup', True)
        backup_path = Path(contest_conf.get('backup_path', './.contest_backups'))
        global_defaults = contest_conf.get('global', {})

        problems = contest_conf.get('problems', [])
        if not problems:
            Console.error("比赛配置中无题目列表")
            return False

        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        contest_record_dir = self.contest_dir / f"{name}_{ts}"
        contest_record_dir.mkdir(parents=True, exist_ok=True)
        snap_dir = contest_record_dir / 'snapshots'
        snap_dir.mkdir(exist_ok=True)

        (contest_record_dir / 'contest.json').write_text(json.dumps(contest_conf, indent=2, ensure_ascii=False), encoding='utf-8')

        Console.bold(f"比赛 '{name}' 启动，时长 {duration} 秒，赛制 {scoring.upper()}")
        Console.info(f"题目列表: {', '.join([p.get('name', f'P{i+1}') for i, p in enumerate(problems)])}")

        if auto_backup:
            backup_path.mkdir(parents=True, exist_ok=True)
            backup_ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_dir = backup_path / f"{name}_backup_{backup_ts}"
            backup_dir.mkdir()
            for prob in problems:
                src = Path(prob.get('src', ''))
                if src.exists():
                    shutil.copy2(src, backup_dir / src.name)
                cfg_path = Path(prob.get('config', ''))
                if cfg_path.exists():
                    shutil.copy2(cfg_path, backup_dir / cfg_path.name)
            Console.success(f"已备份到 {backup_dir}")

        data_dirs = set()
        for prob in problems:
            pcfg_path = Path(prob.get('config', ''))
            if pcfg_path.exists():
                try:
                    with open(pcfg_path, 'r', encoding='utf-8') as f:
                        pcfg = json.load(f)
                    in_dir = Path(pcfg.get('input_dir', 'data/in'))
                    if in_dir.exists():
                        data_dirs.add(in_dir)
                except Exception:
                    pass

        original_modes = {}
        if readonly_data:
            for d in data_dirs:
                for root, dirs, files in os.walk(d):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            original_modes[fp] = os.stat(fp).st_mode
                            os.chmod(fp, 0o444)
                        except Exception:
                            pass
            Console.info("数据目录已设为只读")

        hash_records = {}
        if hash_check:
            for d in data_dirs:
                for f in d.glob('*.in'):
                    try:
                        with open(f, 'rb') as fin:
                            h = hashlib.sha256(fin.read()).hexdigest()
                            hash_records[str(f)] = h
                    except Exception:
                        pass
            (contest_record_dir / 'hash_records.json').write_text(json.dumps(hash_records, indent=2), encoding='utf-8')
            Console.info(f"已记录 {len(hash_records)} 个输入文件的哈希")

        watch_files = []
        for prob in problems:
            src = prob.get('src')
            if src:
                watch_files.append(Path(src).resolve())

        if not watch_files:
            Console.warn("没有指定任何源文件，无法监控")
            if readonly_data:
                for fp, mode in original_modes.items():
                    try:
                        os.chmod(fp, mode)
                    except Exception:
                        pass
            return False

        stop_event = threading.Event()

        def watcher():
            last_mtime = {}
            while not stop_event.is_set():
                for f in watch_files:
                    if not f.exists():
                        continue
                    try:
                        mtime = f.stat().st_mtime
                        if mtime != last_mtime.get(f, 0):
                            content = f.read_text(encoding='utf-8', errors='ignore')
                            snap_file = snap_dir / f"{f.stem}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
                            snap_file.write_text(content, encoding='utf-8')
                            Console.info(f"快照已保存: {snap_file.name}")
                            last_mtime[f] = mtime
                    except Exception:
                        pass
                time.sleep(1)

        watcher_thread = threading.Thread(target=watcher, daemon=True)
        watcher_thread.start()

        try:
            for remaining in range(duration, 0, -1):
                if stop_event.is_set():
                    break
                mins, secs = divmod(remaining, 60)
                timer = f'{mins:02d}:{secs:02d}'
                print(f"\r倒计时: {timer}  ", end='')
                time.sleep(1)
        except KeyboardInterrupt:
            Console.info("\n比赛被用户中断")
            stop_event.set()
            watcher_thread.join(timeout=2)

        stop_event.set()
        watcher_thread.join(timeout=2)
        print()
        Console.success("比赛时间到！")

        self._evaluate_and_report(contest_record_dir, contest_conf, problems, global_defaults, scoring, auto_submit)

        if readonly_data:
            for fp, mode in original_modes.items():
                try:
                    os.chmod(fp, mode)
                except Exception:
                    pass
            Console.info("数据目录权限已恢复")

        return True

    def _evaluate_and_report(self, record_dir: Path, contest_conf: Dict, problems: List[Dict],
                             global_defaults: Dict, scoring: str, auto_submit: bool):
        snap_dir = record_dir / 'snapshots'
        if not snap_dir.exists():
            Console.warn("没有快照目录，无法评测")
            return

        judge = JudgeService(self.config)

        report_lines = []
        report_lines.append(f"比赛报告: {contest_conf.get('name', 'Unnamed')}")
        report_lines.append(f"生成时间: {datetime.now().isoformat()}")
        report_lines.append(f"赛制: {scoring.upper()}")
        report_lines.append("=" * 60)

        total_score = 0
        total_obtained = 0
        problem_results = []

        for idx, prob in enumerate(problems, 1):
            pid = prob.get('id', f'P{idx}')
            name = prob.get('name', f'Problem {idx}')
            src = prob.get('src', '')
            pcfg_path = Path(prob.get('config', ''))
            if not src or not pcfg_path.exists():
                Console.warn(f"题目 {pid} 配置或源文件缺失，跳过")
                continue

            try:
                with open(pcfg_path, 'r', encoding='utf-8') as f:
                    pcfg = json.load(f)
                for k, v in global_defaults.items():
                    if k not in pcfg:
                        pcfg[k] = v
            except Exception as e:
                Console.error(f"读取题目配置 {pcfg_path} 失败: {e}")
                continue

            snap_files = sorted(snap_dir.glob(f"{Path(src).stem}_*.txt"), key=lambda x: x.stat().st_mtime, reverse=True)
            if snap_files:
                final_src = snap_files[0]
                Console.info(f"题目 {pid} 使用最终快照: {final_src.name}")
                temp_src = record_dir / f"{Path(src).name}"
                shutil.copy2(final_src, temp_src)
                src_to_judge = str(temp_src)
            else:
                src_to_judge = src
                Console.warn(f"题目 {pid} 没有快照，使用原始源文件")

            Console.info(f"正在评测题目 {pid} ...")
            temp_cfg = record_dir / f"temp_{pid}_cfg.json"
            with open(temp_cfg, 'w', encoding='utf-8') as f:
                json.dump(pcfg, f, indent=2)

            try:
                result = judge.judge(
                    problem_config=str(temp_cfg),
                    source=src_to_judge,
                    output_dir=None,
                    html=False,
                    dry_run=False,
                    return_details=True,
                    scoring=scoring
                )
                if result['ok']:
                    Console.success(f"题目 {pid} 全部通过")
                else:
                    Console.warn(f"题目 {pid} 得分 {result['score']}/{result['total']}")
                problem_results.append({
                    'id': pid,
                    'score': result['score'],
                    'total': result['total']
                })
                total_score += result['total']
                total_obtained += result['score']
            except Exception as e:
                Console.error(f"评测题目 {pid} 失败: {e}")
                continue

        report_lines.append("\n题目得分:")
        for res in problem_results:
            report_lines.append(f"  {res['id']}: {res['score']}/{res['total']}")
        report_lines.append(f"\n总分: {total_obtained}/{total_score}")

        report_file = record_dir / 'report.txt'
        report_file.write_text('\n'.join(report_lines), encoding='utf-8')
        Console.success(f"报告已生成: {report_file}")

        if auto_submit:
            Console.info("自动提交模式开启，正在提交最终代码...")
            submit_service = SubmitService(self.config)
            for prob in problems:
                pid = prob.get('id', '')
                src = prob.get('src', '')
                if not src:
                    continue
                snap_files = sorted(snap_dir.glob(f"{Path(src).stem}_*.txt"), key=lambda x: x.stat().st_mtime, reverse=True)
                if snap_files:
                    final_src = snap_files[0]
                else:
                    final_src = Path(src)
                platform = contest_conf.get('platform', 'luogu')
                submit_service.submit(str(final_src), problem=pid, platform=platform,
                                      contest=None, language=None, fast=False, dry_run=False)
            Console.success("自动提交完成")


# ======================== 静态代码质量预检 (CheckService) ========================
class CheckService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def check(self, target: str = None) -> bool:
        target_path = Path(target) if target else Path.cwd()
        if target_path.is_dir():
            files = []
            for ext in ['.cpp', '.cxx', '.cc', '.c']:
                files.extend(target_path.rglob(f'*{ext}'))
        elif target_path.is_file():
            files = [target_path]
        else:
            Console.error(f"路径不存在: {target}")
            return False

        if not files:
            Console.info("未找到 C/C++ 文件")
            return True

        issues = []
        for f in files:
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                array_decl = re.findall(r'(\w+)\[(\d+)\]\s*;', content)
                for name, size in array_decl:
                    try:
                        if int(size) > self.config.get('check.array_size_warning', 100000):
                            issues.append(f"{f}: 数组 {name} 大小 {size} 可能过大")
                    except ValueError:
                        pass
                if self.config.get('check.int_overflow_warning', True):
                    int_mult = re.findall(r'int\s+\w+\s*=\s*(\w+)\s*\*\s*(\w+)', content)
                    for a, b in int_mult:
                        issues.append(f"{f}: int 乘法 {a}*{b} 可能溢出，考虑 long long")
                rec_funcs = re.findall(r'void\s+(\w+)\s*\([^)]*\)\s*\{[^}]*\1\s*\(', content, re.DOTALL)
                if rec_funcs:
                    issues.append(f"{f}: 发现递归函数 {', '.join(rec_funcs)}，注意栈深度")
                if 'ios::sync_with_stdio' not in content and 'cin' in content:
                    issues.append(f"{f}: 使用了 cin 但未关闭同步 (ios::sync_with_stdio(false))")
            except Exception as e:
                Console.warn(f"检查 {f} 时出错: {e}")

        if issues:
            Console.warn(f"发现 {len(issues)} 个潜在问题:")
            for issue in issues:
                Console.info(f"  - {issue}")
            return False
        else:
            Console.success("未发现常见问题")
            return True


# ======================== 在线评测数据包拉取 (FetchService) ========================
class FetchService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.cache_dir = Path(self.config.get('fetch.cache_dir', str(GLOBAL_CONFIG_DIR / 'cache' / 'fetch')))
        self.cache_dir.mkdir(parents=True, exist_ok=True)

    def fetch(self, problem_id: str, platform: str = 'luogu') -> bool:
        if requests is None:
            Console.error("requests 未安装，请运行: pip install requests")
            return False
        if platform == 'luogu':
            return self._fetch_luogu(problem_id)
        elif platform == 'codeforces':
            return self._fetch_codeforces(problem_id)
        elif platform == 'atcoder':
            return self._fetch_atcoder(problem_id)
        else:
            Console.error(f"不支持的平台: {platform}")
            return False

    def _fetch_luogu(self, pid: str) -> bool:
        url = f"https://www.luogu.com.cn/problem/{pid}"
        Console.info(f"从洛谷拉取: {url}")
        try:
            Console.warn("洛谷数据拉取需手动配置，请自行下载样例文件")
            api_url = f"https://www.luogu.com.cn/api/problem/{pid}"
            resp = requests.get(api_url, timeout=self.config.get('fetch.timeout', 10))
            if resp.status_code != 200:
                Console.error("拉取失败，请手动下载")
                return False
            data = resp.json()
            samples = data.get('data', {}).get('samples', [])
            if not samples:
                Console.warn("未找到样例")
                return False
            in_dir = Path.cwd() / 'data' / 'in'
            out_dir = Path.cwd() / 'data' / 'out'
            in_dir.mkdir(parents=True, exist_ok=True)
            out_dir.mkdir(parents=True, exist_ok=True)
            for i, sample in enumerate(samples, 1):
                if isinstance(sample, (list, tuple)) and len(sample) >= 2:
                    inp, out = sample[0], sample[1]
                else:
                    continue
                in_file = in_dir / f"{pid}_{i}.in"
                in_file.write_text(inp, encoding='utf-8')
                out_file = out_dir / f"{pid}_{i}.out"
                out_file.write_text(out, encoding='utf-8')
            Console.success(f"成功拉取 {len(samples)} 组样例")
            return True
        except Exception as e:
            Console.error(f"拉取失败: {e}")
            return False

    def _fetch_codeforces(self, pid: str) -> bool:
        Console.warn("Codeforces 数据拉取功能待实现，请手动下载")
        return False

    def _fetch_atcoder(self, pid: str) -> bool:
        Console.warn("AtCoder 数据拉取功能待实现，请手动下载")
        return False


# ======================== 剪贴板集成 (CopyService) ========================
class CopyService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def copy(self, file: str) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        try:
            content = path.read_text(encoding='utf-8')
        except Exception as e:
            Console.error(f"读取文件失败: {e}")
            return False

        cmd = None
        default = self.config.get('copy.default_command', 'auto')
        if default == 'auto':
            if sys.platform == 'win32':
                cmd = ['clip']
            elif sys.platform == 'darwin':
                cmd = ['pbcopy']
            else:
                if shutil.which('xclip'):
                    cmd = ['xclip', '-selection', 'c']
                elif shutil.which('xsel'):
                    cmd = ['xsel', '--clipboard', '--input']
                else:
                    Console.error("未找到剪贴板工具，请安装 xclip 或 xsel")
                    return False
        else:
            if default == 'clip':
                cmd = ['clip']
            elif default == 'pbcopy':
                cmd = ['pbcopy']
            elif default == 'xclip':
                cmd = ['xclip', '-selection', 'c']
            elif default == 'xsel':
                cmd = ['xsel', '--clipboard', '--input']
            else:
                Console.error(f"未知剪贴板命令: {default}")
                return False

        proc = None
        try:
            proc = sp.Popen(cmd, stdin=sp.PIPE, text=True)
            _register_popen(proc)
            proc.communicate(content)
            Console.success(f"已复制 {file} 到剪贴板")
            return True
        except Exception as e:
            Console.error(f"复制失败: {e}")
            return False
        finally:
            if proc is not None:
                _unregister_popen(proc)


# ======================== 代码提交 (SubmitService) ========================
class SubmitService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def _submit_single(self, file: str, problem: str, platform: str,
                       contest: Optional[str] = None, language: Optional[str] = None,
                       fast: bool = False, dry_run: bool = False) -> bool:
        if fast:
            oj_json = Path.cwd() / '.codekit-oj.json'
            if not oj_json.exists():
                Console.error("快速提交需要 .codekit-oj.json 文件，请创建并填写平台和题目")
                return False
            try:
                with open(oj_json, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                platform = data.get('platform', platform)
                problem = data.get('problem', problem)
                contest = data.get('contest', contest)
                language = data.get('language', language)
                if not problem:
                    Console.error(".codekit-oj.json 中缺少 'problem' 字段")
                    return False
                Console.info(f"从 .codekit-oj.json 读取: platform={platform}, problem={problem}")
            except Exception as e:
                Console.error(f"读取 .codekit-oj.json 失败: {e}")
                return False

        if not problem:
            Console.error("必须指定题目 ID (--problem)")
            return False

        if not shutil.which('oj'):
            Console.error("未找到 online-judge-tools (oj)，请安装: pip install online-judge-tools")
            return False

        if dry_run:
            Console.info("[Dry-run] 将提交代码:")
            Console.info(f"  文件: {file}")
            Console.info(f"  题目: {problem}")
            Console.info(f"  平台: {platform}")
            Console.info(f"  Contest: {contest if contest else '无'}")
            Console.info(f"  语言: {language if language else '自动'}")
            return True

        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False

        platform_config = self.config.get('submit.platforms', {})
        if platform not in platform_config:
            Console.error(f"不支持的平台: {platform}，支持: {', '.join(platform_config.keys())}")
            return False

        url_template = platform_config[platform].get('url_template', '')
        if not url_template:
            Console.error(f"平台 {platform} 未配置 URL 模板")
            return False

        url = url_template.format(problem=problem, contest=contest or '')
        if not url.startswith('http'):
            Console.error(f"生成的 URL 无效: {url}")
            return False

        if language is None:
            ext = path.suffix.lower()
            lang_map = platform_config[platform].get('language_map', {})
            default_map = {
                '.cpp': 'cpp',
                '.c': 'c',
                '.py': 'python',
                '.java': 'java',
                '.go': 'go',
                '.rs': 'rust',
                '.js': 'javascript',
                '.ts': 'typescript'
            }
            lang_map = {**default_map, **lang_map}
            language = lang_map.get(ext)
            if not language:
                Console.warn(f"无法识别文件类型 {ext}，默认使用 cpp")
                language = 'cpp'

        cmd = ['oj', 'submit', '--language', language, '--yes', url, str(path)]
        if not sys.stdout.isatty():
            cmd.append('--no-open')
        Console.info(f"提交命令: {' '.join(cmd)}")
        ret = safe_run(cmd)
        if ret.returncode != 0:
            Console.error("提交失败")
            if ret.stderr:
                print(ret.stderr)
            return False
        Console.success("提交成功")
        if ret.stdout:
            print(ret.stdout)
        return True

    def submit(self, file: str, problem: str = None, platform: str = 'luogu',
               contest: Optional[str] = None, language: Optional[str] = None,
               fast: bool = False, dry_run: bool = False, all: bool = False) -> bool:
        if all:
            json_path = Path.cwd() / 'submit-all.json'
            if not json_path.exists():
                Console.error("未找到 submit-all.json 文件")
                return False
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    entries = json.load(f)
            except Exception as e:
                Console.error(f"读取 submit-all.json 失败: {e}")
                return False
            if not isinstance(entries, list):
                Console.error("submit-all.json 必须是一个数组")
                return False
            success_count = 0
            for entry in entries:
                try:
                    f = entry['file']
                    p = entry['problem']
                    pl = entry.get('platform', platform)
                    c = entry.get('contest', contest)
                    lang = entry.get('language', language)
                    fast_flag = entry.get('fast', fast)
                    dry = entry.get('dry_run', dry_run)
                except KeyError as e:
                    Console.error(f"条目缺少键 {e}")
                    continue
                Console.info(f"批量提交: {f} -> {pl}/{p}")
                if self._submit_single(f, p, pl, contest=c, language=lang, fast=fast_flag, dry_run=dry):
                    success_count += 1
                else:
                    Console.warn(f"提交 {f} 失败")
            Console.success(f"批量提交完成，成功 {success_count}/{len(entries)}")
            return success_count == len(entries)
        else:
            return self._submit_single(file, problem, platform, contest, language, fast, dry_run)


# ======================== 性能回归检测 (BenchService) ========================
class BenchService:
    def __init__(self, config: ConfigManager, time_service: TimeService):
        self.config = config
        self.time_service = time_service
        self.default_baseline = Path.cwd() / config.get('bench.baseline_file', '.codekit-bench.json')
        self.history_file = Path.cwd() / config.get('bench.history_file', '.codekit-bench-history.json')

    def bench(self, file: str, args: Optional[List[str]] = None,
              timeout: Optional[int] = None, iterations: Optional[int] = None,
              save: bool = False, compare: bool = False,
              baseline_file: Optional[str] = None, dry_run: bool = False,
              track: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行性能回归检测:")
            Console.info(f"  程序: {file}")
            Console.info(f"  参数: {args if args else '无'}")
            Console.info(f"  迭代次数: {iterations if iterations else self.config.get('bench.iterations', 3)}")
            Console.info(f"  保存: {save}")
            Console.info(f"  比较: {compare}")
            Console.info(f"  Track: {track}")
            return True

        if track:
            return self._track(file, args, timeout)

        if iterations is None:
            iterations = self.config.get('bench.iterations', 3)
        if iterations < 1:
            iterations = 1

        if baseline_file:
            bench_path = Path(baseline_file)
        else:
            bench_path = self.default_baseline

        total_time = 0.0
        total_mem = 0.0
        success = 0
        for i in range(iterations):
            try:
                retcode, elapsed, mem, stdout, stderr = self.time_service.measure(file, args, timeout)
                if retcode != 0:
                    Console.warn(f"第 {i + 1} 次运行返回码 {retcode}，跳过")
                    continue
                total_time += elapsed
                total_mem += mem
                success += 1
            except Exception as e:
                Console.warn(f"第 {i + 1} 次运行失败: {e}")
                continue

        if success == 0:
            Console.error("所有运行均失败，无法进行基准测试")
            return False

        avg_time = total_time / success
        avg_mem = total_mem / success
        Console.info(f"平均耗时: {avg_time:.3f}s, 平均内存: {avg_mem:.2f}MB (基于 {success} 次成功运行)")

        if save:
            bench_data = {
                'file': str(Path(file).resolve()),
                'args': args or [],
                'timeout': timeout,
                'iterations': iterations,
                'avg_time': avg_time,
                'avg_mem': avg_mem,
                'timestamp': datetime.now().isoformat(),
                'success_count': success
            }
            try:
                bench_path.write_text(json.dumps(bench_data, indent=2), encoding='utf-8')
                Console.success(f"基准已保存到 {bench_path}")
                return True
            except Exception as e:
                Console.error(f"保存基准失败: {e}")
                return False

        if compare or bench_path.exists():
            if not bench_path.exists():
                Console.error("基准文件不存在，请先运行 --save 保存基准")
                return False
            try:
                with open(bench_path, 'r', encoding='utf-8') as f:
                    base = json.load(f)
            except Exception as e:
                Console.error(f"读取基准文件失败: {e}")
                return False

            base_time = base.get('avg_time', 0.0)
            base_mem = base.get('avg_mem', 0.0)
            if base_time == 0:
                Console.warn("基准时间无效，无法比较")
            else:
                time_change = (avg_time - base_time) / base_time * 100
                mem_change = (avg_mem - base_mem) / base_mem * 100 if base_mem > 0 else 0
                Console.bold("性能变化:")
                Console.info(f"  时间: {avg_time:.3f}s vs {base_time:.3f}s ({time_change:+.1f}%)")
                Console.info(f"  内存: {avg_mem:.2f}MB vs {base_mem:.2f}MB ({mem_change:+.1f}%)")
                threshold = self.config.get('bench.threshold_percent', 20.0)
                if time_change > threshold:
                    Console.warn(f"⚠️ 时间显著增加 (超过 {threshold}%)")
                if mem_change > threshold:
                    Console.warn(f"⚠️ 内存显著增加 (超过 {threshold}%)")
            return True
        else:
            Console.info("未找到基准，请使用 --save 保存当前结果为基准")
            return True

    def _track(self, file: str, args: Optional[List[str]] = None,
               timeout: Optional[int] = None) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"程序不存在: {file}")
            return False

        commit_hash = "unknown"
        try:
            ret = sp.run(['git', 'rev-parse', 'HEAD'], capture_output=True, text=True, timeout=5)
            if ret.returncode == 0:
                commit_hash = ret.stdout.strip()[:8]
        except Exception:
            pass

        if args is None:
            args = []

        iterations = self.config.get('bench.iterations', 3)
        total_time = 0.0
        total_mem = 0.0
        success = 0
        for i in range(iterations):
            try:
                retcode, elapsed, mem, stdout, stderr = self.time_service.measure(file, args, timeout)
                if retcode != 0:
                    Console.warn(f"第 {i + 1} 次运行返回码 {retcode}，跳过")
                    continue
                total_time += elapsed
                total_mem += mem
                success += 1
            except Exception as e:
                Console.warn(f"第 {i + 1} 次运行失败: {e}")
                continue

        if success == 0:
            Console.error("所有运行均失败，无法进行基准测试")
            return False

        avg_time = total_time / success
        avg_mem = total_mem / success
        Console.info(f"当前性能: 平均耗时 {avg_time:.3f}s, 平均内存 {avg_mem:.2f}MB (基于 {success} 次运行)")

        history = []
        if self.history_file.exists():
            try:
                with open(self.history_file, 'r', encoding='utf-8') as f:
                    history = json.load(f)
            except Exception:
                history = []

        record = {
            'timestamp': datetime.now().isoformat(),
            'commit': commit_hash,
            'file': str(path.resolve()),
            'args': args,
            'timeout': timeout,
            'avg_time': avg_time,
            'avg_mem': avg_mem,
            'iterations': success
        }
        history.append(record)

        if len(history) > 20:
            history = history[-20:]

        try:
            with open(self.history_file, 'w', encoding='utf-8') as f:
                json.dump(history, f, indent=2)
            Console.success(f"性能记录已保存到 {self.history_file}")
        except Exception as e:
            Console.error(f"保存历史记录失败: {e}")
            return False

        if len(history) >= 2:
            last = history[-2]
            last_time = last.get('avg_time', 0.0)
            last_mem = last.get('avg_mem', 0.0)
            if last_time > 0:
                time_change = (avg_time - last_time) / last_time * 100
                mem_change = (avg_mem - last_mem) / last_mem * 100 if last_mem > 0 else 0
                Console.bold("与上次记录比较:")
                Console.info(f"  时间: {avg_time:.3f}s vs {last_time:.3f}s ({time_change:+.1f}%)")
                Console.info(f"  内存: {avg_mem:.2f}MB vs {last_mem:.2f}MB ({mem_change:+.1f}%)")
                threshold = self.config.get('bench.threshold_percent', 20.0)
                if time_change > threshold:
                    Console.warn(f"⚠️ 时间显著增加 (超过 {threshold}%)，请检查代码修改")
                if mem_change > threshold:
                    Console.warn(f"⚠️ 内存显著增加 (超过 {threshold}%)")
        else:
            Console.info("这是第一次记录，暂无历史对比")

        return True


# ======================== 打开 OJ 题目 (OpenService) ========================
class OpenService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def open(self, problem_id: str, platform: str = 'luogu') -> bool:
        platform_config = self.config.get('submit.platforms', {})
        if platform not in platform_config:
            Console.error(f"不支持的平台: {platform}，支持: {', '.join(platform_config.keys())}")
            return False
        url_template = platform_config[platform].get('url_template', '')
        if not url_template:
            Console.error(f"平台 {platform} 未配置 URL 模板")
            return False
        if '{contest}' in url_template:
            parts = problem_id.split('/')
            if len(parts) == 2:
                contest, prob = parts
            else:
                m = re.match(r'(\d+)([A-Za-z]\d*)', problem_id)
                if m:
                    contest, prob = m.group(1), m.group(2)
                else:
                    Console.error(f"无法从 {problem_id} 解析 contest，请使用格式 'contest/problem'")
                    return False
            url = url_template.format(contest=contest, problem=prob)
        else:
            url = url_template.format(problem=problem_id)
        Console.info(f"正在打开: {url}")
        try:
            webbrowser.open(url)
            Console.success("已打开浏览器")
            return True
        except Exception as e:
            Console.error(f"打开失败: {e}")
            return False


# ======================== TODO 统计 (TodoService) ========================
class TodoService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.git_service = GitService(config)
        self.todo_file = Path.cwd() / '.codekit-todo.md'

    def todo(self, sort_by_date: bool = False, count: bool = False) -> bool:
        files = []
        for handler in PluginRegistry.get_all_handlers():
            for ext_str in handler.extensions:
                files.extend(Path.cwd().rglob(f'*{ext_str}'))
        exclude_dirs = {'.git', '__pycache__', 'node_modules', 'target', 'bin', 'obj', '.vs'}
        files = [f for f in files if not any(p in f.parts for p in exclude_dirs)]

        todo_items = []
        for f in files:
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                for lineno, line in enumerate(content.splitlines(), 1):
                    stripped = line.strip()
                    if stripped.startswith('// TODO') or stripped.startswith('# TODO') or '// TODO' in stripped or '# TODO' in stripped:
                        todo_items.append((f, lineno, line.strip(), 'TODO'))
                    elif stripped.startswith('// FIXME') or stripped.startswith('# FIXME') or '// FIXME' in stripped or '# FIXME' in stripped:
                        todo_items.append((f, lineno, line.strip(), 'FIXME'))
            except Exception:
                continue

        if not todo_items:
            Console.info("没有找到 TODO 或 FIXME 注释")
            return True

        if count:
            stats = {}
            for f, _, _, _ in todo_items:
                stats[f] = stats.get(f, 0) + 1
            Console.bold("\n每个文件的 TODO/FIXME 统计:")
            for f, cnt in sorted(stats.items(), key=lambda x: -x[1]):
                print(f"  {f}: {cnt}")
            return True

        if sort_by_date:
            Console.info("按 Git 提交时间排序（需要 Git）...")
            with_time = []
            for f, lineno, text, typ in todo_items:
                dt = self.git_service.get_commit_time(str(f))
                if dt is None:
                    dt = datetime.fromtimestamp(f.stat().st_mtime)
                with_time.append((dt, f, lineno, text, typ))
            with_time.sort(key=lambda x: x[0], reverse=True)
            Console.bold("\nTODO/FIXME 按提交时间排序（最新优先）:")
            for dt, f, lineno, text, typ in with_time:
                print(f"[{dt.strftime('%Y-%m-%d %H:%M')}] {f}:{lineno} {typ}: {text}")
        else:
            Console.bold("\nTODO/FIXME 列表:")
            for f, lineno, text, typ in todo_items:
                print(f"{f}:{lineno} {typ}: {text}")

        Console.info(f"\n共 {len(todo_items)} 项")
        return True

    def add_todo(self, text: str) -> bool:
        if not text:
            Console.error("请提供 TODO 内容")
            return False
        if not self.todo_file.exists():
            self.todo_file.write_text("# CodeKit TODO List\n\n", encoding='utf-8')
        with open(self.todo_file, 'a', encoding='utf-8') as f:
            f.write(f"- [ ] {text}  (添加于 {datetime.now().strftime('%Y-%m-%d %H:%M')})\n")
        Console.success(f"已添加 TODO: {text}")
        return True

    def list_todos(self) -> bool:
        if not self.todo_file.exists():
            Console.info("尚未创建任何 TODO 列表，使用 'ck todo --add \"...\"' 添加")
            return True
        content = self.todo_file.read_text(encoding='utf-8')
        print(content)
        return True


# ======================== ck where ========================
class WhereService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def where(self, symbol: str) -> bool:
        current_dir = Path.cwd()
        files = []
        for handler in PluginRegistry.get_all_handlers():
            for ext_str in handler.extensions:
                files.extend(current_dir.rglob(f'*{ext_str}'))
        exclude = {'.git', '__pycache__', 'node_modules', 'target', 'bin', 'obj'}
        files = [f for f in files if not any(p in f.parts for p in exclude)]

        definitions = []
        for f in files:
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                patterns = [
                    rf'^\s*(def|class|function|void|int|char|float|double|bool|auto|const)\s+{re.escape(symbol)}\s*[\(=;]',
                    rf'^\s*{re.escape(symbol)}\s*[\(=;]',
                ]
                found_in_file = False
                for pat in patterns:
                    for m in re.finditer(pat, content, re.MULTILINE):
                        line_start = content[:m.start()].count('\n') + 1
                        lines = content.splitlines()
                        line = lines[line_start - 1] if line_start <= len(lines) else ''
                        definitions.append((f, line_start, line))
                        found_in_file = True
                        break
                    if found_in_file:
                        break
            except Exception:
                continue

        if not definitions:
            Console.info(f"未找到符号 '{symbol}' 的定义")
            return False

        definitions.sort(key=lambda x: str(x[0]))

        Console.bold(f"找到 {len(definitions)} 个定义:")
        for f, line_no, line in definitions:
            print(f"  {f}:{line_no}: {line.strip()}")
        return True


# ======================== mood 管理 ========================
class MoodService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def set_mood(self, state: str) -> bool:
        self.config._raw['mood']['state'] = state
        self.config.save()
        Console.success(f"状态已设置为: {state}")
        return True

    def get_mood(self) -> str:
        state = self.config.get('mood.state', 'normal')
        Console.info(f"当前状态: {state}")
        return state

    def adjust_cases(self, requested_cases: int) -> int:
        state = self.get_mood()
        if state == 'tired':
            threshold = self.config.get('mood.tired_threshold_cases', 100)
            if requested_cases > threshold:
                adjusted = threshold
                Console.warn(f"状态为 tired，测试用例数从 {requested_cases} 调整为 {adjusted}")
                return adjusted
        return requested_cases


# ======================== ck ask ========================
class AskService:
    def __init__(self, config: ConfigManager, ai_service: AIService):
        self.config = config
        self.ai = ai_service

    def ask(self, question: str) -> bool:
        context_parts = []
        cwd = Path.cwd()
        context_parts.append(f"当前工作目录: {cwd}")
        try:
            files = sorted(cwd.glob('*'), key=lambda p: p.stat().st_mtime, reverse=True)[:10]
            file_list = "\n".join([f"  {f.name} (修改于 {datetime.fromtimestamp(f.stat().st_mtime).strftime('%Y-%m-%d %H:%M')})" for f in files if f.is_file()])
            context_parts.append(f"最近修改的文件:\n{file_list}")
        except Exception:
            pass
        try:
            hist_file = HOME / '.codekit_history'
            if hist_file.exists():
                with open(hist_file, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        last_cmd = lines[-1].strip()
                        context_parts.append(f"最近执行命令: {last_cmd}")
        except Exception:
            pass

        context = "\n".join(context_parts)
        prompt = f"用户的问题: {question}\n\n上下文信息:\n{context}\n\n请根据上下文帮助用户解决问题。"
        try:
            response = self.ai.generate(prompt, temperature=0.5, max_tokens=500, context_aware=True)
            print(Console._c("AI 回答:", Color.CYAN))
            print(response)
            return True
        except Exception as e:
            Console.error(f"AI 回答失败: {e}")
            return False


# ======================== ck timer ========================
class TimerService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def timer(self, duration_minutes: int = None) -> bool:
        if duration_minutes is None:
            duration_minutes = self.config.get('timer.default_duration', 25)
        duration_seconds = duration_minutes * 60
        Console.info(f"启动番茄钟，时长 {duration_minutes} 分钟（按 Ctrl+C 提前结束）")
        try:
            for remaining in range(duration_seconds, 0, -1):
                mins, secs = divmod(remaining, 60)
                print(f"\r⏳ {mins:02d}:{secs:02d}  ", end='')
                time.sleep(1)
            print()
            Console.success("番茄钟结束！")
            self._notify("番茄钟结束", f"已专注 {duration_minutes} 分钟，休息一下吧！")
        except KeyboardInterrupt:
            print()
            Console.info("番茄钟被中断")
            return True
        return True

    def _notify(self, title: str, message: str):
        if notification is not None:
            try:
                notification.notify(title=title, message=message, timeout=5)
            except Exception:
                pass
        else:
            print("\a")


# ======================== ck diff ========================
class DiffService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def diff(self, file1: str, file2: str, ignore_trailing_spaces: bool = False,
             ignore_blank_lines: bool = False) -> bool:
        p1 = Path(file1)
        p2 = Path(file2)
        if not p1.exists() or not p2.exists():
            Console.error("文件不存在")
            return False
        try:
            lines1 = p1.read_text(encoding='utf-8').splitlines()
            lines2 = p2.read_text(encoding='utf-8').splitlines()
        except Exception as e:
            Console.error(f"读取文件失败: {e}")
            return False

        if ignore_trailing_spaces:
            lines1 = [line.rstrip() for line in lines1]
            lines2 = [line.rstrip() for line in lines2]
        if ignore_blank_lines:
            lines1 = [line for line in lines1 if line.strip() != '']
            lines2 = [line for line in lines2 if line.strip() != '']

        diff = difflib.unified_diff(lines1, lines2, fromfile=file1, tofile=file2, lineterm='')
        diff_lines = list(diff)
        if diff_lines:
            Console.error("文件不同:")
            for line in diff_lines:
                if line.startswith('+'):
                    print(Console._c(line, Color.GREEN))
                elif line.startswith('-'):
                    print(Console._c(line, Color.RED))
                else:
                    print(line)
            return False
        else:
            Console.success("文件相同")
            return True


# ======================== 本地 OI 评测机 (JudgeService，v5.2 增强默认值) ========================
class JudgeService:
    def __init__(self, config: ConfigManager):
        self.config = config
        self.test_service = TestService(config)
        self.failure_lib = FailureLibrary(config)

    def judge(self, problem_config: Optional[str] = None, source: str = 'main.cpp',
              output_dir: Optional[str] = None, html: bool = False,
              dry_run: bool = False, return_details: bool = False,
              scoring: str = 'oi') -> Union[bool, Dict]:
        if dry_run:
            Console.info("[Dry-run] 将执行本地评测:")
            Console.info(f"  题目配置: {problem_config if problem_config else '.codekit-problem.json (缺失则自动检测)'}")
            Console.info(f"  源文件: {source}")
            Console.info(f"  输出目录: {output_dir if output_dir else '自动生成'}")
            Console.info(f"  导出 HTML: {html}")
            if return_details:
                return {'ok': True, 'score': 0, 'total': 0, 'details': []}
            return True

        # v5.2: 配置文件可缺失，缺省使用自动检测
        config_path = Path(problem_config) if problem_config else Path.cwd() / '.codekit-problem.json'
        problem: Dict[str, Any] = {}
        if config_path.exists():
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    problem = loaded
            except Exception as e:
                Console.error(f"读取题目配置失败: {e}")
                if return_details:
                    return {'ok': False, 'error': str(e)}
                return False
        else:
            Console.info(f"未找到题目配置文件 {config_path}，使用自动检测默认配置")

        # 应用默认值
        defaults = _auto_detect_problem_config()
        name = problem.get('name', defaults['name'])
        time_limit = problem.get('time_limit', defaults['time_limit'])
        memory_limit_mb = problem.get('memory_limit', defaults['memory_limit'])

        # 输入目录：优先使用配置，否则自动检测
        input_dir_raw = problem.get('input_dir') or self.config.get('oi.default_input_dir')
        if input_dir_raw:
            input_dir = Path(input_dir_raw)
        else:
            input_dir = _auto_detect_input_dir()
            Console.info(f"自动检测到输入目录: {input_dir}")

        # 子任务：若配置缺失，则根据输入目录自动生成
        subtasks = problem.get('subtasks')
        if not subtasks:
            in_files = sorted(input_dir.glob('*.in'))
            if not in_files:
                Console.error(f"输入目录 {input_dir} 中没有 .in 文件，且题目配置未提供 subtasks")
                if return_details:
                    return {'ok': False, 'error': 'no input files'}
                return False
            subtasks = [{
                'id': 'P1',
                'score': 100,
                'cases': [f.name for f in in_files],
            }]
            Console.info(f"自动生成子任务: {len(in_files)} 个测试点，总分 100")

        src_path = Path(source)
        if not src_path.exists():
            Console.error(f"源文件不存在: {src_path}")
            if return_details:
                return {'ok': False, 'error': 'source not found'}
            return False
        handler = PluginRegistry.get_handler(src_path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {src_path.suffix}")
            if return_details:
                return {'ok': False, 'error': 'unsupported file type'}
            return False
        if isinstance(handler, CompiledLanguageHandler):
            Console.info(f"编译: {src_path}")
            ok, err = handler.compile(src_path)
            if not ok:
                Console.error("编译失败")
                if return_details:
                    return {'ok': False, 'error': 'compile failed'}
                return False
            exe = src_path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("编译产物不存在")
                if return_details:
                    return {'ok': False, 'error': 'executable not found'}
                return False
        else:
            Console.error("评测目前仅支持编译型语言 (C/C++/Go/Rust 等)")
            if return_details:
                return {'ok': False, 'error': 'unsupported language'}
            return False

        if not input_dir.exists():
            Console.error(f"输入目录不存在: {input_dir}")
            if return_details:
                return {'ok': False, 'error': 'input dir missing'}
            return False
        if output_dir:
            out_dir = Path(output_dir)
        else:
            # 默认输出目录：优先同级 out，其次 ans，最后输入目录自身
            candidate = input_dir.parent / 'out'
            if candidate.exists() and candidate.is_dir():
                out_dir = candidate
            else:
                candidate2 = input_dir.parent / 'ans'
                if candidate2.exists() and candidate2.is_dir():
                    out_dir = candidate2
                else:
                    out_dir = input_dir
        out_dir.mkdir(parents=True, exist_ok=True)

        checker_cmd = None
        checker_path_str = problem.get('checker')
        if checker_path_str:
            checker_path = Path(checker_path_str)
            if checker_path.exists():
                checker_handler = PluginRegistry.get_handler(checker_path.suffix)
                if checker_handler and isinstance(checker_handler, CompiledLanguageHandler):
                    Console.info(f"编译 SPJ: {checker_path}")
                    ok, err = checker_handler.compile(checker_path)
                    if ok:
                        spj_exe = checker_path.with_suffix(EXE_SUFFIX)
                        if spj_exe.exists():
                            checker_cmd = [str(spj_exe)]
                    else:
                        Console.warn("SPJ 编译失败，回退到普通比较")
                else:
                    Console.warn("SPJ 文件类型不支持，回退到普通比较")
            else:
                Console.warn(f"SPJ 文件 {checker_path} 不存在，回退到普通比较")

        preexec = _get_memory_limit_preexec(memory_limit_mb)

        Console.bold(f"\n开始评测: {name}")
        Console.info(f"时间限制: {time_limit}s, 内存限制: {memory_limit_mb}MB")
        Console.info(f"子任务数: {len(subtasks)}")
        all_results = []
        total_score = 0
        obtained_score = 0

        for subtask in subtasks:
            sid = subtask.get('id', '?')
            score = subtask.get('score', 0)
            cases = subtask.get('cases', [])
            if not cases:
                Console.warn(f"子任务 {sid} 无测试点，跳过")
                continue
            Console.info(f"\n子任务 {sid} (分值 {score}): {len(cases)} 个测试点")

            subtask_ok = True
            subtask_results = []
            for case_file in cases:
                in_file = input_dir / case_file
                if not in_file.exists():
                    Console.error(f"输入文件不存在: {in_file}")
                    subtask_ok = False
                    break
                base = in_file.stem
                temp_out = tempfile.NamedTemporaryFile(mode='w+', suffix='.txt', delete=False)
                temp_out_name = temp_out.name
                temp_out.close()
                start_time = time.time()
                case_status = 'WA'
                case_time = 0.0
                case_mem = 0.0
                case_output = ''
                case_err = ''
                proc = None
                try:
                    with open(in_file, 'r', encoding='utf-8') as inf:
                        proc = sp.run([str(exe)], stdin=inf, stdout=open(temp_out_name, 'w'),
                                      stderr=sp.PIPE, text=True, timeout=time_limit, check=False,
                                      preexec_fn=preexec)
                    case_time = time.time() - start_time
                    if proc.returncode != 0:
                        case_status = 'RE'
                        case_output = ''
                        case_err = proc.stderr or ''
                    else:
                        with open(temp_out_name, 'r', encoding='utf-8') as f:
                            case_output = f.read().strip()
                        # v5.2: 答案文件多候选检测（out_dir / in_dir 都要找）
                        ans_candidates = [
                            out_dir / f"{base}.ans",
                            out_dir / f"{base}.out",
                            in_file.with_suffix('.ans'),
                            in_file.with_suffix('.out'),
                        ]
                        ans_file = None
                        for c in ans_candidates:
                            if c.exists():
                                ans_file = c
                                break
                        if checker_cmd is not None:
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.in', delete=False) as fin:
                                fin.write(in_file.read_text(encoding='utf-8'))
                                fin_name = fin.name
                            with tempfile.NamedTemporaryFile(mode='w', suffix='.out', delete=False) as fout:
                                fout.write(case_output)
                                fout_name = fout.name
                            if ans_file is not None:
                                expected = ans_file.read_text(encoding='utf-8').strip()
                                with tempfile.NamedTemporaryFile(mode='w', suffix='.ans', delete=False) as fans:
                                    fans.write(expected)
                                    fans_name = fans.name
                                try:
                                    ret_spj = safe_run(checker_cmd + [fin_name, fout_name, fans_name],
                                                       check=False, timeout=time_limit)
                                    case_status = 'AC' if ret_spj.returncode == 0 else 'WA'
                                finally:
                                    os.unlink(fin_name)
                                    os.unlink(fout_name)
                                    os.unlink(fans_name)
                            else:
                                Console.warn(f"未找到期望输出文件: {base}.ans，跳过比较")
                                case_status = 'OK'
                                os.unlink(fin_name)
                                os.unlink(fout_name)
                        else:
                            if ans_file is not None:
                                expected = ans_file.read_text(encoding='utf-8').strip()
                                case_status = 'AC' if case_output == expected else 'WA'
                            else:
                                Console.warn(f"未找到期望输出文件: {base}.ans，跳过比较")
                                case_status = 'OK'
                except sp.TimeoutExpired:
                    case_status = 'TLE'
                    case_time = time_limit
                    case_output = ''
                except Exception as e:
                    case_status = 'ERROR'
                    case_output = str(e)
                finally:
                    try:
                        os.unlink(temp_out_name)
                    except Exception:
                        pass

                case_result = {
                    'case': case_file,
                    'status': case_status,
                    'time': case_time,
                    'memory': case_mem,
                    'output': case_output[:200] if case_output else ''
                }
                subtask_results.append(case_result)
                if case_status != 'AC':
                    subtask_ok = False

                try:
                    input_data = in_file.read_text(encoding='utf-8')
                    if case_status == 'WA':
                        expected_val = ''
                        for c in (out_dir / f"{base}.ans",
                                  out_dir / f"{base}.out",
                                  in_file.with_suffix('.ans'),
                                  in_file.with_suffix('.out')):
                            if c.exists():
                                expected_val = c.read_text(encoding='utf-8').strip()
                                break
                        self.failure_lib.add_wa_failure(
                            src_path, input_data, case_output, expected_val,
                            error='WA (judge)', source_type='judge'
                        )
                    elif case_status == 'RE':
                        self.failure_lib.add_re_failure(
                            src_path, input_data, case_err or '',
                            returncode=0,
                            sanitizer='AddressSanitizer' in (case_err or ''),
                            source_type='judge'
                        )
                except Exception as e:
                    Console.debug(f"归档 judge 失败: {e}")

                status_color = Color.GREEN if case_status == 'AC' else Color.RED if case_status in ('WA', 'RE', 'TLE') else Color.YELLOW
                status_str = Console._c(case_status, status_color)
                print(f"  {case_file:<20} {status_str:<8} {case_time:.3f}s")

            subtask_obtained = 0
            if scoring == 'oi':
                if subtask_ok:
                    subtask_obtained = score
            elif scoring == 'ioi':
                case_score = score / len(cases) if cases else 0
                for cr in subtask_results:
                    if cr['status'] == 'AC':
                        subtask_obtained += case_score
                subtask_obtained = round(subtask_obtained, 2)
            elif scoring == 'acm':
                for cr in subtask_results:
                    if cr['status'] == 'AC':
                        subtask_obtained += 1
            else:
                if subtask_ok:
                    subtask_obtained = score

            total_score += score
            obtained_score += subtask_obtained

            all_results.append({
                'id': sid,
                'score': score,
                'obtained': subtask_obtained,
                'cases': subtask_results,
                'ok': subtask_ok
            })

            if subtask_ok:
                Console.success(f"子任务 {sid} 全部通过，获得 {subtask_obtained} 分")
            else:
                Console.warn(f"子任务 {sid} 未完全通过，得分 {subtask_obtained} 分")

        Console.bold("\n" + "=" * 60)
        Console.bold("评测结果汇总")
        Console.bold("=" * 60)
        Console.info(f"题目: {name}")
        Console.info(f"总得分: {obtained_score} / {total_score}")
        Console.info(f"通过子任务: {len([r for r in all_results if r['ok']])} / {len(all_results)}")

        print("\n子任务详情:")
        print(f"{'子任务':<10} {'分值':<8} {'得分':<8} {'状态'}")
        for r in all_results:
            status_str = 'AC' if r['ok'] else 'WA'
            color = Color.GREEN if status_str == 'AC' else Color.RED
            print(f"{r['id']:<10} {r['score']:<8} {r['obtained']:<8} {Console._c(status_str, color)}")

        if html:
            self._export_html(name, all_results, obtained_score, total_score, out_dir)

        if return_details:
            return {
                'ok': obtained_score == total_score,
                'score': obtained_score,
                'total': total_score,
                'details': all_results,
                'name': name
            }
        return obtained_score == total_score

    def _export_html(self, name: str, results: List[Dict], obtained: int, total: int, out_dir: Path):
        html_content = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8"><title>评测报告 - {name}</title>
<style>
body {{ font-family: 'Consolas', monospace; margin: 20px; background: #f8f9fa; }}
table {{ border-collapse: collapse; width: 100%; margin: 10px 0; }}
th, td {{ border: 1px solid #dee2e6; padding: 8px; text-align: center; }}
th {{ background: #343a40; color: white; }}
tr:nth-child(even) {{ background: #f2f2f2; }}
.ac {{ color: green; font-weight: bold; }}
.wa {{ color: red; font-weight: bold; }}
.tle {{ color: orange; font-weight: bold; }}
.re {{ color: purple; font-weight: bold; }}
.error {{ color: gray; }}
</style>
</head>
<body>
<h1>评测报告 - {name}</h1>
<h2>总得分: {obtained} / {total}</h2>
<h3>子任务详情</h3>
<table>
<tr><th>子任务</th><th>分值</th><th>得分</th><th>状态</th></tr>
"""
        for r in results:
            status_class = 'ac' if r['ok'] else 'wa'
            html_content += f"<tr><td>{r['id']}</td><td>{r['score']}</td><td>{r['obtained']}</td><td class='{status_class}'>{'AC' if r['ok'] else 'WA'}</td></tr>\n"
            html_content += "<tr><td colspan='4'><table><tr><th>测试点</th><th>状态</th><th>时间</th></tr>\n"
            for case in r['cases']:
                st = case['status']
                cls = st.lower()
                html_content += f"<tr><td>{case['case']}</td><td class='{cls}'>{st}</td><td>{case['time']:.3f}s</td></tr>\n"
            html_content += "</table></td></tr>\n"
        html_content += "</table></body></html>"

        report_path = out_dir / 'report.html'
        report_path.write_text(html_content, encoding='utf-8')
        Console.success(f"HTML 报告已导出: {report_path}")


# ======================== 静态分析 (ScanService) ========================
class ScanService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def scan(self, target: str = None) -> bool:
        target_path = Path(target) if target else Path.cwd()
        if target_path.is_dir():
            files = []
            for ext in ['.cpp', '.cxx', '.cc', '.c']:
                files.extend(target_path.rglob(f'*{ext}'))
        elif target_path.is_file():
            files = [target_path]
        else:
            Console.error(f"路径不存在: {target}")
            return False

        if not files:
            Console.info("未找到 C/C++ 文件")
            return True

        issues = []
        for f in files:
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                lines = content.splitlines()

                for i, line in enumerate(lines, 1):
                    match = re.search(r'(long\s+long)\s+(\w+)\s*=\s*(\w+)\s*\*\s*(\w+)\s*;', line)
                    if match:
                        var1, var2 = match.group(3), match.group(4)
                        issues.append({
                            'file': f,
                            'line': i,
                            'level': 'warning',
                            'msg': f"int 乘法 {var1} * {var2} 赋值给 long long，可能存在溢出风险，建议先转换为 long long"
                        })

                funcs = re.findall(r'(void|int|long long)\s+(\w+)\s*\([^)]*\)\s*\{([^}]*)\}', content, re.DOTALL)
                for ret_type, func_name, body in funcs:
                    if re.search(rf'\b{re.escape(func_name)}\s*\(', body):
                        if 'if' not in body.split(func_name, 1)[0]:
                            try:
                                line_num = content[:content.index(body)].count('\n') + 1
                            except ValueError:
                                line_num = 1
                            issues.append({
                                'file': f,
                                'line': line_num,
                                'level': 'error',
                                'msg': f"递归函数 {func_name} 未检测到终止条件，可能导致栈溢出"
                            })

                local_arrays = re.findall(r'(int|char|long long|double)\s+(\w+)\s*\[(\d+)\]\s*;', content)
                for dtype, name, size in local_arrays:
                    if int(size) > 100000:
                        try:
                            line_num = content[:content.index(f"{name}[{size}]")].count('\n') + 1
                        except ValueError:
                            line_num = 1
                        issues.append({
                            'file': f,
                            'line': line_num,
                            'level': 'warning',
                            'msg': f"局部数组 {name} 大小 {size} 过大，建议使用静态或堆分配"
                        })

                if re.search(r'#define\s+int\s+long\s+long', content):
                    issues.append({
                        'file': f,
                        'line': 1,
                        'level': 'warning',
                        'msg': "检测到 #define int long long，可能增加内存占用并导致 MLE，请谨慎使用"
                    })

            except Exception as e:
                Console.warn(f"扫描 {f} 时出错: {e}")

        if issues:
            Console.bold("\n" + "=" * 60)
            Console.bold("赛场避坑指南")
            Console.bold("=" * 60)
            for issue in issues:
                level_color = Color.RED if issue['level'] == 'error' else Color.YELLOW
                print(f"{issue['file']}:{issue['line']} [{Console._c(issue['level'], level_color)}] {issue['msg']}")
            Console.warn(f"\n共发现 {len(issues)} 个潜在问题，请逐一检查。")
            return False
        else:
            Console.success("未发现常见危险写法，代码质量良好。")
            return True


# ======================== 提交前防雷 (PolishService) ========================
class PolishService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def polish(self, source: str, output: Optional[str] = None,
               auto_confirm: bool = False, dry_run: bool = False,
               keep_fileio: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行代码抛光:")
            Console.info(f"  源文件: {source}")
            Console.info(f"  输出文件: {output if output else '自动生成'}")
            Console.info(f"  保留文件IO: {keep_fileio}")
            return True

        src_path = Path(source)
        if not src_path.exists():
            Console.error(f"源文件不存在: {source}")
            return False

        if output is None:
            stem = src_path.stem
            suffix = src_path.suffix
            output_path = src_path.parent / f"{stem}_polished{suffix}"
        else:
            output_path = Path(output)

        if output_path.exists():
            if not auto_confirm:
                ans = safe_input(f"输出文件 {output_path} 已存在，覆盖? (y/N): ")
                if ans.lower() != 'y':
                    Console.info("取消操作")
                    return True

        try:
            content = src_path.read_text(encoding='utf-8')
        except Exception as e:
            Console.error(f"读取源文件失败: {e}")
            return False

        modifications = []

        if not keep_fileio:
            def comment_freopen(line):
                if re.search(r'\bfreopen\s*\(', line) or re.search(r'\bfclose\s*\(', line):
                    if not line.strip().startswith('//'):
                        return '// ' + line
                return line
            lines = content.splitlines()
            new_lines = []
            for line in lines:
                new_line = comment_freopen(line)
                if new_line != line:
                    modifications.append("注释了 freopen/fclose")
                new_lines.append(new_line)
            content = '\n'.join(new_lines)
        else:
            Console.info("保留文件IO操作（未注释 freopen/fclose）")

        def is_debug_line(line):
            if re.search(r'\b(cerr|cout)\s*<<', line):
                if re.search(r'"(debug|DEBUG|Debug|dev|DEV)"', line):
                    return True
            return False
        new_lines = []
        for line in content.splitlines():
            if is_debug_line(line):
                modifications.append("删除调试输出行")
                continue
            new_lines.append(line)
        content = '\n'.join(new_lines)

        if re.search(r'#define\s+int\s+long\s+long', content):
            Console.warn("检测到 #define int long long，可能导致 MLE")
            if not auto_confirm:
                ans = safe_input("是否替换为 using ll = long long; 并删除宏? (y/N): ")
            else:
                ans = 'y'
            if ans.lower() == 'y':
                content = re.sub(r'#define\s+int\s+long\s+long',
                                 '// #define int long long (已替换为 using ll = long long;)\nusing ll = long long;',
                                 content)
                modifications.append("替换 #define int long long")
            else:
                Console.info("保留 #define int long long")

        if 'main' in content:
            main_start = re.search(r'int\s+main\s*\([^)]*\)\s*\{', content)
            if main_start:
                main_body_start = main_start.end()
                brace_count = 0
                main_end = None
                for i, ch in enumerate(content[main_body_start:], start=main_body_start):
                    if ch == '{':
                        brace_count += 1
                    elif ch == '}':
                        brace_count -= 1
                    if brace_count == 0:
                        main_end = i
                        break
                if main_end is None:
                    main_end = len(content)
                main_body = content[main_body_start:main_end]
                if not re.search(r'return\s+[^;]*;', main_body):
                    content = content[:main_end] + '\n    return 0;\n' + content[main_end:]
                    modifications.append("添加 return 0;")

        try:
            output_path.write_text(content, encoding='utf-8')
            Console.success(f"抛光后的代码已保存到 {output_path}")
            if modifications:
                Console.bold("修改摘要:")
                for mod in set(modifications):
                    Console.info(f"  - {mod}")
            else:
                Console.info("未进行任何修改，代码已符合规范")
            return True
        except Exception as e:
            Console.error(f"写入输出文件失败: {e}")
            return False


# ======================== ck sample 服务 ========================
class SampleService:
    def __init__(self, config: ConfigManager):
        self.config = config

    def sample(self, main_file: Optional[str] = None, dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] 将执行样例测试")
            return True

        if main_file:
            src_path = Path(main_file)
            if not src_path.exists():
                Console.error(f"主程序文件不存在: {main_file}")
                return False
        else:
            candidates = []
            for ext in ['.cpp', '.c', '.py', '.java', '.go', '.rs']:
                for f in Path.cwd().glob(f'*{ext}'):
                    if f.stem in ['main', 'Main', 'index']:
                        candidates.append(f)
            if not candidates:
                for ext in ['.cpp', '.c', '.py']:
                    for f in Path.cwd().glob(f'*{ext}'):
                        candidates.append(f)
                        break
                    if candidates:
                        break
            if not candidates:
                Console.error("未找到主程序文件，请指定")
                return False
            src_path = candidates[0]
            Console.info(f"自动选择主程序: {src_path}")

        handler = PluginRegistry.get_handler(src_path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {src_path.suffix}")
            return False

        if isinstance(handler, CompiledLanguageHandler):
            Console.info(f"编译主程序: {src_path}")
            ok, err = handler.compile(src_path)
            if not ok:
                Console.error("编译失败")
                return False
            exe = src_path.with_suffix(EXE_SUFFIX)
            if not exe.exists():
                Console.error("可执行文件未生成")
                return False
            run_cmd = [str(exe)]
        elif isinstance(handler, PythonHandler):
            interpreter = 'py' if shutil.which('py') else ('python' if shutil.which('python') else 'python3')
            run_cmd = [interpreter, str(src_path)]
        else:
            Console.error(f"不支持的语言: {handler.name}")
            return False

        in_files = sorted(Path.cwd().glob('*.in'))
        if not in_files:
            Console.info("未发现样例，请手动 ck test")
            return True

        timeout_val = int(self.config.get('oi.timeout', 5))
        all_passed = True

        Console.bold(f"\n运行样例测试 (共 {len(in_files)} 个):")
        for idx, in_file in enumerate(in_files, 1):
            base = in_file.stem
            out_file = in_file.with_suffix('.out')
            ans_file = in_file.with_suffix('.ans')
            if out_file.exists():
                expected_file = out_file
            elif ans_file.exists():
                expected_file = ans_file
            else:
                Console.warn(f"样例 #{idx}: 未找到对应的 .out/.ans 文件，跳过")
                continue

            try:
                with open(in_file, 'r', encoding='utf-8') as fin:
                    proc = sp.run(run_cmd, stdin=fin, stdout=sp.PIPE, stderr=sp.PIPE,
                                  text=True, timeout=timeout_val, check=False)
                if proc.returncode != 0:
                    Console.error(f"样例 #{idx}: RE (返回码 {proc.returncode})")
                    if proc.stderr:
                        print(proc.stderr)
                    all_passed = False
                    continue
                output = proc.stdout.strip()
            except sp.TimeoutExpired:
                Console.error(f"样例 #{idx}: TLE (超时 {timeout_val}s)")
                all_passed = False
                continue
            except Exception as e:
                Console.error(f"样例 #{idx}: ERROR ({e})")
                all_passed = False
                continue

            expected = expected_file.read_text(encoding='utf-8').strip()
            if output == expected:
                Console.success(f"样例 #{idx}: AC ✓")
            else:
                Console.error(f"样例 #{idx}: WA ✗")
                Console.info(f"  期望: {expected[:200]}")
                Console.info(f"  输出: {output[:200]}")
                all_passed = False

        if all_passed:
            Console.success("\n所有样例通过")
        else:
            Console.warn("\n存在失败的样例")
        return all_passed


# ======================== 崩溃日志分析 (AnalLogService) ========================
class AnalLogService:
    """解析 ~/.codekit/logs/crash_*.log 崩溃日志。"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.log_dir = LOGS_DIR

    def list_logs(self) -> bool:
        if not self.log_dir.exists():
            Console.info("没有找到日志目录")
            return True
        files = sorted(self.log_dir.glob('crash_*.log'))
        if not files:
            Console.info("没有找到崩溃日志")
            return True
        Console.bold(f"\n共 {len(files)} 个崩溃日志:")
        for f in files:
            try:
                size = f.stat().st_size
                mtime = datetime.fromtimestamp(f.stat().st_mtime)
                print(f"  {f.name:<30} {size:>10} bytes  {mtime.strftime('%Y-%m-%d %H:%M:%S')}")
            except Exception:
                pass
        return True

    def parse_log(self, path: Path) -> List[Dict]:
        if not path.exists():
            return []
        try:
            content = path.read_text(encoding='utf-8', errors='replace')
        except Exception:
            return []
        entries = []
        blocks = re.split(r'={40,}\n', content)
        for block in blocks:
            block = block.strip()
            if not block:
                continue
            entry = {'raw': block}
            for line in block.splitlines():
                if line.startswith('Time: '):
                    entry['time'] = line[6:].strip()
                elif line.startswith('argv: '):
                    entry['argv'] = line[6:].strip()
                elif line.startswith('Python: '):
                    entry['python'] = line[8:].strip()
                elif line.startswith('Platform: '):
                    entry['platform'] = line[10:].strip()
                elif line.startswith('Exception: '):
                    entry['exception'] = line[11:].strip()
            if 'exception' in entry or 'time' in entry:
                entries.append(entry)
        return entries

    def anal_log(self, log_file: Optional[str] = None, today: bool = False,
                 list_flag: bool = False, tail: int = 0, summary: bool = False,
                 dry_run: bool = False) -> bool:
        if dry_run:
            Console.info("[Dry-run] anal_log 将解析崩溃日志")
            return True

        if list_flag:
            return self.list_logs()

        if log_file:
            log_path = Path(log_file).expanduser()
        else:
            log_path = self.log_dir / f"crash_{datetime.now().strftime('%Y%m%d')}.log"

        if not log_path.exists():
            Console.error(f"日志文件不存在: {log_path}")
            return False

        entries = self.parse_log(log_path)
        if not entries:
            Console.info(f"日志文件 {log_path} 中没有崩溃条目")
            return True

        if tail > 0:
            entries = entries[-tail:]

        if summary:
            Console.bold(f"\n日志统计: {log_path}")
            print(f"  崩溃条目数: {len(entries)}")
            exc_counter = {}
            for e in entries:
                exc = e.get('exception', '未知')
                exc_type = exc.split(':', 1)[0] if ':' in exc else exc
                exc_counter[exc_type] = exc_counter.get(exc_type, 0) + 1
            print("  异常类型分布:")
            for et, cnt in sorted(exc_counter.items(), key=lambda x: -x[1]):
                print(f"    {et}: {cnt}")
            if entries:
                print(f"  最新: {entries[-1].get('time', '?')}")
                print(f"  最早: {entries[0].get('time', '?')}")
            return True

        Console.bold(f"\n日志条目 ({len(entries)}):")
        for i, e in enumerate(entries):
            print(f"\n--- 条目 #{i + 1} ---")
            print(f"  时间: {e.get('time', '?')}")
            if e.get('argv'):
                print(f"  参数: {e.get('argv')}")
            if e.get('exception'):
                print(f"  异常: {e.get('exception')}")
            if e.get('python'):
                print(f"  Python: {e.get('python')}")
            if e.get('platform'):
                print(f"  平台: {e.get('platform')}")
            traceback_part = e.get('raw', '')
            if 'Traceback' in traceback_part:
                tb_start = traceback_part.find('Traceback')
                tb = traceback_part[tb_start:tb_start + 800]
                print(f"  追踪:\n{tb}")
        return True


# ======================== DI 容器 ========================
class Container:
    def __init__(self):
        self._services = {}

    def register(self, name: str, instance: Any):
        self._services[name] = instance

    def get(self, name: str) -> Any:
        return self._services.get(name)

    def __contains__(self, name: str) -> bool:
        return name in self._services


# ======================== 增强功能：watch 等辅助函数 ========================
try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    Observer = None
    FileSystemEventHandler = object


def _glob_to_regex(pattern: str) -> str:
    return re.escape(pattern).replace(r'\*', '.*').replace(r'\?', '.')


class WatchHandler(FileSystemEventHandler if FileSystemEventHandler is not object else object):
    def __init__(self, callback: Callable, exclude_patterns: List[str]):
        self.callback = callback
        self.exclude = []
        for pat in exclude_patterns:
            try:
                self.exclude.append(re.compile(_glob_to_regex(pat)))
            except re.error:
                continue

    def _should_ignore(self, path: str) -> bool:
        p = Path(path).name
        for pat in self.exclude:
            if pat.search(p) or pat.search(str(path)):
                return True
        return False

    def on_modified(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(event.src_path)

    def on_created(self, event):
        if not event.is_directory and not self._should_ignore(event.src_path):
            self.callback(event.src_path)


def watch_directory(path: str, callback: Callable, exclude: Optional[List[str]] = None,
                    use_polling: Optional[bool] = None, poll_interval: float = 1.0,
                    recursive: bool = True):
    target = Path(path).resolve()
    if not target.exists():
        raise FileNotFoundError(f'监控路径不存在: {target}')
    exclude = exclude or config.get('watch.exclude', DEFAULT_WATCH_EXCLUDE)
    if use_polling is None:
        use_polling = config.get('watch.use_polling', False)
    if poll_interval is None:
        poll_interval = config.get('watch.poll_interval', 1.0)

    if not use_polling and Observer is not None:
        event_handler = WatchHandler(callback, exclude)
        observer = Observer()
        observer.schedule(event_handler, str(target), recursive=recursive)
        observer.start()
        logger.info(f'监控启动 (watchdog): {target}')
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            observer.stop()
        observer.join()
    else:
        logger.info(f'监控启动 (轮询, 间隔 {poll_interval}s): {target}')
        last_mtimes: Dict[str, float] = {}
        exclude_re = []
        for p in exclude:
            try:
                exclude_re.append(re.compile(_glob_to_regex(p)))
            except re.error:
                continue

        def should_ignore(p: Path) -> bool:
            name = p.name
            for pat in exclude_re:
                if pat.search(name) or pat.search(str(p)):
                    return True
            return False

        def walk_scan(base: Path):
            result = {}
            try:
                with os.scandir(base) as it:
                    for entry in it:
                        if should_ignore(Path(entry.path)):
                            continue
                        if entry.is_file(follow_symlinks=False):
                            try:
                                mtime = entry.stat().st_mtime
                                result[entry.path] = mtime
                            except OSError:
                                continue
                        elif recursive and entry.is_dir(follow_symlinks=False):
                            result.update(walk_scan(Path(entry.path)))
            except PermissionError:
                pass
            return result

        try:
            while True:
                current = walk_scan(target)
                for fpath, mtime in current.items():
                    old = last_mtimes.get(fpath)
                    if old is None or mtime > old:
                        callback(fpath)
                last_mtimes = current
                time.sleep(poll_interval)
        except KeyboardInterrupt:
            pass


def launch_terminal(command: Optional[str] = None, terminal: Optional[str] = None,
                    working_dir: Optional[str] = None):
    terminal = terminal or config.get('terminal.default', 'auto')
    if terminal == 'auto':
        detect_order = config.get('terminal.detect_order', ['wezterm', 'alacritty', 'gnome-terminal', 'konsole', 'xfce4-terminal', 'xterm'])
        for t in detect_order:
            if shutil.which(t):
                terminal = t
                break
        else:
            terminal = config.get('terminal.fallback', 'xterm')
    if not command:
        command = os.environ.get('SHELL', '/bin/bash')
    if terminal == 'wezterm':
        cmd = ['wezterm', 'start', '--', command]
    elif terminal == 'alacritty':
        cmd = ['alacritty', '-e', command]
    elif terminal == 'gnome-terminal':
        cmd = ['gnome-terminal', '--', command]
    elif terminal == 'konsole':
        cmd = ['konsole', '-e', command]
    elif terminal == 'xfce4-terminal':
        cmd = ['xfce4-terminal', '-e', command]
    elif terminal == 'xterm':
        cmd = ['xterm', '-e', command]
    else:
        cmd = [terminal, '-e', command]
    if working_dir:
        if terminal == 'wezterm':
            cmd.insert(1, '--cwd')
            cmd.insert(2, working_dir)
        elif terminal == 'alacritty':
            cmd = ['alacritty', '--working-directory', working_dir, '-e', command]
        elif terminal == 'gnome-terminal':
            cmd = ['gnome-terminal', '--working-directory', working_dir, '--', command]
    logger.info(f'启动终端: {" ".join(cmd)}')
    sp.Popen(cmd, start_new_session=True, cwd=working_dir)


# ======================== CodeManager ========================
class CodeManager:
    def __init__(self, container: Container):
        self.container = container
        self.cfg = container.get('config') if 'config' in container else config
        self.ai_service = container.get('ai') if 'ai' in container else AIService(self.cfg)
        self.build_service = container.get('build') if 'build' in container else BuildService(self.cfg)
        self.dep_service = container.get('deps') if 'deps' in container else DependencyService(self.cfg)
        self.format_service = container.get('format') if 'format' in container else FormatService(self.cfg)
        self.search_service = container.get('search') if 'search' in container else SearchService(self.cfg)
        self.stats_service = container.get('stats') if 'stats' in container else StatsService(self.cfg)
        self.debug_service = container.get('debug') if 'debug' in container else DebugService(self.cfg)
        self.git_service = container.get('git') if 'git' in container else GitService(self.cfg)
        self.task_service = container.get('task') if 'task' in container else TaskService(self.cfg, self)
        if getattr(self.task_service, 'code_manager', None) is None:
            self.task_service.code_manager = self
        self.env_service = container.get('env') if 'env' in container else EnvService(self.cfg)
        self.lint_service = container.get('lint') if 'lint' in container else LintService(self.cfg)
        self.scaffold_service = container.get('scaffold') if 'scaffold' in container else ScaffoldService(self.cfg)
        self.checksum_service = container.get('checksum') if 'checksum' in container else ChecksumService(self.cfg)
        self.doctor_service = container.get('doctor') if 'doctor' in container else DoctorService(self.cfg)
        self.stress_service = container.get('stress') if 'stress' in container else StressService(self.cfg)
        self.test_service = container.get('test') if 'test' in container else TestService(self.cfg)
        self.gen_service = container.get('gen') if 'gen' in container else GenService(self.cfg)
        self.time_service = container.get('time') if 'time' in container else TimeService(self.cfg)
        self.snippet_service = container.get('snippet') if 'snippet' in container else SnippetService(self.cfg)
        self.contest_service = container.get('contest') if 'contest' in container else ContestService(self.cfg)
        self.check_service = container.get('check') if 'check' in container else CheckService(self.cfg)
        self.fetch_service = container.get('fetch') if 'fetch' in container else FetchService(self.cfg)
        self.copy_service = container.get('copy') if 'copy' in container else CopyService(self.cfg)
        self.submit_service = container.get('submit') if 'submit' in container else SubmitService(self.cfg)
        self.bench_service = container.get('bench') if 'bench' in container else BenchService(self.cfg, self.time_service)
        self.open_service = container.get('open') if 'open' in container else OpenService(self.cfg)
        self.todo_service = container.get('todo') if 'todo' in container else TodoService(self.cfg)
        self.where_service = container.get('where') if 'where' in container else WhereService(self.cfg)
        self.mood_service = container.get('mood') if 'mood' in container else MoodService(self.cfg)
        self.ask_service = container.get('ask') if 'ask' in container else AskService(self.cfg, self.ai_service)
        self.timer_service = container.get('timer') if 'timer' in container else TimerService(self.cfg)
        self.diff_service = container.get('diff') if 'diff' in container else DiffService(self.cfg)
        self.judge_service = container.get('judge') if 'judge' in container else JudgeService(self.cfg)
        self.scan_service = container.get('scan') if 'scan' in container else ScanService(self.cfg)
        self.polish_service = container.get('polish') if 'polish' in container else PolishService(self.cfg)
        self.sample_service = container.get('sample') if 'sample' in container else SampleService(self.cfg)
        self.failure_lib = container.get('failures') if 'failures' in container else FailureLibrary(self.cfg)
        self.import_service = container.get('import') if 'import' in container else ImportService(self.cfg)
        self.anal_log_service = container.get('anal_log') if 'anal_log' in container else AnalLogService(self.cfg)
        # v5.2 新增
        self.interact_service = container.get('interact') if 'interact' in container else InteractService(self.cfg)

        self._watch_observer = None
        CommandRegistry.load_external_commands()

    def _apply_command_format(self, args: List[str]) -> List[str]:
        if not args:
            return args
        cmd = args[0]
        fmt_list = self.cfg.get('CommandFormat', [])
        if not isinstance(fmt_list, list):
            return args
        fmt_dict = {}
        for item in fmt_list:
            if isinstance(item, dict) and '指令名' in item and '对应指令' in item:
                fmt_dict[item['指令名']] = item['对应指令']
        if cmd not in fmt_dict:
            return args
        template = fmt_dict[cmd]

        def repl(match):
            num = int(match.group(1))
            if num < len(args):
                return args[num]
            else:
                return ''

        new_cmd_str = re.sub(r'\$(\d+)', repl, template)
        try:
            new_args = shlex.split(new_cmd_str)
        except ValueError:
            new_args = new_cmd_str.split()
        return new_args

    def _dispatch_to_plugin(self, command: str, plugin,
                            remaining_args: Optional[List[str]] = None):
        if remaining_args is None:
            argv = sys.argv[1:]
            try:
                idx = argv.index(command)
            except ValueError:
                remaining_args = []
            else:
                remaining_args = argv[idx + 1:]
        parser = plugin.get_parser()
        try:
            parsed_plugin = parser.parse_args(remaining_args)
            return plugin.run(parsed_plugin, self)
        except SystemExit:
            return False
        except Exception as e:
            Console.error(f"命令插件 {command} 执行失败: {e}")
            if VERBOSE:
                traceback.print_exc()
            return False

    def dispatch_command(self, parsed_args):
        command = getattr(parsed_args, 'command', None)
        if command is None:
            Console.error("未指定命令")
            return False

        # 优先级: module_list > CommandFormat > Command
        if self.import_service.is_module_command(command):
            self.import_service.try_resolve_lazy_for(command)
            plugin = CommandRegistry.get_command(command)
            if plugin:
                remaining = getattr(parsed_args, '_remaining', None)
                return self._dispatch_to_plugin(command, plugin, remaining)

        if command == 'run':
            return self.run(parsed_args.file, parsed_args.version, getattr(parsed_args, 'std', None), parsed_args.args)
        elif command == 'compile':
            ok, _ = self.compile(parsed_args.file)
            return ok
        elif command == 'clean':
            return self.clean(getattr(parsed_args, 'dry_run', False), not getattr(parsed_args, 'no_confirm', False))
        elif command in ('list', 'ls'):
            return self.list_files(getattr(parsed_args, 'filter', None))
        elif command == 'search':
            return self.search_service.search_code(parsed_args.keyword)
        elif command == 'new':
            return self.new_file(parsed_args.file, is_plugin=getattr(parsed_args, 'plugin', False),
                                 is_command=getattr(parsed_args, 'command', False))
        elif command == 'backup':
            return self.backup(getattr(parsed_args, 'dst', None))
        elif command in ('restore', 'back'):
            return self.restore(parsed_args.src)
        elif command == 'git':
            return self.git_service.git(parsed_args.args if parsed_args.args else ['status'])
        elif command == 'watch':
            return self.watch(parsed_args.file,
                              test=parsed_args.test,
                              input_dir=getattr(parsed_args, 'input_dir', None),
                              output_dir=getattr(parsed_args, 'output_dir', None),
                              timeout=getattr(parsed_args, 'timeout', None),
                              cktest=getattr(parsed_args, 'cktest', None),
                              sanitize=getattr(parsed_args, 'sanitize', False),
                              memory_limit=getattr(parsed_args, 'memory_limit', None),
                              abackup=getattr(parsed_args, 'abackup', False),
                              nerror=getattr(parsed_args, 'nerror', False) or getattr(parsed_args, 'noteerror', False),
                              ai_explain=getattr(parsed_args, 'ai_explain', False))
        elif command == 'pyexe':
            return self.pack_py(parsed_args.file, parsed_args.opts)
        elif command == 'todll':
            return self.to_dll(parsed_args.file, parsed_args.output)
        elif command == 'chdir':
            return self.chdir(getattr(parsed_args, 'path', None))
        elif command == 'config':
            return self._config_action(parsed_args)
        elif command in ('shell', 'interactive'):
            return interactive_mode(self)
        elif command == 'build':
            return self.build_service.build()
        elif command == 'deps':
            if parsed_args.deps_action == 'check':
                return self.dep_service.check()
            elif parsed_args.deps_action == 'install':
                return self.dep_service.install()
            else:
                Console.error("请指定 deps 子命令: check 或 install")
                return False
        elif command == 'fmt':
            return self.format_service.format(parsed_args.target)
        elif command == 'grep':
            return self.search_service.grep(parsed_args.pattern, parsed_args.extra)
        elif command == 'def':
            return self.search_service.def_find(parsed_args.symbol)
        elif command == 'stats':
            return self.stats_service.stats(parsed_args.by_file)
        elif command == 'debug':
            return self.debug_service.debug(parsed_args.file, parsed_args.args)
        elif command == 'plugin':
            if parsed_args.plugin_action == 'list':
                return self.plugin_list()
            elif parsed_args.plugin_action == 'install':
                return self.plugin_install(parsed_args.name_or_url)
            elif parsed_args.plugin_action == 'reload':
                return self.plugin_reload()
            else:
                Console.error("请指定 plugin 子命令: list, install 或 reload")
                return False
        elif command == 'test':
            if getattr(parsed_args, 'gen', False):
                return self.test_gen(getattr(parsed_args, 'unit_file', None))
            else:
                return self.test_service.test(
                    parsed_args.file,
                    getattr(parsed_args, 'input_dir', None),
                    getattr(parsed_args, 'output_dir', None),
                    getattr(parsed_args, 'timeout', None),
                    getattr(parsed_args, 'exact', True),
                    getattr(parsed_args, 'cktest', None),
                    getattr(parsed_args, 'sanitize', False),
                    getattr(parsed_args, 'memory_limit', None),
                    getattr(parsed_args, 'dry_run', False)
                )
        elif command == 'terminal':
            return self.terminal()
        elif command == 'edit':
            return self.edit(parsed_args.file)
        elif command == 'task':
            return self.task_service.task(parsed_args.name, parsed_args.args)
        elif command == 'env':
            if parsed_args.env_action == 'save':
                return self.env_service.save_fingerprint()
            elif parsed_args.env_action == 'restore':
                return self.env_service.restore_fingerprint()
            elif parsed_args.env_action == 'list':
                return self.env_service.list_env()
            elif parsed_args.env_action == 'set':
                return self.env_service.set_env(parsed_args.key, parsed_args.value)
            elif parsed_args.env_action == 'check-g++':
                return self.env_service.check_gpp()
            else:
                Console.error("请指定 env 子命令: save, restore, list, set, check-g++")
                return False
        elif command == 'kill':
            return self.kill_process(parsed_args.pid)
        elif command == 'lint':
            return self.lint_service.lint()[0]
        elif command == 'init':
            return self.init_oi(parsed_args.lang)
        elif command == 'commit':
            return self.git_service.commit()
        elif command == 'checksum':
            return self.checksum_service.checksum(parsed_args.file, parsed_args.algo)
        elif command == 'freeze':
            return self.checksum_service.freeze()
        elif command == 'archive':
            return self.archive(parsed_args.format, parsed_args.output)
        elif command == 'explain':
            return self.explain(parsed_args.file, getattr(parsed_args, 'ask', None))
        elif command == 'fix':
            return self.fix(getattr(parsed_args, 'file', None))
        elif command == 'self-test':
            return self.self_test()
        elif command == 'failures':
            if parsed_args.failures_action == 'list':
                return self.failure_lib.list_command(type_filter=getattr(parsed_args, 'type', None))
            elif parsed_args.failures_action == 'show':
                return self.failure_lib.show_failure(parsed_args.id)
            elif parsed_args.failures_action == 'retry':
                return self.failure_lib.retry_failures(type_filter=getattr(parsed_args, 'type', None))
            else:
                Console.error("请指定 failures 子命令: list, show 或 retry")
                return False
        elif command == 'import':
            return self.import_service.import_command(
                parsed_args.modules,
                lazy=getattr(parsed_args, 'lazy', False),
                persistence=getattr(parsed_args, 'persistence', False),
                dry_run=getattr(parsed_args, 'dry_run', False)
            )
        elif command == 'stress':
            cases = parsed_args.cases
            if self.cfg.get('mood.state') == 'tired':
                cases = self.mood_service.adjust_cases(cases)
            return self.stress_service.stress(
                parsed_args.main,
                parsed_args.brute,
                parsed_args.gen,
                cases,
                getattr(parsed_args, 'timeout', None),
                getattr(parsed_args, 'gen_args', None),
                getattr(parsed_args, 'shrink', False),
                getattr(parsed_args, 'parallel', False),
                getattr(parsed_args, 'workers', 4),
                getattr(parsed_args, 'eps', None),
                getattr(parsed_args, 'sanitize', False),
                getattr(parsed_args, 'checker', None),
                getattr(parsed_args, 'celebrate', False),
                getattr(parsed_args, 'dry_run', False),
                auto_generate=getattr(parsed_args, 'auto', False),
                replay=getattr(parsed_args, 'replay', False)
            )
        elif command == 'time':
            return self.time_service.time_run(
                parsed_args.file,
                parsed_args.args,
                getattr(parsed_args, 'timeout', None),
                getattr(parsed_args, 'flamegraph', False),
                getattr(parsed_args, 'top', False),
                getattr(parsed_args, 'dry_run', False)
            )
        elif command == 'gen':
            return self.gen_service.generate(
                parsed_args.gen_file,
                parsed_args.cases,
                getattr(parsed_args, 'output_prefix', None),
                getattr(parsed_args, 'gen_args', None),
                getattr(parsed_args, 'seed', None),
                getattr(parsed_args, 'dry_run', False)
            )
        elif command == 'snippet':
            from_file = getattr(parsed_args, 'from_file', None)
            if from_file:
                return self.snippet_service.add_from_file(from_file, getattr(parsed_args, 'name', None))
            if parsed_args.snippet_action == 'list':
                return self.snippet_service.list_snippets()
            elif parsed_args.snippet_action == 'get':
                return self.snippet_service.get_snippet(
                    parsed_args.name,
                    getattr(parsed_args, 'output', None),
                    getattr(parsed_args, 'insert', False),
                    getattr(parsed_args, 'position', None),
                    {'AUTHOR': self.cfg.get('oi.author', os.environ.get('USER', 'OIer'))}
                )
            else:
                Console.error("请指定 snippet 子命令: list 或 get，或使用 --from-file 导入模板")
                return False
        elif command == 'contest':
            if parsed_args.contest_action == 'start':
                return self.contest_service.start(
                    getattr(parsed_args, 'config', 'contest.json'),
                    getattr(parsed_args, 'duration', 3600),
                    getattr(parsed_args, 'dry_run', False),
                    getattr(parsed_args, 'cfg', None)
                )
            else:
                Console.error("请指定 contest 子命令: start")
                return False
        elif command == 'check':
            return self.check_service.check(getattr(parsed_args, 'target', None))
        elif command == 'copy':
            return self.copy_service.copy(parsed_args.file)
        elif command == 'submit':
            return self.submit_service.submit(
                parsed_args.file,
                getattr(parsed_args, 'problem', None),
                getattr(parsed_args, 'platform', 'luogu'),
                getattr(parsed_args, 'contest', None),
                getattr(parsed_args, 'language', None),
                getattr(parsed_args, 'fast', False),
                getattr(parsed_args, 'dry_run', False),
                all=getattr(parsed_args, 'all', False)
            )
        elif command == 'bench':
            return self.bench_service.bench(
                parsed_args.file,
                getattr(parsed_args, 'args', None),
                getattr(parsed_args, 'timeout', None),
                getattr(parsed_args, 'iterations', None),
                getattr(parsed_args, 'save', False),
                getattr(parsed_args, 'compare', False),
                getattr(parsed_args, 'baseline', None),
                getattr(parsed_args, 'dry_run', False),
                track=getattr(parsed_args, 'track', False)
            )
        elif command == 'open':
            return self.open_service.open(parsed_args.problem, parsed_args.platform)
        elif command == 'todo':
            if getattr(parsed_args, 'add', None):
                return self.todo_service.add_todo(parsed_args.add)
            elif getattr(parsed_args, 'list', False):
                return self.todo_service.list_todos()
            else:
                return self.todo_service.todo(
                    getattr(parsed_args, 'sort_by_date', False),
                    getattr(parsed_args, 'count', False)
                )
        elif command == 'where':
            return self.where_service.where(parsed_args.symbol)
        elif command == 'mood':
            if parsed_args.mood_action == 'set':
                return self.mood_service.set_mood(parsed_args.state)
            elif parsed_args.mood_action == 'get':
                return self.mood_service.get_mood()
            else:
                Console.error("请指定 mood 子命令: set 或 get")
                return False
        elif command == 'ask':
            return self.ask_service.ask(parsed_args.question)
        elif command == 'timer':
            return self.timer_service.timer(getattr(parsed_args, 'minutes', None))
        elif command == 'cd':
            return self.chdir(parsed_args.path)
        elif command == 'diff':
            return self.diff_service.diff(
                parsed_args.file1,
                parsed_args.file2,
                getattr(parsed_args, 'ignore_trailing_spaces', False),
                getattr(parsed_args, 'ignore_blank_lines', False)
            )
        elif command == 'judge':
            fmt = getattr(parsed_args, 'format', 'text')
            return_details = (fmt == 'json')
            result = self.judge_service.judge(
                problem_config=getattr(parsed_args, 'problem_config', None),
                source=getattr(parsed_args, 'source', 'main.cpp'),
                output_dir=getattr(parsed_args, 'output_dir', None),
                html=getattr(parsed_args, 'html', False),
                dry_run=getattr(parsed_args, 'dry_run', False),
                return_details=return_details,
                scoring=self.cfg.get('contest.scoring', 'oi')
            )
            if fmt == 'json':
                try:
                    json_str = json.dumps(result, ensure_ascii=False, default=str)
                except Exception as e:
                    json_str = json.dumps({'ok': False, 'error': str(e)})
                try:
                    out = sys.__stdout__ if sys.__stdout__ is not None else sys.stdout
                    out.write(json_str + '\n')
                    out.flush()
                except Exception:
                    try:
                        print(json_str)
                    except Exception:
                        pass
                if isinstance(result, dict):
                    return bool(result.get('ok', False))
                return bool(result)
            return bool(result)
        elif command == 'scan':
            return self.scan_service.scan(getattr(parsed_args, 'target', None))
        elif command == 'polish':
            return self.polish_service.polish(
                parsed_args.file,
                getattr(parsed_args, 'output', None),
                getattr(parsed_args, 'yes', False),
                getattr(parsed_args, 'dry_run', False),
                keep_fileio=getattr(parsed_args, 'fileIO', False)
            )
        elif command == 'sample':
            return self.sample_service.sample(
                getattr(parsed_args, 'main', None),
                getattr(parsed_args, 'dry_run', False)
            )
        elif command == 'anal_log':
            return self.anal_log_service.anal_log(
                log_file=getattr(parsed_args, 'log_file', None),
                today=getattr(parsed_args, 'today', False),
                list_flag=getattr(parsed_args, 'list_flag', False),
                tail=getattr(parsed_args, 'tail', 0),
                summary=getattr(parsed_args, 'summary', False),
                dry_run=getattr(parsed_args, 'dry_run', False)
            )
        # ---------- v5.2 新增 ----------
        elif command == 'interact':
            return self.interact_service.interact(
                parsed_args.player,
                parsed_args.interactor,
                getattr(parsed_args, 'input', None),
                getattr(parsed_args, 'timeout', None),
                getattr(parsed_args, 'player_args', None),
                getattr(parsed_args, 'interactor_args', None),
                getattr(parsed_args, 'dry_run', False)
            )
        elif command == 'rip': # 纪念
            print("在此纪念fetch和upgrade字指令")
            print('fetch:享年12个小版本,死于v5.0,安葬于v5.1')
            print('upgrade:享年12个小版本,死于v5.0,安葬于v5.1')
            
            return True
        else:
            plugin = CommandRegistry.get_command(command)
            if plugin:
                return self._dispatch_to_plugin(command, plugin)
            else:
                Console.error(f"未知命令: {command}")
                return False

    # ---------- 核心方法 ----------
    def run(self, file: str, version: str = None, std: str = None, args: List[str] = None) -> bool:
        self.env_service.load_env()
        proj = BuildSystem.detect(Path.cwd())
        if proj and proj.get('run_cmd'):
            Console.info(f"检测到项目类型: {proj['type']}，执行 run 命令")
            ret = safe_run(proj['run_cmd'])
            return ret.returncode == 0
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        handler = PluginRegistry.get_handler(path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {path.suffix}")
            return False
        start = time.time()
        ok = handler.run(path, args or [], version)
        elapsed = time.time() - start
        Console.info(f"耗时: {elapsed:.3f}s")
        if ok and isinstance(handler, CompiledLanguageHandler):
            compiler = getattr(handler, 'compiler_cmd', None)
            if compiler and shutil.which(compiler):
                try:
                    proc = sp.run([compiler, '--version'], capture_output=True, text=True, timeout=5)
                    ver = proc.stdout.splitlines()[0] if proc.stdout else ''
                    self.doctor_service.record_successful_build(compiler, ver)
                except Exception:
                    pass
        return ok

    def compile(self, file: str, sanitize: bool = False) -> Tuple[bool, str]:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False, "文件不存在"
        handler = PluginRegistry.get_handler(path.suffix)
        if not handler:
            Console.error(f"不支持的文件类型: {path.suffix}")
            return False, "不支持的文件类型"
        ok, err = handler.compile(path, sanitize=sanitize)
        if ok and isinstance(handler, CompiledLanguageHandler):
            compiler = getattr(handler, 'compiler_cmd', None)
            if compiler and shutil.which(compiler):
                try:
                    proc = sp.run([compiler, '--version'], capture_output=True, text=True, timeout=5)
                    ver = proc.stdout.splitlines()[0] if proc.stdout else ''
                    self.doctor_service.record_successful_build(compiler, ver)
                except Exception:
                    pass
        return ok, err

    def clean(self, dry_run: bool = False, confirm: bool = True) -> bool:
        patterns = [
            '*.exe', '*.o', '*.obj', '*.class', '__pycache__', '*.pyc',
            'node_modules', '.cache', 'target',
            '*.dll', '*.lib', '*.so', 'bin', 'obj',
            '*.pdb', '*.ilk'
        ]
        current_dir = Path.cwd()
        to_remove = []
        for item in current_dir.iterdir():
            if item.is_dir():
                if item.name in {'node_modules', 'target', 'bin', 'obj', '__pycache__'}:
                    to_remove.append(item)
                    continue
            else:
                for pat in patterns:
                    if fnmatch.fnmatch(item.name, pat):
                        to_remove.append(item)
                        break
        if not to_remove:
            Console.info("没有需要清理的构建产物")
            return True
        Console.bold(f"将删除以下 {len(to_remove)} 项:")
        for r in to_remove:
            print(f"  {r}")
        if confirm:
            ans = safe_input(Console._c("确认删除? (y/N): ", Color.YELLOW))
            if ans.lower() != 'y':
                Console.info("取消清理")
                return True
        if dry_run:
            Console.info("试运行模式，未实际删除")
            return True
        errors = []
        for r in to_remove:
            try:
                if r.is_dir():
                    shutil.rmtree(r)
                else:
                    r.unlink()
                Console.success(f"已删除: {r}")
            except Exception as e:
                Console.error(f"删除失败 {r}: {e}")
                errors.append(str(r))
        if errors:
            Console.warn(f"清理过程中有 {len(errors)} 个错误")
            return False
        return True

    def ensure_templates(self):
        tpl_dir = Path(self.cfg.get('template_dir', str(GLOBAL_CONFIG_DIR / 'templates')))
        tpl_dir.mkdir(parents=True, exist_ok=True)
        templates = {
            '.cpp': '#include <bits/stdc++.h>\nusing namespace std;\n\nint main() {\n    ios::sync_with_stdio(false);\n    cin.tie(nullptr);\n    \n    return 0;\n}\n',
            '.c': '#include <stdio.h>\n\nint main() {\n    \n    return 0;\n}\n',
            '.java': 'public class Main {\n    public static void main(String[] args) {\n        \n    }\n}\n',
            '.py': '# -*- coding: utf-8 -*-\n\ndef main():\n    pass\n\nif __name__ == "__main__":\n    main()\n',
            '.go': 'package main\n\nimport "fmt"\n\nfunc main() {\n\tfmt.Println("Hello, World!")\n}\n',
            '.rs': 'fn main() {\n    println!("Hello, World!");\n}\n',
            '.ts': '// TypeScript entry point\nconsole.log("Hello, World!");\n',
            '.js': '// JavaScript entry point\nconsole.log("Hello, World!");\n',
            '.cs': 'using System;\n\nclass Program {\n    static void Main(string[] args) {\n        \n    }\n}\n',
            '.sh': '#!/bin/bash\n# Shell script template\n\necho "Hello, World!"\n',
            '.bat': '@echo off\n:: Batch file template\necho Hello, World!\n',
            '.dart': 'void main() {\n  print("Hello, World!");\n}\n',
            '.swift': 'import Foundation\n\nprint("Hello, World!")\n',
            '.rb': '# Ruby script\nputs "Hello, World!"\n',
        }
        for ext, content in templates.items():
            tpl = tpl_dir / f"_template{ext}"
            if not tpl.exists():
                tpl.write_text(content, encoding='utf-8')

    def new_file(self, file: str, is_plugin: bool = False, is_command: bool = False) -> bool:
        if is_command:
            return self._create_command_plugin(file)
        if is_plugin:
            return self._create_lang_plugin(file)
        path = Path(file)
        if path.exists():
            Console.error(f"文件已存在: {file}")
            return False
        self.ensure_templates()
        ext = path.suffix.lower()
        tpl_dir = Path(self.cfg.get('template_dir', str(GLOBAL_CONFIG_DIR / 'templates')))
        tpl = tpl_dir / f"_template{ext}"
        if tpl.exists():
            content = tpl.read_text(encoding='utf-8')
            path.write_text(content, encoding='utf-8')
            Console.success(f"已创建 (模板): {path}")
        else:
            path.touch()
            Console.success(f"已创建 (空文件): {path}")
        return True

    def _create_lang_plugin(self, plugin_name: str) -> bool:
        if not plugin_name.endswith('.py'):
            plugin_name += '.py'
        path = Path(plugin_name)
        if path.exists():
            Console.error(f"插件文件已存在: {path}")
            return False
        class_name = path.stem
        if not class_name[0].isupper():
            class_name = class_name.capitalize()
        content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义插件: {class_name}
"""
from CodeKit import LanguageHandler, Config, Console, Path, Optional, List, Tuple

class {class_name}(LanguageHandler):
    name = "{class_name}"
    extensions = []
    __deps__ = []

    def run(self, file: Path, args: List[str], version: str = None) -> bool:
        Console.info(f"Running {{self.name}} plugin on {{file}}")
        return True

    def compile(self, file: Path, sanitize: bool = False) -> Tuple[bool, str]:
        Console.warn(f"{{self.name}} 不支持编译")
        return False, "解释型语言无法编译"

    def clean(self, file: Optional[Path] = None) -> bool:
        Console.info(f"{{self.name}} 清理操作")
        return True

    def build(self, file: Optional[Path] = None) -> bool:
        Console.warn(f"{{self.name}} 不支持构建")
        return False

    def help(self) -> str:
        return f"自定义插件 {{self.name}}: 请参考源代码实现具体功能"

Handler = {class_name}
'''
        try:
            path.write_text(content, encoding='utf-8')
            Console.success(f"语言插件模板已创建: {path}")
            Console.info("请编辑该文件实现自定义逻辑，然后放入 ~/.codekit/plugins/ 目录。")
            return True
        except Exception as e:
            Console.error(f"创建插件模板失败: {e}")
            return False

    def _create_command_plugin(self, command_name: str) -> bool:
        if not command_name.endswith('.py'):
            command_name += '.py'
        path = Path(command_name)
        if path.exists():
            Console.error(f"命令插件文件已存在: {path}")
            return False
        class_name = path.stem.capitalize() + 'Command'
        content = f'''#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自定义命令插件: {class_name}
"""
import argparse
from CodeKit import CommandPlugin, CodeManager, Console, Path, config

class {class_name}(CommandPlugin):
    name = "{path.stem}"

    def get_parser(self) -> argparse.ArgumentParser:
        parser = argparse.ArgumentParser(prog=self.name, description="我的自定义命令")
        parser.add_argument('--message', '-m', default='Hello', help='要输出的消息')
        parser.add_argument('--count', '-c', type=int, default=1, help='重复次数')
        return parser

    def run(self, parsed_args: argparse.Namespace, code_manager: CodeManager) -> bool:
        for _ in range(parsed_args.count):
            Console.info(f"自定义命令输出: {{parsed_args.message}}")
        return True

    def check_dependencies(self) -> bool:
        return True
'''
        try:
            path.write_text(content, encoding='utf-8')
            Console.success(f"命令插件模板已创建: {path}")
            Console.info("请编辑该文件实现自定义命令，然后放入 ~/.codekit/commands/ 目录。")
            Console.info("之后即可使用 'ck <command_name>' 调用。")
            return True
        except Exception as e:
            Console.error(f"创建命令插件失败: {e}")
            return False

    def list_files(self, filter_ext: str = None):
        current_dir = Path.cwd()
        code_files = []
        for item in current_dir.iterdir():
            if item.is_file():
                handler = PluginRegistry.get_handler(item.suffix)
                if handler:
                    if filter_ext:
                        if filter_ext.startswith('.'):
                            ext = filter_ext.lower()
                        else:
                            ext = f".{filter_ext.lower()}"
                        if item.suffix.lower() != ext:
                            continue
                    code_files.append((item, handler.name))
        if not code_files:
            Console.info("当前目录没有代码文件")
            return
        groups = {}
        for f, name in code_files:
            groups.setdefault(name, []).append(f)
        Console.bold("\n📁 当前目录代码文件:")
        for lang_name, files in sorted(groups.items()):
            Console.bold(f"\n  [{lang_name}]")
            for f in files:
                size = f.stat().st_size
                size_str = f"{size}B" if size < 1024 else f"{size / 1024:.1f}KB"
                print(f"    {f.name:<30} {size_str:>8}")

    def backup(self, dst: str = None) -> bool:
        src = Path.cwd()
        if dst is None:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            dst = Path.home() / '.code_backups' / f"backup_{ts}"
        else:
            dst = Path(dst)
        dst.mkdir(parents=True, exist_ok=True)
        copied = 0
        errors = []
        skip_dirs = {'.git', '__pycache__', 'node_modules', '.code_backups', 'target', '.vs', 'bin', 'obj'}
        for item in src.iterdir():
            if item.name in skip_dirs:
                continue
            try:
                if item.is_dir():
                    shutil.copytree(item, dst / item.name,
                                    ignore=shutil.ignore_patterns('*.exe', '*.o', '__pycache__'))
                else:
                    shutil.copy2(item, dst)
                copied += 1
            except Exception as e:
                msg = f"跳过 {item.name}: {e}"
                Console.warn(msg)
                errors.append(msg)
        if errors:
            Console.warn(f"备份完成，但有 {len(errors)} 个警告/错误")
        else:
            Console.success(f"备份完成: {copied} 个项目 -> {dst}")
        return True

    def restore(self, src: str) -> bool:
        src = Path(src)
        if not src.exists():
            Console.error(f"备份路径不存在: {src}")
            return False
        dst = Path.cwd()
        restored = 0
        errors = []
        for item in src.iterdir():
            s = item
            d = dst / item.name
            try:
                if s.is_dir():
                    if d.exists():
                        shutil.rmtree(d)
                    shutil.copytree(s, d)
                else:
                    shutil.copy2(s, d)
                restored += 1
            except Exception as e:
                msg = f"跳过 {item.name}: {e}"
                Console.warn(msg)
                errors.append(msg)
        if errors:
            Console.warn(f"还原完成，但有 {len(errors)} 个警告/错误")
        else:
            Console.success(f"还原完成: {restored} 个项目 <- {src}")
        return True

    def watch(self, file: str, test: bool = False, input_dir: str = None,
              output_dir: str = None, timeout: int = None, cktest: str = None,
              sanitize: bool = False, memory_limit: int = None,
              abackup: bool = False, nerror: bool = False,
              ai_explain: bool = False) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False

        def handle_change():
            if nerror:
                Console.info("检查编译错误...")
                ok, err = self.compile(file, sanitize=sanitize)
                if not ok:
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    error_dir = Path.cwd() / f".CodeKit-OI-{ts}"
                    error_dir.mkdir(parents=True, exist_ok=True)
                    try:
                        shutil.copy2(path, error_dir / path.name)
                    except Exception:
                        pass
                    (error_dir / f"{path.stem}.err").write_text(err, encoding='utf-8')

                    ai_explanation = None
                    if ai_explain:
                        try:
                            Console.info("调用 AI 分析编译错误...")
                            ai_service = AIService(self.cfg)
                            try:
                                src_content = path.read_text(encoding='utf-8')
                            except Exception:
                                src_content = ''
                            prompt = (
                                "下面是一段 C/C++ 代码的编译错误，请解释错误原因并给出修复建议。\n\n"
                                f"编译错误：\n```\n{err}\n```\n\n"
                                f"源代码：\n```\n{src_content[:3000]}\n```\n\n"
                                "请用中文回答，包含：1) 错误定位；2) 错误原因；3) 修复方法。"
                            )
                            ai_explanation = ai_service.generate(
                                prompt, temperature=0.3, max_tokens=600, context_aware=False
                            )
                            (error_dir / 'ai.txt').write_text(ai_explanation, encoding='utf-8')
                            print(Console._c("AI 分析:", Color.CYAN))
                            print(ai_explanation)
                        except Exception as e:
                            Console.warn(f"AI 分析失败: {e}")

                    fid = self.failure_lib.add_compile_failure(
                        path, err, ai_explanation=ai_explanation
                    )
                    Console.error(f"编译错误已记录到 {error_dir}")
                    Console.info(f"统一失败库 ID: {fid}")
                    return False

            if abackup:
                ok, _ = self.compile(file, sanitize=sanitize)
                if ok:
                    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                    backup_name = f"{path.stem}_{timestamp}{path.suffix}"
                    backup_path = path.parent / backup_name
                    shutil.copy2(path, backup_path)
                    Console.success(f"备份已保存: {backup_path}")
                else:
                    Console.warn("编译失败，跳过备份")

            if test:
                ok, _ = self.compile(file, sanitize=sanitize)
                if ok:
                    self.test_service.test(
                        main_file=file,
                        input_dir=input_dir,
                        output_dir=output_dir,
                        timeout=timeout,
                        cktest_file=cktest,
                        sanitize=sanitize,
                        memory_limit_mb=memory_limit,
                        dry_run=False
                    )
                else:
                    Console.error("编译失败，跳过测试")
            else:
                self.run(str(path))
            return True

        if test:
            Console.info(f"进入 Watch + Test 模式 (Ctrl+C 退出): {file}")

            def on_change(fpath):
                if Path(fpath) == path:
                    print("\n" + Console._c("=" * 60, Color.YELLOW))
                    Console.info(f"检测到变化: {datetime.now().strftime('%H:%M:%S')}")
                    handle_change()

            try:
                watch_directory(str(path.parent), on_change,
                                use_polling=config.get('watch.use_polling', False),
                                poll_interval=config.get('watch.poll_interval', 1.0))
            except KeyboardInterrupt:
                Console.info("Watch 模式退出")
                return True
        else:
            Console.info(f"进入 Watch 模式 (Ctrl+C 退出): {file}")

            def on_change(fpath):
                if Path(fpath) == path:
                    print("\n" + Console._c("=" * 40, Color.YELLOW))
                    Console.info(f"检测到变化: {datetime.now().strftime('%H:%M:%S')}")
                    handle_change()

            try:
                watch_directory(str(path.parent), on_change,
                                use_polling=config.get('watch.use_polling', False),
                                poll_interval=config.get('watch.poll_interval', 1.0))
            except KeyboardInterrupt:
                Console.info("Watch 模式退出")
                return True
        return True

    def pack_py(self, file: str, opts: List[str]) -> bool:
        path = Path(file)
        if not path.exists() or path.suffix.lower() != '.py':
            Console.error("请提供 .py 文件")
            return False
        handler = PluginRegistry.get_handler('.py')
        if not handler:
            Console.error("未找到 Python 插件")
            return False
        return handler.pack(path, options=opts)

    def to_dll(self, file: str, output: str = None) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        ext = path.suffix.lower()
        if ext == '.cs':
            return self._cs_to_dll(path, output)
        elif ext in ('.cpp', '.cxx', '.cp', '.c++'):
            return self._cpp_to_dll(path, output)
        else:
            Console.error(f"不支持打包为 DLL 的类型: {ext}")
            return False

    def _cs_to_dll(self, file: Path, out_name: str = None) -> bool:
        if out_name is None:
            out_name = file.stem
        dll = Path(out_name).with_suffix('.dll')
        csc = shutil.which('csc')
        if csc:
            cmd = [csc, '/target:library', f'/out:{dll}', str(file)]
            Console.info(f"编译 C# DLL: {' '.join(cmd)}")
            ret = safe_run(cmd)
            if ret.returncode == 0:
                Console.success(f"DLL 生成: {dll}")
                return True
            Console.error("csc 编译失败")
            return False
        dotnet = shutil.which('dotnet')
        if dotnet:
            proj_dir = file.parent
            proj_name = file.stem
            proj_file = proj_dir / f"{proj_name}.csproj"
            created = False
            if not proj_file.exists():
                proj_file.write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <OutputType>Library</OutputType>
    <TargetFramework>net8.0</TargetFramework>
    <AssemblyName>{proj_name}</AssemblyName>
  </PropertyGroup>
</Project>''', encoding='utf-8')
                created = True
            try:
                cmd = ['dotnet', 'build', str(proj_dir), '-o', str(proj_dir)]
                Console.info(f"编译 C# DLL (dotnet): {' '.join(cmd)}")
                ret = safe_run(cmd)
                if ret.returncode == 0:
                    built = proj_dir / f"{proj_name}.dll"
                    if built.exists():
                        shutil.copy2(built, dll)
                        Console.success(f"DLL 生成: {dll}")
                        return True
                    Console.error("未找到生成的 DLL")
                    return False
                Console.error("dotnet build 失败")
                return False
            finally:
                if created and proj_file.exists():
                    proj_file.unlink()
                    for d in ['bin', 'obj']:
                        shutil.rmtree(proj_dir / d, ignore_errors=True)
        Console.error("未找到 C# 编译器")
        return False

    def _cpp_to_dll(self, file: Path, out_name: str = None) -> bool:
        if out_name is None:
            out_name = file.stem
        dll_ext = '.dll' if sys.platform == 'win32' else '.so'
        dll = Path(out_name).with_suffix(dll_ext)
        std = self.cfg.get('gcc_version', 'c++17')
        implib = None
        if sys.platform == 'win32':
            if shutil.which('g++'):
                implib = Path(out_name).with_suffix('.lib')
                cmd = ['g++', '-shared', '-fPIC', f'-std={std}', '-o', str(dll), str(file),
                       '-Wl,--out-implib,' + str(implib)]
            elif shutil.which('cl'):
                implib = Path(out_name).with_suffix('.lib')
                cmd = ['cl', '/EHsc', '/LD', f'/std:c++latest', str(file), f'/Fe:{dll}', f'/link /OUT:{implib}']
            else:
                Console.error("未找到 C++ 编译器，请安装 g++ 或 Visual Studio")
                return False
        else:
            cmd = ['g++', '-shared', '-fPIC', f'-std={std}', '-o', str(dll), str(file)]
        Console.info(f"编译 C++ DLL: {' '.join(cmd)}")
        ret = safe_run(cmd)
        if ret.returncode == 0:
            Console.success(f"DLL 生成: {dll}")
            if sys.platform == 'win32' and implib is not None and implib.exists():
                Console.info(f"导入库: {implib}")
            return True
        Console.error("编译失败")
        return False

    def chdir(self, path: str = None):
        if path is None:
            Console.info(f"当前工作目录: {Path.cwd()}")
            Console.info(f"配置的工作目录: {self.cfg.get('work_dir')}")
            return
        target = Path(path).resolve()
        if not target.exists():
            Console.error(f"目录不存在: {target}")
            return
        if not target.is_dir():
            Console.error(f"路径不是目录: {target}")
            return
        os.chdir(target)
        self.cfg._raw['work_dir'] = str(target)
        self.cfg.save()
        Console.success(f"工作目录已切换: {target}")

    def _config_action(self, args):
        if args.action == 'show' or args.action is None:
            Console.bold("\n⚙️  当前配置:")
            import pprint
            safe = copy.deepcopy(self.cfg._raw)
            if 'ai' in safe and 'api_key' in safe['ai'] and safe['ai']['api_key']:
                safe['ai']['api_key'] = '*****'
            pprint.pprint(safe)
        elif args.action == 'get':
            if not args.key:
                Console.error("请指定键名")
            else:
                val = self.cfg.get(args.key)
                print(f"{args.key} = {val}")
        elif args.action == 'set':
            if not args.key or args.value is None:
                Console.error("用法: config set <key> <value>")
            else:
                self.cfg._raw[args.key] = args.value
                self.cfg.save()
                Console.success(f"配置已更新: {args.key} = {args.value}")
        elif args.action == 'diff':
            self.cfg.diff()
        elif args.action == 'reload':
            self.cfg.reload()

    def plugin_list(self) -> bool:
        plugin_dir = Path(self.cfg.get('plugins.dir', str(PLUGINS_DIR)))
        if not plugin_dir.exists():
            Console.info("没有安装外部插件")
            return True
        Console.bold("\n已安装的外部插件:")
        for py_file in plugin_dir.glob('*.py'):
            print(f"  {py_file.name}")
        return True

    def plugin_install(self, name_or_url: str) -> bool:
        if name_or_url.startswith('http://') or name_or_url.startswith('https://'):
            return self._plugin_download_url(name_or_url)
        else:
            official_base = "https://raw.githubusercontent.com/CodeKit/plugins/main/"
            url = official_base + name_or_url + ".py"
            Console.info(f"尝试从官方源下载: {url}")
            return self._plugin_download_url(url)

    def _plugin_download_url(self, url: str) -> bool:
        plugin_dir = Path(self.cfg.get('plugins.dir', str(PLUGINS_DIR)))
        plugin_dir.mkdir(parents=True, exist_ok=True)
        filename = url.split('/')[-1]
        if not filename.endswith('.py'):
            Console.error("插件文件必须是 .py")
            return False
        target = plugin_dir / filename
        if target.exists():
            overwrite = safe_input(f"插件 {filename} 已存在，覆盖? (y/N): ").lower()
            if overwrite != 'y':
                Console.info("取消安装")
                return True
        try:
            Console.info(f"下载插件: {url}")
            urllib.request.urlretrieve(url, target)
            Console.success(f"插件下载成功: {target}")
            self.plugin_reload()
            return True
        except Exception as e:
            Console.error(f"下载插件失败: {e}")
            return False

    def plugin_reload(self) -> bool:
        PluginRegistry.reload_plugins()
        Console.success("插件已重载")
        return True

    def terminal(self) -> bool:
        launch_terminal(working_dir=str(Path.cwd()))
        return True

    def edit(self, file: str) -> bool:
        path = Path(file)
        if not path.exists():
            Console.error(f"文件不存在: {file}")
            return False
        if sys.platform == 'win32':
            try:
                os.startfile(str(path))
                return True
            except Exception as e:
                Console.error(f"打开文件失败: {e}")
                return False
        elif sys.platform == 'darwin':
            cmd = ['open', str(path)]
        else:
            editor = os.environ.get('EDITOR')
            if editor:
                cmd = [editor, str(path)]
            else:
                cmd = ['xdg-open', str(path)]
        Console.info(f"打开: {' '.join(cmd)}")
        try:
            sp.Popen(cmd)
            return True
        except Exception as e:
            Console.error(f"打开文件失败: {e}")
            return False

    def archive(self, fmt: str = 'zip', output: str = None) -> bool:
        if fmt not in ('zip', 'tar'):
            Console.error("格式仅支持 zip 或 tar")
            return False
        if not output:
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            output = f"codekit_archive_{ts}"
        base_name = output
        root_dir = Path.cwd()
        try:
            shutil.make_archive(base_name, fmt, root_dir)
            Console.success(f"打包成功: {base_name}.{fmt}")
            return True
        except Exception as e:
            Console.error(f"打包失败: {e}")
            return False

    # ---------- AI 功能 ----------
    def explain(self, target: str = '.', ask_question: str = None) -> bool:
        if ask_question:
            Console.info(f"追问: {ask_question}")
            files = []
            path = Path(target)
            if path.is_file():
                files = [path]
            else:
                for ext in PluginRegistry._handlers.keys():
                    files.extend(path.rglob(f'*{ext}'))
                files = files[:5]
            context = ""
            for f in files:
                try:
                    content = f.read_text(encoding='utf-8', errors='ignore')[:1000]
                    context += f"文件 {f.name}:\n{content}\n\n"
                except Exception:
                    pass
            if context:
                prompt = f"基于以下代码上下文，回答用户的问题：\n\n{context}\n\n问题: {ask_question}"
            else:
                prompt = f"用户问题: {ask_question}"
            try:
                response = self.ai_service.generate(prompt, temperature=0.5, max_tokens=500, context_aware=True)
                print(Console._c("AI 回答:", Color.CYAN))
                print(response)
                return True
            except Exception as e:
                Console.error(f"AI 回答失败: {e}")
                Console.info("降级到静态模式：查找相关定义...")
                if ask_question:
                    words = re.findall(r'\b\w+\b', ask_question)
                    for word in words:
                        if len(word) > 2:
                            self.where_service.where(word)
                return False

        path = Path(target)
        if path.is_file():
            files = [path]
        elif path.is_dir():
            files = []
            for ext in PluginRegistry._handlers.keys():
                files.extend(path.rglob(f'*{ext}'))
            if not files:
                Console.error(f"在 {target} 中未找到任何代码文件")
                return False
        else:
            Console.error(f"路径不存在: {target}")
            return False

        if len(files) > 10:
            Console.warn(f"有 {len(files)} 个文件，将仅分析前 10 个")
            files = files[:10]

        Console.info(f"正在使用 AI 分析 {len(files)} 个文件...")
        explanations = []
        for f in files:
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')[:2000]
                prompt = f"解释以下代码文件 {f.name} 的作用和主要功能：\n\n```\n{content}\n```"
                response = self.ai_service.generate(prompt, temperature=0.3, max_tokens=300, context_aware=True)
                explanations.append(f"--- {f.name} ---\n{response}")
            except Exception as e:
                Console.warn(f"分析 {f.name} 失败: {e}")
                continue

        if not explanations:
            Console.error("未能生成任何解释")
            return False

        Console.bold("\nAI 代码解释:\n")
        print("\n\n".join(explanations))
        return True

    def fix(self, target: Optional[str] = None) -> bool:
        Console.info("运行 Lint 检查以获取错误...")
        ok, errors = self.lint_service.lint(target)
        if ok:
            Console.success("没有发现 Lint 错误，无需修复")
            return True
        if not errors:
            Console.error("无法获取错误信息，可能 Lint 工具未输出")
            return False

        error_text = "\n".join(errors[:20])
        prompt = f"以下代码存在 Lint 错误，请给出修复补丁（diff 格式）或直接提供修改后的完整代码：\n\n{error_text}"
        try:
            response = self.ai_service.generate(prompt, temperature=0.5, max_tokens=1000, context_aware=True)
            Console.bold("AI 提供的修复建议:\n")
            print(response)
            ans = safe_input("是否应用这些修复？(y/N): ")
            if ans.lower() != 'y':
                Console.info("取消修复")
                return True
            code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', response, re.DOTALL)
            if not code_blocks:
                Console.warn("无法解析修复代码，请手动应用")
                return False
            if target:
                target_path = Path(target)
                if target_path.exists():
                    target_path.write_text(code_blocks[0], encoding='utf-8')
                    Console.success(f"已应用修复到 {target}")
                    return True
            Console.warn("未指定目标文件，无法自动应用")
            return False
        except Exception as e:
            Console.error(f"AI 修复失败: {e}")
            return False

    def test_gen(self, file: Optional[str] = None) -> bool:
        if file:
            target_file = Path(file)
            if not target_file.exists():
                Console.error(f"文件不存在: {file}")
                return False
            files = [target_file]
        else:
            main_candidates = []
            for ext in PluginRegistry._handlers.keys():
                candidates = list(Path.cwd().glob(f'*{ext}'))
                if candidates:
                    for c in candidates:
                        if c.stem in ('main', 'index', Path.cwd().name):
                            main_candidates.append(c)
                    if not main_candidates:
                        main_candidates.extend(candidates)
            if not main_candidates:
                Console.error("未找到可生成测试的代码文件，请指定")
                return False
            files = main_candidates[:1]

        for f in files:
            Console.info(f"为 {f} 生成单元测试...")
            try:
                content = f.read_text(encoding='utf-8', errors='ignore')
                if f.suffix == '.py':
                    test_framework = 'pytest'
                    test_suffix = '_test.py'
                    template = f"import pytest\nfrom {f.stem} import *\n\n# AI 生成的测试用例\n"
                elif f.suffix in ('.js', '.ts'):
                    test_framework = 'jest' if f.suffix == '.js' else 'ts-jest'
                    test_suffix = '.test.js' if f.suffix == '.js' else '.test.ts'
                    template = f"// AI 生成的测试用例\nimport {{}} from './{f.stem}';\n\n"
                elif f.suffix == '.go':
                    test_framework = 'testing'
                    test_suffix = '_test.go'
                    template = f"package {f.stem}\n\nimport \"testing\"\n\n// AI 生成的测试用例\n"
                else:
                    Console.warn(f"不支持为 {f.suffix} 生成测试")
                    continue

                prompt = f"为以下代码生成基于 {test_framework} 的单元测试代码，覆盖主要功能：\n\n```\n{content[:2000]}\n```"
                response = self.ai_service.generate(prompt, temperature=0.7, max_tokens=600, context_aware=True)
                code_blocks = re.findall(r'```(?:\w+)?\n(.*?)```', response, re.DOTALL)
                test_code = code_blocks[0] if code_blocks else response
                test_file = f.with_suffix(test_suffix)
                if test_file.exists():
                    overwrite = safe_input(f"测试文件 {test_file} 已存在，覆盖？(y/N): ")
                    if overwrite.lower() != 'y':
                        Console.info("跳过")
                        continue
                test_file.write_text(template + "\n" + test_code, encoding='utf-8')
                Console.success(f"测试代码已生成: {test_file}")
            except Exception as e:
                Console.error(f"生成测试失败: {e}")
                return False
        return True

    def kill_process(self, pid: int) -> bool:
        if sys.platform == 'win32':
            cmd = ['taskkill', '/PID', str(pid), '/F']
        else:
            cmd = ['kill', '-9', str(pid)]
        Console.info(f"终止进程 {pid}: {' '.join(cmd)}")
        ret = safe_run(cmd)
        if ret.returncode == 0:
            Console.success(f"进程 {pid} 已终止")
            return True
        Console.error(f"终止进程 {pid} 失败")
        return False

    # ---------- OI 专用 ----------
    def init_oi(self, lang: str = 'cpp') -> bool:
        if lang not in ('cpp', 'c', 'python', 'java', 'go', 'rust'):
            Console.error(f"不支持的语言: {lang}，支持: cpp, c, python, java, go, rust")
            return False

        tpl_dir = Path(self.cfg.get('template_dir', str(GLOBAL_CONFIG_DIR / 'templates')))
        tpl_dir.mkdir(parents=True, exist_ok=True)

        templates = {
            'cpp': '''#include <bits/stdc++.h>
using namespace std;

using ll = long long;
using pii = pair<int, int>;
using pll = pair<ll, ll>;

#define fi first
#define se second
#define pb push_back
#define all(x) (x).begin(), (x).end()
#define rall(x) (x).rbegin(), (x).rend()
#define sz(x) ((int)(x).size())

template <typename T>
void read(T &x) {
    char c; bool f = false;
    for (c = getchar(); c < '0' || c > '9'; c = getchar()) if (c == '-') f = true;
    x = c - '0';
    for (c = getchar(); c >= '0' && c <= '9'; c = getchar()) x = x * 10 + c - '0';
    if (f) x = -x;
}

int main() {
    ios::sync_with_stdio(false);
    cin.tie(nullptr);
    
    // 你的代码
    
    return 0;
}
''',
            'c': '''#include <stdio.h>
#include <stdlib.h>

int main() {
    // 你的代码
    return 0;
}
''',
            'python': '''#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys

def main():
    data = sys.stdin.read().strip().split()
    # 你的代码
    pass

if __name__ == "__main__":
    main()
''',
            'java': '''import java.io.*;
import java.util.*;

public class Main {
    public static void main(String[] args) throws IOException {
        BufferedReader br = new BufferedReader(new InputStreamReader(System.in));
        // 你的代码
    }
}
''',
            'go': '''package main

import (
    "bufio"
    "fmt"
    "os"
)

func main() {
    reader := bufio.NewReader(os.Stdin)
    _ = reader
    fmt.Println()
    // 你的代码
}
''',
            'rust': '''use std::io::{self, BufRead};

fn main() {
    let stdin = io::stdin();
    let mut lines = stdin.lock().lines();
    let _ = lines.next();
    // 你的代码
}
'''
        }

        content = templates.get(lang)
        if not content:
            Console.error("模板不存在")
            return False

        ext_map = {'cpp': '.cpp', 'c': '.c', 'python': '.py', 'java': '.java', 'go': '.go', 'rust': '.rs'}
        fname = f"_template{ext_map[lang]}"
        tpl_file = tpl_dir / fname
        if not tpl_file.exists():
            tpl_file.write_text(content, encoding='utf-8')
            Console.success(f"OI 模板已创建: {tpl_file}")
        else:
            Console.info(f"模板已存在: {tpl_file}")

        src_file = Path.cwd() / f"main{ext_map[lang]}"
        if src_file.exists():
            overwrite = safe_input(f"文件 {src_file} 已存在，覆盖? (y/N): ")
            if overwrite.lower() != 'y':
                Console.info("跳过创建源文件")
                return True
        src_file.write_text(content, encoding='utf-8')
        Console.success(f"源文件已创建: {src_file}")
        return True

    # ---------- 自检 ----------
    def self_test(self) -> bool:
        Console.bold("🧪 运行 CodeKit OI 自检...")
        success = True
        try:
            cfg = ConfigManager()
            Console.success("配置加载正常")
        except Exception as e:
            Console.error(f"配置加载失败: {e}")
            success = False
        try:
            PluginRegistry.initialize()
            handlers = PluginRegistry.get_all_handlers()
            Console.success(f"插件注册正常，共 {len(handlers)} 个处理器")
        except Exception as e:
            Console.error(f"插件注册失败: {e}")
            success = False

        for tool in ['git', 'make', 'gcc', 'g++', 'python', 'node']:
            if shutil.which(tool):
                Console.debug(f"{tool} 可用")
            else:
                Console.warn(f"{tool} 未安装（可选）")
        try:
            with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as tf:
                tf.write("print('self-test OK')")
                tf_path = tf.name
            try:
                if self.run(tf_path):
                    Console.success("简单 run 命令测试通过")
                else:
                    Console.error("简单 run 命令测试失败")
                    success = False
            finally:
                os.unlink(tf_path)
        except Exception as e:
            Console.error(f"run 测试异常: {e}")
            success = False

        if success:
            Console.success("✅ 所有自检项目通过")
        else:
            Console.error("❌ 自检发现错误，请检查日志")
        return success


# ======================== 交互模式 ========================
def interactive_mode(mgr: CodeManager):
    mgr.import_service.set_interactive(True)
    try:
        import readline
        histfile = Path.home() / '.codemanager_history'
        if histfile.exists():
            readline.read_history_file(str(histfile))
        atexit.register(lambda: readline.write_history_file(str(histfile)))
    except ImportError:
        pass
    title = "CodeKit OI 交互模式"
    help_line = "输入 help 查看可用指令"
    exit_line = "输入 exit 或 quit 退出"
    width = 40
    border = "═" * (width - 2)
    Console.bold(f"╔{border}╗")
    Console.bold(f"║{title.center(width - 2)}║")
    Console.bold(f"║{help_line.center(width - 2)}║")
    Console.bold(f"║{exit_line.center(width - 2)}║")
    Console.bold(f"╚{border}╝")
    print(f"  当前工作目录: {Path.cwd()}")
    print("  输入 exit 或 quit 退出\n")
    while True:
        try:
            cmd = input(Console._c("codes> ", Color.GREEN)).strip()
            if not cmd:
                continue
            if cmd.lower() in ('exit', 'quit'):
                Console.info("再见!")
                break
            parts = cmd.split()
            if parts[0].lower() == 'help':
                print(create_parser().format_help())
                continue
            main_parse(parts, mgr)
        except KeyboardInterrupt:
            print()
            Console.info("输入 exit 退出")
        except Exception as e:
            Console.error(str(e))
            if VERBOSE:
                traceback.print_exc()


# ======================== 命令行解析 ========================
def create_parser():
    parser = argparse.ArgumentParser(
        prog="CodeKit OI",
        description="专为信息学竞赛（OI）设计的代码工具，支持对拍、批量测试、计时、生成器、AI 辅助等。",
        epilog="示例:\n"
               "  ck run main.cpp\n"
               "  ck stress main.cpp brute.cpp --gen gen.py --cases 100 --shrink --eps 1e-6 --sanitize --checker checker.cpp --celebrate\n"
               "  ck stress main.cpp --auto                                 # AI 自动生成暴力和生成器\n"
               "  ck stress main.cpp --replay                               # 重放统一失败库中的 WA 反例\n"
               "  ck test main.cpp                                          # 自动检测 data/in 或 data\n"
               "  ck test main.cpp --input-dir ./data/in --cktest .cktest --sanitize --memory-limit 256 --dry-run\n"
               "  ck judge --source main.cpp                                # 无配置文件也可用，自动检测\n"
               "  ck judge --source main.cpp --html\n"
               "  ck judge --source main.cpp --format json                  # 机器可读输出\n"
               "  ck interact solution.cpp interactor.cpp --input in.txt    # 交互题\n"
               "  ck gen gen.py --cases 10 --seed 12345 --dry-run\n"
               "  ck time main.cpp --flamegraph --top\n"
               "  ck init cpp\n"
               "  ck snippet list\n"
               "  ck snippet get segtree --output my.cpp --insert --position \"// @insert_here\"\n"
               "  ck snippet --from-file mycode.cpp --name mytemplate\n"
               "  ck contest start contest.json --duration 3600 --cfg my_config.json\n"
               "  ck explain main.cpp --ask \"为什么用指针？\"\n"
               "  ck fix main.cpp\n"
               "  ck check main.cpp\n"
               "  ck copy main.cpp\n"
               "  ck submit main.cpp --problem P1001 --platform luogu --dry-run\n"
               "  ck submit main.cpp --all\n"
               "  ck diff my.out std.out --ignore-trailing-spaces --ignore-blank-lines\n"
               "  ck env --check-g++\n"
               "  ck watch main.cpp --test --input-dir data/in --abackup\n"
               "  ck watch main.cpp --nerror\n"
               "  ck watch main.cpp --nerror --ai-explain\n"
               "  ck failures list\n"
               "  ck failures show <id>\n"
               "  ck failures retry\n"
               "  ck todo --add \"优化二分边界\"\n"
               "  ck todo --list\n"
               "  ck bench main.cpp --save --dry-run\n"
               "  ck bench main.cpp --compare\n"
               "  ck bench main.cpp --track\n"
               "  ck open P1001 --platform luogu\n"
               "  ck todo --count\n"
               "  ck where main\n"
               "  ck mood set tired\n"
               "  ck ask \"为什么编译报错？\"\n"
               "  ck timer 30\n"
               "  ck cd /path/to/project\n"
               "  ck self-test\n"
               "  ck scan .\n"
               "  ck polish main.cpp --output main_polished.cpp --yes\n"
               "  ck polish main.cpp --fileIO\n"
               "  ck doctor --hard\n"
               "  ck sample main.cpp\n"
               "  ck import myplugin.py\n"
               "  ck import a.py b.py --persistence\n"
               "  ck import myplugin.py --lazy\n"
               "  ck anal_log --list\n"
               "  ck anal_log --summary\n"
               "  ck rip                                                      # 纪念 fetch / upgrade\n"
               "  ck --quiet run main.cpp\n"
    )
    parser.add_argument('--verbose', '-v', action='store_true', help='输出详细调试信息')
    parser.add_argument('--dry-run', '-n', action='store_true', help='全局试运行模式（仅打印操作，不实际执行）')
    parser.add_argument('--quiet', '-q', action='store_true', help='安静模式，抑制所有输出')
    parser.add_argument('--version', action='store_true', help='打印版本并退出')
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    p_run = subparsers.add_parser('run', help='运行代码文件')
    p_run.add_argument('file', help='源代码文件')
    p_run.add_argument('version', nargs='?', help='Python版本（可选）')
    p_run.add_argument('--std', help='编译器标准 (如 c++17)')
    p_run.add_argument('args', nargs=argparse.REMAINDER, help='传递给程序的参数')

    p_compile = subparsers.add_parser('compile', help='仅编译')
    p_compile.add_argument('file', help='源代码文件')
    p_compile.add_argument('--sanitize', action='store_true', help='启用 AddressSanitizer 检测内存错误')

    p_clean = subparsers.add_parser('clean', help='清理构建产物')
    p_clean.add_argument('--dry-run', action='store_true', help='试运行')
    p_clean.add_argument('--no-confirm', action='store_true', help='跳过确认')

    p_new = subparsers.add_parser('new', help='创建新文件（带模板）或插件模板')
    p_new.add_argument('file', help='新文件路径或插件名称')
    p_new.add_argument('--plugin', action='store_true', help='创建语言插件模板')
    p_new.add_argument('--command', action='store_true', help='创建命令插件模板')

    p_list = subparsers.add_parser('list', aliases=['ls'], help='列出代码文件')
    p_list.add_argument('filter', nargs='?', help='按扩展名过滤')

    p_search = subparsers.add_parser('search', help='搜索代码内容')
    p_search.add_argument('keyword', help='关键词')

    p_backup = subparsers.add_parser('backup', help='备份当前目录')
    p_backup.add_argument('dst', nargs='?', help='目标备份路径')

    p_restore = subparsers.add_parser('restore', aliases=['back'], help='从备份还原')
    p_restore.add_argument('src', help='备份源路径')

    p_git = subparsers.add_parser('git', help='执行 Git 操作（安全白名单）')
    p_git.add_argument('args', nargs='*', help='Git 参数，默认 status')

    p_watch = subparsers.add_parser('watch', help='监控文件变化自动重跑')
    p_watch.add_argument('file', help='要监控的文件')
    p_watch.add_argument('--test', action='store_true', help='保存时自动运行测试点')
    p_watch.add_argument('--input-dir', help='测试输入目录（与 --test 配合）')
    p_watch.add_argument('--output-dir', help='测试输出目录')
    p_watch.add_argument('--timeout', type=int, help='测试超时')
    p_watch.add_argument('--cktest', help='.cktest 数据包文件')
    p_watch.add_argument('--sanitize', action='store_true', help='启用 AddressSanitizer')
    p_watch.add_argument('--memory-limit', type=int, help='内存限制（MB）')
    p_watch.add_argument('--abackup', '-abp', action='store_true', help='每次修改保存可编译的备份（带时间戳）')
    p_watch.add_argument('--nerror', '-ne', action='store_true', help='监控编译错误，若有错误则保存快照和错误信息')
    p_watch.add_argument('--noteerror', action='store_true', help='同 --nerror')
    p_watch.add_argument('--ai-explain', action='store_true',
                         help='与 --nerror 配合，编译失败时调用 AI 分析并保存 ai.txt')

    p_pyexe = subparsers.add_parser('pyexe', help='将 Python 打包为 EXE')
    p_pyexe.add_argument('file', help='.py 文件')
    p_pyexe.add_argument('opts', nargs='*', help='PyInstaller 选项')

    p_todll = subparsers.add_parser('todll', help='打包 .cs/.cpp 为 DLL')
    p_todll.add_argument('file', help='源文件')
    p_todll.add_argument('output', nargs='?', help='输出文件名（不含扩展名）')

    p_chdir = subparsers.add_parser('chdir', help='切换工作目录')
    p_chdir.add_argument('path', nargs='?', help='目标目录')

    p_config = subparsers.add_parser('config', help='查看或修改配置')
    p_config.add_argument('action', choices=['get', 'set', 'show', 'diff', 'reload'], default='show', nargs='?')
    p_config.add_argument('key', nargs='?', help='配置键')
    p_config.add_argument('value', nargs='?', help='配置值')

    p_shell = subparsers.add_parser('shell', aliases=['interactive'], help='进入交互模式')

    p_build = subparsers.add_parser('build', help='构建项目')
    p_deps = subparsers.add_parser('deps', help='依赖管理')
    p_deps_sub = p_deps.add_subparsers(dest='deps_action', help='依赖操作')
    p_deps_check = p_deps_sub.add_parser('check', help='检查依赖文件')
    p_deps_install = p_deps_sub.add_parser('install', help='安装依赖')

    p_fmt = subparsers.add_parser('fmt', help='格式化代码')
    p_fmt.add_argument('target', help='文件或目录路径')

    p_grep = subparsers.add_parser('grep', help='快速搜索')
    p_grep.add_argument('pattern', help='搜索模式')
    p_grep.add_argument('extra', nargs='*', help='额外参数')

    p_def = subparsers.add_parser('def', help='查找符号定义')
    p_def.add_argument('symbol', help='符号名')

    p_stats = subparsers.add_parser('stats', help='代码统计')
    p_stats.add_argument('--by-file', action='store_true', help='按文件显示')

    p_debug = subparsers.add_parser('debug', help='调试代码')
    p_debug.add_argument('file', help='源文件')
    p_debug.add_argument('args', nargs=argparse.REMAINDER, help='调试参数')

    p_plugin = subparsers.add_parser('plugin', help='插件管理')
    p_plugin_sub = p_plugin.add_subparsers(dest='plugin_action', help='插件操作')
    p_plugin_list = p_plugin_sub.add_parser('list', help='列出已安装插件')
    p_plugin_install = p_plugin_sub.add_parser('install', help='安装插件')
    p_plugin_install.add_argument('name_or_url', help='插件名称或URL')
    p_plugin_reload = p_plugin_sub.add_parser('reload', help='热加载插件（无需重启）')

    p_terminal = subparsers.add_parser('terminal', help='启动新终端')
    p_edit = subparsers.add_parser('edit', help='用默认编辑器打开文件')
    p_edit.add_argument('file', help='文件路径')

    p_task = subparsers.add_parser('task', help='执行自定义任务')
    p_task.add_argument('name', help='任务名称')
    p_task.add_argument('args', nargs='*', help='任务参数')

    p_env = subparsers.add_parser('env', help='管理环境变量和环境指纹')
    p_env_sub = p_env.add_subparsers(dest='env_action', help='环境操作')
    p_env_list = p_env_sub.add_parser('list', help='列出当前环境变量')
    p_env_set = p_env_sub.add_parser('set', help='设置环境变量')
    p_env_set.add_argument('key')
    p_env_set.add_argument('value')
    p_env_save = p_env_sub.add_parser('save', help='保存环境指纹')
    p_env_restore = p_env_sub.add_parser('restore', help='恢复环境指纹')
    p_env_check_gpp = p_env_sub.add_parser('check-g++', help='检测并选用最新 g++ 版本')

    p_kill = subparsers.add_parser('kill', help='终止进程')
    p_kill.add_argument('pid', type=int, help='进程 PID')

    p_lint = subparsers.add_parser('lint', help='静态代码检查')

    p_commit = subparsers.add_parser('commit', help='智能生成并提交 Git commit message')

    p_checksum = subparsers.add_parser('checksum', help='计算文件哈希')
    p_checksum.add_argument('file')
    p_checksum.add_argument('--algo', default='sha256', choices=['md5', 'sha1', 'sha256', 'sha512'])

    p_freeze = subparsers.add_parser('freeze', help='生成依赖哈希锁文件')

    p_archive = subparsers.add_parser('archive', help='打包项目')
    p_archive.add_argument('--format', choices=['zip', 'tar'], default='zip')
    p_archive.add_argument('--output', help='输出文件名（不含扩展名）')

    p_self_test = subparsers.add_parser('self-test', help='运行自检')

    p_explain = subparsers.add_parser('explain', help='AI 解释代码或追问')
    p_explain.add_argument('file', nargs='?', default='.', help='文件或目录')
    p_explain.add_argument('--ask', help='追问问题，进入问答模式')

    p_fix = subparsers.add_parser('fix', help='AI 修复 Lint 错误')
    p_fix.add_argument('--file', help='指定文件')

    p_failures = subparsers.add_parser('failures', help='统一失败库：查看/重试所有历史失败')
    p_failures_sub = p_failures.add_subparsers(dest='failures_action', help='failures 操作')
    p_failures_list = p_failures_sub.add_parser('list', help='列出所有历史失败')
    p_failures_list.add_argument('--type', choices=['compile', 'wa', 're'], help='按类型过滤')
    p_failures_show = p_failures_sub.add_parser('show', help='查看某个失败的完整现场')
    p_failures_show.add_argument('id', help='失败记录 ID（支持前缀匹配）')
    p_failures_retry = p_failures_sub.add_parser('retry', help='重跑所有失败的 case')
    p_failures_retry.add_argument('--type', choices=['compile', 'wa', 're'], help='按类型过滤')

    p_import = subparsers.add_parser(
        'import',
        help='导入命令模块（优先级: module_list > CommandFormat > Command）'
    )
    p_import.add_argument('modules', nargs='+', help='要导入的模块文件（.py）')
    p_import.add_argument('--lazy', '-l', action='store_true',
                          help='仅交互模式：延迟导入（用时才加载）')
    p_import.add_argument('--persistence', '-p', action='store_true',
                          help='将模块文件拷贝到加载目录')

    p_stress = subparsers.add_parser('stress', help='对拍（批量模式，支持 ddmin 自动缩小、浮点数容差、Sanitizer、SPJ、重放反例）')
    p_stress.add_argument('main', help='主程序（优化）')
    p_stress.add_argument('brute', nargs='?', default='brute_auto.cpp', help='暴力程序（若使用 --auto 可省略）')
    p_stress.add_argument('--gen', default='gen_auto.py', help='数据生成器文件（若使用 --auto 可省略）')
    p_stress.add_argument('--cases', type=int, default=100, help='测试数据组数')
    p_stress.add_argument('--timeout', type=int, help='每组超时（秒）')
    p_stress.add_argument('--gen-args', nargs='*', help='传递给生成器的参数')
    p_stress.add_argument('--shrink', action='store_true', help='启用 ddmin 自动缩小反例')
    p_stress.add_argument('--parallel', action='store_true', help='启用并行执行（多核）')
    p_stress.add_argument('--workers', type=int, default=4, help='并行线程数')
    p_stress.add_argument('--eps', type=float, help='浮点数容差，例如 1e-6')
    p_stress.add_argument('--sanitize', action='store_true', help='启用 AddressSanitizer 检测内存错误')
    p_stress.add_argument('--checker', help='Special Judge 程序（编译型）')
    p_stress.add_argument('--celebrate', action='store_true', help='全部 AC 时打印彩蛋')
    p_stress.add_argument('--auto', action='store_true', help='AI 自动生成暴力和生成器')
    p_stress.add_argument('--replay', action='store_true', help='重放 .codekit-failures/wa/ 下的历史反例')
    p_stress.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_test = subparsers.add_parser('test', help='批量测试（支持 .cktest 数据包，支持 SPJ，内存限制）')
    p_test.add_argument('file', help='主程序文件')
    p_test.add_argument('--input-dir', default=None,
                        help='输入目录（包含 .in 文件）；不指定则自动检测 data/in、data 或当前目录')
    p_test.add_argument('--output-dir', help='期望输出目录（包含 .out/.ans 文件）')
    p_test.add_argument('--timeout', type=int, help='每组超时（秒）')
    p_test.add_argument('--exact', action='store_true', help='精确比较输出（默认）')
    p_test.add_argument('--cktest', help='指定 .cktest 数据包文件路径')
    p_test.add_argument('--sanitize', action='store_true', help='启用 AddressSanitizer')
    p_test.add_argument('--memory-limit', type=int, help='内存限制（MB），仅 Unix')
    p_test.add_argument('--dry-run', '-n', action='store_true', help='试运行')
    p_test.add_argument('--gen', action='store_true', help='使用 AI 生成单元测试（与批量测试互斥）')
    p_test.add_argument('--file', dest='unit_file', nargs='?', help='为指定文件生成测试')

    p_gen = subparsers.add_parser('gen', help='数据生成器')
    p_gen.add_argument('gen_file', help='生成器文件')
    p_gen.add_argument('--cases', type=int, default=1, help='生成数据组数')
    p_gen.add_argument('--output-prefix', default='data', help='输出文件名前缀')
    p_gen.add_argument('--gen-args', nargs='*', help='传递给生成器的参数')
    p_gen.add_argument('--seed', type=int, help='随机种子')
    p_gen.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_time = subparsers.add_parser('time', help='计时与内存统计')
    p_time.add_argument('file', help='程序文件')
    p_time.add_argument('args', nargs='*', help='程序参数')
    p_time.add_argument('--timeout', type=int, help='超时（秒）')
    p_time.add_argument('--flamegraph', action='store_true', help='生成火焰图（需 py-spy）')
    p_time.add_argument('--top', action='store_true', help='显示最耗时的 Top N 函数（轻量级）')
    p_time.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_init = subparsers.add_parser('init', help='生成 OI 模板')
    p_init.add_argument('lang', nargs='?', default='cpp', help='语言 (cpp, c, python, java, go, rust)')

    p_snippet = subparsers.add_parser('snippet', help='算法模板速查与插入（支持位置插入、变量替换）')
    p_snippet.add_argument('--from-file', dest='from_file', help='从文件导入自定义模板到 ~/.codekit/snippets/')
    p_snippet.add_argument('--name', help='导入模板的名称（默认使用文件名）')
    p_snippet_sub = p_snippet.add_subparsers(dest='snippet_action', help='snippet 操作')
    p_snippet_list = p_snippet_sub.add_parser('list', help='列出所有可用模板')
    p_snippet_get = p_snippet_sub.add_parser('get', help='获取并插入模板')
    p_snippet_get.add_argument('name', help='模板名称')
    p_snippet_get.add_argument('--output', '-o', help='输出文件（默认打印到终端）')
    p_snippet_get.add_argument('--insert', action='store_true', help='追加到输出文件（而不是覆盖）')
    p_snippet_get.add_argument('--position', help='在文件中查找该标记行，并在其后插入模板')

    p_contest = subparsers.add_parser('contest', help='竞赛模式')
    p_contest_sub = p_contest.add_subparsers(dest='contest_action', help='contest 操作')
    p_contest_start = p_contest_sub.add_parser('start', help='启动比赛')
    p_contest_start.add_argument('config', nargs='?', default='contest.json', help='比赛配置 JSON 文件（可被 --cfg 覆盖）')
    p_contest_start.add_argument('--cfg', help='指定配置文件路径（优先级高于 config 位置参数）')
    p_contest_start.add_argument('--duration', type=int, default=3600, help='比赛时长（秒），默认 3600')
    p_contest_start.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_judge = subparsers.add_parser('judge', help='本地 OI 评测机 (NOIP/CSP 模拟)')
    p_judge.add_argument('--problem-config', '-p', default=None,
                         help='题目配置文件路径（默认 .codekit-problem.json，缺失时自动检测 data/in 或 data）')
    p_judge.add_argument('--source', '-s', default='main.cpp', help='源代码文件')
    p_judge.add_argument('--output-dir', '-o', help='输出目录（默认 data/out）')
    p_judge.add_argument('--html', action='store_true', help='导出 HTML 报告')
    p_judge.add_argument('--format', choices=['text', 'json'], default='text', help='输出格式，默认 text')
    p_judge.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_scan = subparsers.add_parser('scan', help='静态分析 C/C++ 代码，生成“赛场避坑指南”')
    p_scan.add_argument('target', nargs='?', default='.', help='文件或目录，默认当前目录')

    p_polish = subparsers.add_parser('polish', help='提交前自动防雷（默认注释 freopen，删除调试输出、检查 #define int long long）')
    p_polish.add_argument('file', help='源文件')
    p_polish.add_argument('--output', '-o', help='输出文件（默认 源文件名_polished.扩展名）')
    p_polish.add_argument('--yes', '-y', action='store_true', help='自动确认所有操作')
    p_polish.add_argument('--fileIO', action='store_true', help='保留文件IO操作（不注释 freopen/fclose）')
    p_polish.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_bench = subparsers.add_parser('bench', help='性能基准与回归追踪')
    p_bench.add_argument('file', help='程序文件')
    p_bench.add_argument('args', nargs='*', help='程序参数')
    p_bench.add_argument('--timeout', type=int, help='超时（秒）')
    p_bench.add_argument('--iterations', type=int, help='迭代次数')
    p_bench.add_argument('--save', action='store_true', help='保存基准结果')
    p_bench.add_argument('--compare', action='store_true', help='与现有基准比较')
    p_bench.add_argument('--baseline', help='自定义基准文件')
    p_bench.add_argument('--track', action='store_true', help='性能追踪模式（记录历史并比较）')
    p_bench.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_doctor = subparsers.add_parser('doctor', help='环境诊断与压力测试')
    p_doctor.add_argument('--hard', action='store_true', help='执行极限压力测试，生成 OI 适配报告')

    p_sample = subparsers.add_parser('sample', help='自动搜索样例并输出 AC/WA 结果')
    p_sample.add_argument('main', nargs='?', help='主程序文件（默认自动检测）')
    p_sample.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_open = subparsers.add_parser('open', help='打开 OJ 题目页面')
    p_open.add_argument('problem', help='题目 ID')
    p_open.add_argument('--platform', default='luogu', help='平台 (luogu/codeforces/atcoder)')

    p_copy = subparsers.add_parser('copy', help='复制文件内容到剪贴板')
    p_copy.add_argument('file', help='文件路径')

    p_submit = subparsers.add_parser('submit', help='提交代码到 OJ')
    p_submit.add_argument('file', help='源文件')
    p_submit.add_argument('--problem', help='题目 ID')
    p_submit.add_argument('--platform', default='luogu', help='平台')
    p_submit.add_argument('--contest', help='比赛 ID')
    p_submit.add_argument('--language', help='语言')
    p_submit.add_argument('--fast', action='store_true', help='使用 .codekit-oj.json 快速提交')
    p_submit.add_argument('--all', action='store_true', help='批量提交 (submit-all.json)')
    p_submit.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_diff = subparsers.add_parser('diff', help='比较两个文件的差异')
    p_diff.add_argument('file1', help='文件 1')
    p_diff.add_argument('file2', help='文件 2')
    p_diff.add_argument('--ignore-trailing-spaces', action='store_true', help='忽略行尾空白')
    p_diff.add_argument('--ignore-blank-lines', action='store_true', help='忽略空行')

    p_todo = subparsers.add_parser('todo', help='TODO/FIXME 统计与管理')
    p_todo.add_argument('--add', help='添加一条 TODO')
    p_todo.add_argument('--list', action='store_true', help='列出 TODO 列表')
    p_todo.add_argument('--sort-by-date', action='store_true', help='按 Git 提交时间排序')
    p_todo.add_argument('--count', action='store_true', help='统计每个文件的 TODO 数量')

    p_where = subparsers.add_parser('where', help='查找符号定义位置')
    p_where.add_argument('symbol', help='符号名')

    p_mood = subparsers.add_parser('mood', help='状态管理 (normal/tired)')
    p_mood_sub = p_mood.add_subparsers(dest='mood_action', help='mood 操作')
    p_mood_set = p_mood_sub.add_parser('set', help='设置状态')
    p_mood_set.add_argument('state', choices=['normal', 'tired'], help='状态')
    p_mood_get = p_mood_sub.add_parser('get', help='查看当前状态')

    p_ask = subparsers.add_parser('ask', help='向 AI 提问')
    p_ask.add_argument('question', help='问题内容')

    p_timer = subparsers.add_parser('timer', help='番茄钟计时器')
    p_timer.add_argument('minutes', type=int, nargs='?', default=None, help='时长（分钟），默认 25')

    p_cd = subparsers.add_parser('cd', help='切换工作目录')
    p_cd.add_argument('path', nargs='?', help='目标目录')

    p_anal_log = subparsers.add_parser('anal_log', help='分析崩溃日志')
    p_anal_log.add_argument('log_file', nargs='?', help='日志文件路径（默认为今天的）')
    p_anal_log.add_argument('--today', action='store_true', help='分析今天的日志')
    p_anal_log.add_argument('--list', dest='list_flag', action='store_true', help='列出所有日志文件')
    p_anal_log.add_argument('--tail', type=int, default=0, help='只显示最后 N 条')
    p_anal_log.add_argument('--summary', action='store_true', help='显示统计摘要')
    p_anal_log.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    # ---------- v5.2 新增 ----------
    p_interact = subparsers.add_parser(
        'interact',
        help='交互题支持：编译选手程序与交互器，由交互器负责通信'
    )
    p_interact.add_argument('player', help='选手程序源文件（编译型或 .py）')
    p_interact.add_argument('interactor', help='交互器源文件（编译型或 .py）')
    p_interact.add_argument('--input', '-i', help='传给交互器的输入数据文件（可选）')
    p_interact.add_argument('--timeout', '-t', type=int, help='交互超时（秒），默认取 oi.timeout')
    p_interact.add_argument('--player-args', nargs='*', default=None,
                            help='传递给选手程序的额外参数（附加到 argv[1] 之后）')
    p_interact.add_argument('--interactor-args', nargs='*', default=None,
                            help='传递给交互器的额外参数')
    p_interact.add_argument('--dry-run', '-n', action='store_true', help='试运行')

    p_rip = subparsers.add_parser(
        'rip',
        help='纪念已移除的 fetch 与 upgrade 子指令'
    )

    return parser


def main_parse(argv: List[str], mgr: CodeManager):
    global DRY_RUN, VERBOSE, QUIET
    parser = create_parser()
    if not argv:
        parser.print_help()
        return

    # 移除全局 quiet 标志（在 main() 中已经生效）
    argv = [a for a in argv if a not in ('--quiet', '-q')]
    if not argv:
        parser.print_help()
        return

    first_arg = argv[0]

    # 优先级: module_list > CommandFormat > Command
    if mgr.import_service.is_module_command(first_arg):
        ns = argparse.Namespace(command=first_arg)
        setattr(ns, 'dry_run', DRY_RUN)
        setattr(ns, 'verbose', VERBOSE)
        setattr(ns, '_remaining', list(argv[1:]))
        audit_log(' '.join([sys.argv[0]] + argv))
        mgr.dispatch_command(ns)
        return

    max_iter = 5
    iter_count = 0
    while iter_count < max_iter:
        new_argv = mgr._apply_command_format(argv)
        if new_argv == argv:
            break
        argv = new_argv
        iter_count += 1
    if iter_count >= max_iter:
        Console.warn("命令格式化达到最大迭代次数，可能存在循环引用")

    if '--dry-run' in argv or '-n' in argv:
        DRY_RUN = True
    if '--verbose' in argv or '-v' in argv:
        VERBOSE = True

    args = parser.parse_args(argv)
    if not hasattr(args, 'dry_run'):
        setattr(args, 'dry_run', DRY_RUN)
    if not hasattr(args, 'verbose'):
        setattr(args, 'verbose', VERBOSE)
    if not hasattr(args, 'quiet'):
        setattr(args, 'quiet', QUIET)

    audit_log(' '.join([sys.argv[0]] + argv))
    mgr.dispatch_command(args)


# ======================== 主入口 ========================
def _main_impl():
    global VERBOSE, DRY_RUN, QUIET

    _install_sigint_handler()

    if '--quiet' in sys.argv or '-q' in sys.argv:
        QUIET = True
        Console.set_quiet(True)
        _install_quiet_streams()

    if '--verbose' in sys.argv or '-v' in sys.argv:
        VERBOSE = True
        if not QUIET:
            logger.setLevel(logging.DEBUG)
    if '--dry-run' in sys.argv or '-n' in sys.argv:
        DRY_RUN = True

    cfg = ConfigManager()
    container = Container()
    container.register('config', cfg)
    container.register('ai', AIService(cfg))
    container.register('build', BuildService(cfg))
    container.register('deps', DependencyService(cfg))
    container.register('format', FormatService(cfg))
    container.register('search', SearchService(cfg))
    container.register('stats', StatsService(cfg))
    container.register('debug', DebugService(cfg))
    container.register('git', GitService(cfg))
    container.register('task', TaskService(cfg, None))
    container.register('env', EnvService(cfg))
    container.register('lint', LintService(cfg))
    container.register('scaffold', ScaffoldService(cfg))
    container.register('checksum', ChecksumService(cfg))
    container.register('doctor', DoctorService(cfg))
    container.register('stress', StressService(cfg))
    container.register('test', TestService(cfg))
    container.register('gen', GenService(cfg))
    container.register('time', TimeService(cfg))
    container.register('snippet', SnippetService(cfg))
    container.register('contest', ContestService(cfg))
    container.register('check', CheckService(cfg))
    container.register('fetch', FetchService(cfg))
    container.register('copy', CopyService(cfg))
    container.register('submit', SubmitService(cfg))
    container.register('bench', BenchService(cfg, TimeService(cfg)))
    container.register('open', OpenService(cfg))
    container.register('todo', TodoService(cfg))
    container.register('where', WhereService(cfg))
    container.register('mood', MoodService(cfg))
    container.register('ask', AskService(cfg, AIService(cfg)))
    container.register('timer', TimerService(cfg))
    container.register('diff', DiffService(cfg))
    container.register('judge', JudgeService(cfg))
    container.register('scan', ScanService(cfg))
    container.register('polish', PolishService(cfg))
    container.register('sample', SampleService(cfg))
    container.register('failures', FailureLibrary(cfg))
    container.register('import', ImportService(cfg))
    container.register('anal_log', AnalLogService(cfg))
    # v5.2 新增
    container.register('interact', InteractService(cfg))

    mgr = CodeManager(container)
    mgr.task_service.code_manager = mgr

    PluginRegistry.initialize()

    if '--version' in sys.argv:
        if VERBOSE:
            print(f"CodeKit OI v5.2")
            print(f"Python: {sys.version}")
            print(f"运行路径: {Path(__file__).resolve()}")
            print(f"配置目录: {GLOBAL_CONFIG_DIR}")
            print(f"日志目录: {LOGS_DIR}")
            print(f"已加载插件: {PluginRegistry._loaded_plugins}")
            fmt_list = cfg.get('CommandFormat', [])
            print(f"CommandFormat 条目数: {len(fmt_list)}")
            if fmt_list:
                print("CommandFormat 映射:")
                for item in fmt_list:
                    if isinstance(item, dict):
                        print(f"  {item.get('指令名', '?')} -> {item.get('对应指令', '?')}")
        else:
            print("CodeKit OI v5.2")
        sys.exit(0)

    if len(sys.argv) == 1:
        interactive_mode(mgr)
    else:
        try:
            main_parse(sys.argv[1:], mgr)
        except SystemExit:
            raise
        except Exception as e:
            Console.error(str(e))
            if VERBOSE:
                traceback.print_exc()
            sys.exit(1)


def main():
    try:
        _main_impl()
    except SystemExit:
        raise
    except KeyboardInterrupt:
        try:
            Console.warn("\n用户中断")
        except Exception:
            pass
        sys.exit(130)
    except Exception as e:
        try:
            log_file = _write_crash_log(e)
        except Exception:
            log_file = None
        try:
            Console.error(f"发生未捕获异常: {type(e).__name__}: {e}")
            if log_file:
                Console.info(f"崩溃日志已写入: {log_file}")
            else:
                Console.info(f"崩溃日志目录: {LOGS_DIR}")
            Console.info("可运行 'ck anal_log' 分析崩溃日志")
        except Exception:
            pass
        sys.exit(1)


if __name__ == "__main__":
    main()