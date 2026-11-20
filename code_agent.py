#!/usr/bin/env python3
"""
Ultimate Local Code Improvement Agent (Ollama)
------------------------------------------------
Features:
- Multi-file safe apply (with confirmation)
- Automatic git branch + commit
- Create GitHub Pull Request (gh)
- Run tests before/after
- Export .patch file
- Dry-run mode
- Chunked reading for large files
- Gradio Web UI with Split-Screen 2D Pixel Office Agent (Gradio 6)
"""

import os
import sys
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Tuple
from openai import OpenAI

# ====================== CONFIG ======================
MODEL = "qwen2.5-coder:14b"                  # ← change to your model
OLLAMA_BASE_URL = "http://localhost:11434/v1"
DRY_RUN = False                              # True = never write files

client = OpenAI(base_url=OLLAMA_BASE_URL, api_key="ollama", timeout=60.0)

MAX_CHARS_FULL_READ = 8_000
MAX_CHUNK_LINES = 120
IGNORE_DIRS = {".git", "__pycache__", "node_modules", "venv", ".venv", "dist",
               "build", ".next", "target", ".idea", ".vscode", "coverage", ".tox"}
SUPPORTED_EXTENSIONS = {".py", ".js", ".ts", ".tsx", ".jsx", ".go", ".rs",
                        ".java", ".cpp", ".c", ".h", ".rb", ".php", ".svelte", ".vue",
                        ".tf", ".tfvars", ".yaml", ".yml"}

PLACEHOLDER_PATTERNS = (
    "<proposed-changes>",
    "<your-code-here>",
    "<insert-code>",
    "TODO: replace with actual",
)

TOOL_ALIASES = {
    "list_repo_files": "list_files",
    "lint": "run_linter",
    "run_lint": "run_linter",
    "git_status": "get_git_status",
    "project_structure": "get_project_structure",
}

# ====================== LOW-LEVEL HELPERS ======================

def run_cmd(cmd: str, cwd: str = ".") -> str:
    blocked = ("git push", "gh pr create")
    if any(b in cmd for b in blocked):
        return f"Blocked '{cmd}': remote push/PR commands are disabled in automatic shell execution."

    env = os.environ.copy()
    env["GIT_TERMINAL_PROMPT"] = "0"
    env["GCM_INTERACTIVE"] = "never"

    try:
        result = subprocess.run(
            cmd,
            shell=True,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (result.stdout + result.stderr).strip()
        return out or "(no output)"
    except subprocess.TimeoutExpired:
        return f"Error: Command timed out after 30s: {cmd}"
    except Exception as e:
        return f"Error: {e}"

def is_git_repo() -> bool:
    return run_cmd("git rev-parse --is-inside-work-tree 2>/dev/null").strip() == "true"

def _suggest_matching_paths(target: str) -> List[str]:
    clean = target.lstrip("./")
    stem = Path(clean).name.lower()
    matches = []
    for path in Path(".").rglob("*"):
        if not path.is_file():
            continue
        if any(p in IGNORE_DIRS for p in path.parts):
            continue
        rel = str(path).lstrip("./")
        if stem and (stem in rel.lower() or path.suffix.lower() in {".tf", ".yaml", ".yml"}):
            matches.append(rel)
    return sorted(matches)[:15]

def _missing_path_message(path: str) -> str:
    suggestions = _suggest_matching_paths(path)
    hint = ""
    if suggestions:
        hint = " Matching/infra files in repo:\n- " + "\n- ".join(suggestions)
    return f"Error: '{path}' does not exist. Call list_files or get_project_structure to get exact paths.{hint}"

# ====================== TOOLS ======================

def list_repo_files() -> List[str]:
    files = []
    for path in Path(".").rglob("*"):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS:
            if any(p in IGNORE_DIRS for p in path.parts):
                continue
            files.append(str(path).lstrip("./"))
    return sorted(files)[:300]

def read_file(path: str) -> str:
    try:
        p = Path(path)
        if p.is_dir():
            return f"Error: '{path}' is a directory, not a file. Use list_files or get_project_structure."
        if not p.exists():
            return _missing_path_message(path)
        content = p.read_text(encoding="utf-8", errors="ignore")
        if len(content) > MAX_CHARS_FULL_READ:
            return (content[:MAX_CHARS_FULL_READ] +
                    f"\n\n... [TRUNCATED - file is {len(content)} chars. "
                    f"Use read_file_chunk for specific parts]")
        return content
    except Exception as e:
        return f"Error reading {path}: {e}"

def read_file_chunk(path: str, start_line: int = 1, num_lines: int = MAX_CHUNK_LINES) -> str:
    try:
        p = Path(path)
        if p.is_dir():
            return f"Error: '{path}' is a directory, not a file."
        if not p.exists():
            return _missing_path_message(path)
        lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        total = len(lines)
        safe_num = max(1, min(num_lines or MAX_CHUNK_LINES, MAX_CHUNK_LINES))
        start = max(0, (start_line or 1) - 1)
        end = min(total, start + safe_num)
        header = f"📄 {path}  |  lines {start+1}–{end} of {total}\n{'─'*60}\n"
        return header + "\n".join(lines[start:end])
    except Exception as e:
        return f"Error: {e}"

def write_file(path: str, content: str) -> str:
    if not path or not path.strip():
        return "❌ Failed to write: empty file path."

    p = Path(path)
    if path.endswith(("/", "\\")) or p.is_dir():
        return f"❌ Refused to write to directory path '{path}'. Specify a concrete file path."

    if not content.strip():
        return f"❌ Refused to write empty content to '{path}'."

    if any(pat in content for pat in PLACEHOLDER_PATTERNS):
        return f"❌ Refused to write placeholder content to '{path}'. Provide actual file content first."

    if DRY_RUN:
        return f"[DRY-RUN] Would write {len(content)} chars → {path}"

    try:
        if p.exists():
            backup = p.with_suffix(p.suffix + ".bak")
            backup.write_text(p.read_text(encoding="utf-8", errors="ignore"), encoding="utf-8")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"✅ Wrote {path} (backup created)"
    except Exception as e:
        return f"❌ Failed to write {path}: {e}"

def write_files(files: List[Dict[str, str]]) -> str:
    """Write multiple files at once. Only after explicit confirmation."""
    if not files:
        return "No files provided."
    results = []
    for item in files:
        if not isinstance(item, dict):
            results.append(f"Invalid item: {item}")
            continue
        path = item.get("path")
        content = item.get("content")
        if not path or content is None:
            results.append(f"Invalid item: {item}")
            continue
        results.append(write_file(path, content))
    return "\n".join(results)

def get_git_status() -> str:
    if not is_git_repo():
        return "Not a git repository."
    branch = run_cmd("git branch --show-current")
    status = run_cmd("git status --short")
    diffstat = run_cmd("git diff --stat HEAD")
    log = run_cmd("git log --oneline -6")
    return f"Branch: {branch}\n\nStatus:\n{status}\n\nDiffstat:\n{diffstat}\n\nLog:\n{log}"

def create_branch(branch_name: str = None) -> str:
    if not is_git_repo():
        return "Not a git repository."
    if not branch_name:
        branch_name = f"ai-improve/{datetime.now().strftime('%Y%m%d-%H%M')}"
    if run_cmd(f"git branch --list {branch_name}").strip():
        run_cmd(f"git checkout {branch_name}")
        return f"Switched to existing branch: {branch_name}"
    result = run_cmd(f"git checkout -b {branch_name}")
    return f"Created & switched to branch: {branch_name}\n{result}"

def commit_changes(message: str) -> str:
    if not is_git_repo():
        return "Not a git repository."
    if DRY_RUN:
        return f"[DRY-RUN] Would commit: {message}"
    run_cmd("git add -A && git reset -- '*.bak' 2>/dev/null || true")
    safe_msg = message.replace('"', '\\"')
    return run_cmd(f'git commit -m "{safe_msg}"')

def show_diff(path: str = None) -> str:
    if path:
        return run_cmd(f"git diff -- {path}")
    return run_cmd("git diff") + "\n\n--- STAGED ---\n" + run_cmd("git diff --cached")

def export_patch(filename: str = "ai-improvements.patch") -> str:
    """Export current changes as a unified patch file."""
    diff = run_cmd("git diff") + "\n" + run_cmd("git diff --cached")
    if not diff.strip():
        return "No changes to export."
    Path(filename).write_text(diff, encoding="utf-8")
    return f"Patch saved to: {filename} ({len(diff)} bytes)"

def run_tests() -> str:
    """Try to detect and run the project's test suite."""
    results = []

    if any(Path(".").rglob("test_*.py")) or any(Path(".").rglob("*_test.py")) or Path("tests").exists():
        r = run_cmd("pytest -q --tb=no 2>/dev/null || python -m pytest -q --tb=no 2>/dev/null || true")
        results.append(f"pytest:\n{r[:2500]}")

    if Path("package.json").exists():
        r = run_cmd("npm test -- --watchAll=false 2>/dev/null || yarn test --watchAll=false 2>/dev/null || true")
        results.append(f"npm/yarn test:\n{r[:2000]}")

    if any(Path(".").rglob("*_test.go")):
        r = run_cmd("go test ./... 2>/dev/null || true")
        results.append(f"go test:\n{r[:2000]}")

    if Path("Cargo.toml").exists():
        r = run_cmd("cargo test 2>/dev/null || true")
        results.append(f"cargo test:\n{r[:2000]}")

    if not results:
        return "Could not detect a standard test runner."
    return "\n\n".join(results)

def create_pull_request(title: str, body: str = "") -> str:
    """Create a GitHub Pull Request using the GitHub CLI (gh)."""
    if not is_git_repo():
        return "Not a git repository."
    if DRY_RUN:
        return f"[DRY-RUN] Would create PR: {title}"

    branch = run_cmd("git branch --show-current").strip()
    if branch in {"main", "master"}:
        return "You are on main/master. Create a feature branch first."

    push = run_cmd(f"git push -u origin {branch}")

    body = body or "AI-assisted code improvements."
    with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as f:
        f.write(body)
        body_file = f.name

    cmd = f'gh pr create --title "{title}" --body-file "{body_file}"'
    result = run_cmd(cmd)
    os.unlink(body_file)
    return f"Push result:\n{push}\n\nPR result:\n{result}"

def run_linter() -> str:
    results = []
    if any(Path(".").rglob("*.py")):
        r = run_cmd("ruff check . --output-format=text 2>/dev/null || true")
        if r.strip():
            results.append(f"Ruff:\n{r[:3500]}")
    if Path("package.json").exists():
        r = run_cmd("npx eslint . --ext .js,.jsx,.ts,.tsx 2>/dev/null | head -60 || true")
        if r.strip():
            results.append(f"ESLint:\n{r}")
    return "\n\n".join(results) if results else "No linter issues found."

def get_project_structure() -> str:
    return run_cmd(
        "find . -maxdepth 4 -type f \\( -name '*.py' -o -name '*.js' -o -name '*.ts' -o -name '*.tsx' "
        "-o -name '*.go' -o -name '*.rs' -o -name '*.java' -o -name '*.tf' -o -name '*.tfvars' "
        "-o -name '*.yaml' -o -name '*.yml' \\) "
        "| grep -vE 'node_modules|__pycache__|venv|.venv|.git|dist|build|.terraform' | sort | head -150"
    )

# ====================== TOOL REGISTRY ======================

TOOLS = {
    "list_files": {"function": list_repo_files, "description": "List source and config files", "parameters": {"type": "object", "properties": {}, "required": []}},
    "read_file": {"function": read_file, "description": "Read full file (auto-truncates large ones)", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": ["path"]}},
    "read_file_chunk": {"function": read_file_chunk, "description": "Read specific lines from a large file", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "start_line": {"type": "integer"}, "num_lines": {"type": "integer"}}, "required": ["path"]}},
    "write_file": {"function": write_file, "description": "Write one file. ONLY after explicit user confirmation.", "parameters": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}},
    "write_files": {"function": write_files, "description": "Write multiple files at once after confirmation. Argument: list of {path, content}", "parameters": {"type": "object", "properties": {"files": {"type": "array", "items": {"type": "object", "properties": {"path": {"type": "string"}, "content": {"type": "string"}}, "required": ["path", "content"]}}}, "required": ["files"]}},
    "get_git_status": {"function": get_git_status, "description": "Detailed git status", "parameters": {"type": "object", "properties": {}, "required": []}},
    "create_branch": {"function": create_branch, "description": "Create and switch to a new branch", "parameters": {"type": "object", "properties": {"branch_name": {"type": "string"}}, "required": []}},
    "commit_changes": {"function": commit_changes, "description": "git add + commit", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}, "required": ["message"]}},
    "show_diff": {"function": show_diff, "description": "Show current diff", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}, "required": []}},
    "export_patch": {"function": export_patch, "description": "Save current changes as a .patch file", "parameters": {"type": "object", "properties": {"filename": {"type": "string"}}, "required": []}},
    "run_tests": {"function": run_tests, "description": "Detect and run the project test suite", "parameters": {"type": "object", "properties": {}, "required": []}},
    "create_pull_request": {"function": create_pull_request, "description": "Create a GitHub Pull Request using gh CLI", "parameters": {"type": "object", "properties": {"title": {"type": "string"}, "body": {"type": "string"}}, "required": ["title"]}},
    "run_linter": {"function": run_linter, "description": "Run linters", "parameters": {"type": "object", "properties": {}, "required": []}},
    "get_project_structure": {"function": get_project_structure, "description": "Project structure overview", "parameters": {"type": "object", "properties": {}, "required": []}},
    "run_command": {"function": run_cmd, "description": "Run non-interactive shell command", "parameters": {"type": "object", "properties": {"cmd": {"type": "string"}}, "required": ["cmd"]}},
}

def resolve_tool_name(name: str) -> str:
    if name in TOOLS:
        return name
    return TOOL_ALIASES.get(name, name)

def get_openai_tools():
    return [{"type": "function", "function": {"name": n, "description": t["description"], "parameters": t["parameters"]}} for n, t in TOOLS.items()]

def extract_text_tool_calls(content: str) -> List[Tuple[str, Dict[str, Any]]]:
    """Fallback parser if a local model outputs JSON tool calls as plain text."""
    if not content or "{" not in content:
        return []
    found: List[Tuple[str, Dict[str, Any]]] = []
    decoder = json.JSONDecoder()
    idx = 0
    while idx < len(content):
        brace_idx = content.find("{", idx)
        if brace_idx == -1:
            break
        try:
            obj, end_idx = decoder.raw_decode(content[brace_idx:])
            idx = brace_idx + end_idx
            raw_name = obj.get("name") if isinstance(obj, dict) else None
            resolved = resolve_tool_name(raw_name) if isinstance(raw_name, str) else None
            if resolved and resolved in TOOLS:
                args = obj.get("arguments")
                if isinstance(args, str):
                    try:
                        args = json.loads(args)
                    except Exception:
                        args = {}
                if not isinstance(args, dict):
                    args = {}
                found.append((resolved, args))
        except Exception:
            idx = brace_idx + 1
    return found

# ====================== AGENT ======================

class CodeImprovementAgent:
    def __init__(self):
        self.messages = []
        dry = "\n\n⚠️  CURRENT MODE: DRY-RUN (no files will be modified)" if DRY_RUN else ""
        self.system_prompt = f"""You are a senior software engineer helping improve a local codebase.{dry}

Strict rules:
1. NEVER call write_file, write_files, create_branch, commit_changes, or create_pull_request unless the user explicitly asks for or confirms that action.
2. When asked to analyze or propose improvements without writing files, only inspect/read/lint/check status and return a concrete written proposal.
3. Call list_files or get_project_structure first if you are unsure of exact file paths. Never guess paths.
4. For large files always use read_file_chunk.
5. Always pass actual file paths and complete, real code—never directory paths or placeholders like "<proposed-changes>".
6. Do not repeat identical tool calls if they already returned no output or the same result.

Recommended workflow:
Explore → Lint → Read key files → Propose improvements → Wait for confirmation → 
Create branch → Write files → Run tests → Commit → (PR or patch)
"""

    def _execute_tool_call(self, name: str, args: Dict[str, Any], call_id: str) -> None:
        resolved_name = resolve_tool_name(name)
        display = {k: (f"[{len(v)} files]" if k == "files" else
                       (v[:70] + "..." if isinstance(v, str) and len(v) > 70 else v))
                   for k, v in args.items()}
        print(f"→ {resolved_name}({display})")

        result = TOOLS[resolved_name]["function"](**args) if resolved_name in TOOLS else f"Unknown tool {name}"
        result_str = str(result)
        if len(result_str) > 6000:
            result_str = result_str[:6000] + "\n... [truncated]"
        print(f"← {len(result_str)} chars")

        self.messages.append({
            "role": "tool",
            "tool_call_id": call_id,
            "name": resolved_name,
            "content": result_str
        })

    def _dispatch_calls(self, calls: List[Tuple[str, Dict[str, Any], str]], seen_calls: set) -> int:
        executed = 0
        for name, args, call_id in calls:
            resolved_name = resolve_tool_name(name)
            call_sig = (resolved_name, json.dumps(args, sort_keys=True, default=str))
            if call_sig in seen_calls:
                print(f"↺ Skipped duplicate {resolved_name}")
                self.messages.append({
                    "role": "tool",
                    "tool_call_id": call_id,
                    "name": resolved_name,
                    "content": "You ALREADY have the full output of this tool call earlier in this conversation. Do NOT call any more tools—write your final answer right now using the output you already received."
                })
                continue
            seen_calls.add(call_sig)
            self._execute_tool_call(resolved_name, args, call_id)
            executed += 1
        return executed

    def chat(self, user_message: str, max_steps: int = 8) -> str:
        if not self.messages:
            self.messages.append({"role": "system", "content": self.system_prompt})
        self.messages.append({"role": "user", "content": user_message})
        seen_calls = set()

        for step in range(max_steps):
            print(f"\n{'═'*64}\n Step {step+1}\n{'═'*64}")

            try:
                response = client.chat.completions.create(
                    model=MODEL,
                    messages=self.messages,
                    tools=get_openai_tools(),
                    tool_choice="auto",
                    temperature=0.1,
                )
            except Exception as e:
                print(f"Ollama error: {e}")
                return f"Error talking to Ollama: {e}"

            message = response.choices[0].message

            if message.tool_calls:
                self.messages.append({
                    "role": "assistant",
                    "content": message.content or "",
                    "tool_calls": [{
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments}
                    } for tc in message.tool_calls]
                })

                parsed_calls = []
                for tc in message.tool_calls:
                    try:
                        args = json.loads(tc.function.arguments or "{}")
                    except Exception:
                        args = {}
                    parsed_calls.append((tc.function.name, args, tc.id))

                self._dispatch_calls(parsed_calls, seen_calls)
            else:
                raw_content = message.content or ""
                fallback_calls = extract_text_tool_calls(raw_content)
                if fallback_calls:
                    self.messages.append({"role": "assistant", "content": raw_content})
                    indexed_calls = [
                        (name, args, f"fallback_{step}_{idx}")
                        for idx, (name, args) in enumerate(fallback_calls)
                    ]
                    self._dispatch_calls(indexed_calls, seen_calls)
                    continue

                print("\n" + raw_content)
                self.messages.append({"role": "assistant", "content": raw_content})
                return raw_content

        self.messages.append({
            "role": "user",
            "content": "Step limit reached. Provide a concise summary of what actions were taken and what remains."
        })
        try:
            wrap_response = client.chat.completions.create(
                model=MODEL,
                messages=self.messages,
                temperature=0.1,
            )
            summary = (wrap_response.choices[0].message.content or "").strip() or "Max steps reached."
        except Exception:
            summary = "Max steps reached."

        print("\n" + summary)
        self.messages.append({"role": "assistant", "content": summary})
        return summary

# ====================== 2D PIXEL OFFICE CANVAS (Gradio 6) ======================

OFFICE_HTML_TEMPLATE = """
<div id="pixel-office-wrap" style="background:#0f172a;border:2px solid #38bdf8;border-radius:14px;padding:12px;
            box-shadow:0 10px 25px rgba(0,0,0,0.45);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
            position:relative;z-index:20;">
  <style>
    #pixel-office-wrap,
    #pixel-office-wrap *,
    #pixel-office-wrap.pending,
    #pixel-office-wrap .pending {
      opacity: 1 !important;
      filter: none !important;
      backdrop-filter: none !important;
    }
  </style>
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;padding:0 4px;">
    <div style="display:flex;align-items:center;gap:8px;">
      <span id="status-dot" style="width:10px;height:10px;border-radius:2px;background:#4ade80;display:inline-block;"></span>
      <span style="color:#f8fafc;font-weight:700;font-size:13px;letter-spacing:0.06em;">AGENT HQ // 2D PIXEL OFFICE</span>
    </div>
    <span id="status-badge" style="font-size:11px;padding:2px 8px;border-radius:4px;background:#1e293b;color:#4ade80;border:1px solid #334155;">
      IDLE • PATROLLING OFFICE
    </span>
  </div>
  <canvas id="office-canvas" width="320" height="240"
          style="width:100%;height:560px;image-rendering:pixelated;border-radius:8px;
                 background:#1e1b2e;display:block;border:1px solid #334155;"></canvas>
  <div style="display:flex;justify-content:space-between;color:#cbd5e1;font-size:11px;margin-top:8px;padding:0 4px;">
    <span>🪑 Workstation: Dual-Monitor Dev Rig</span>
    <span>☕ Coffee &amp; Server Rack Online</span>
  </div>
</div>
"""

OFFICE_JS_ON_LOAD = """
const canvas = element.querySelector('#office-canvas');
const ctx = canvas.getContext('2d');
const badge = element.querySelector('#status-badge');
const dot = element.querySelector('#status-dot');

ctx.imageSmoothingEnabled = false;

const host = element.closest('.block, .gr-html, [class*="html"]') || element.parentElement;
if (host) {
  const styleTag = document.createElement('style');
  styleTag.textContent = `
    .pending, [data-testid="pending"], .generating {
      opacity: 1 !important;
    }
  `;
  document.head.appendChild(styleTag);
}

let currentState = props.value || 'idle';

function syncStatusUI(st) {
  if (st === 'working') {
    badge.textContent = 'WORKING • TYPING AT DESK';
    badge.style.color = '#38bdf8';
    badge.style.borderColor = '#38bdf8';
    dot.style.background = '#38bdf8';
    dot.style.boxShadow = '0 0 8px #38bdf8';
  } else {
    badge.textContent = 'IDLE • PATROLLING OFFICE';
    badge.style.color = '#4ade80';
    badge.style.borderColor = '#4ade80';
    dot.style.background = '#4ade80';
    dot.style.boxShadow = '0 0 8px #4ade80';
  }
}
syncStatusUI(currentState);

if (typeof watch === 'function') {
  watch('value', () => {
    currentState = props.value || 'idle';
    syncStatusUI(currentState);
  });
}

const deskSpot = { x: 168, y: 122 };
const patrolSpots = [
  { x: 74, y: 146 },
  { x: 245, y: 156 },
  { x: 132, y: 172 },
  { x: 168, y: 122 }
];
let patrolIdx = 0;
let idleTimer = 0;

const agent = {
  x: 168,
  y: 122,
  dir: 'down',
  frame: 0,
  typing: false
};

const particles = [];

function px(x, y, w, h, color) {
  ctx.fillStyle = color;
  ctx.fillRect(Math.round(x), Math.round(y), Math.round(w), Math.round(h));
}

function drawRoom(tick) {
  px(0, 0, 320, 92, '#28253b');
  px(0, 88, 320, 4, '#181626');

  for (let x = 8; x < 320; x += 24) {
    px(x, 0, 2, 88, '#2f2b45');
  }

  for (let y = 92; y < 240; y += 16) {
    for (let x = 0; x < 320; x += 16) {
      const even = ((x / 16) + (y / 16)) % 2 === 0;
      px(x, y, 16, 16, even ? '#36324a' : '#312d44');
    }
  }

  px(26, 16, 68, 52, '#131629');
  px(24, 14, 72, 2, '#64748b');
  px(24, 68, 72, 3, '#94a3b8');
  px(24, 14, 2, 54, '#64748b');
  px(94, 14, 2, 54, '#64748b');
  px(59, 16, 2, 52, '#475569');
  px(36, 24, 2, 2, tick % 60 < 30 ? '#fef08a' : '#94a3b8');
  px(78, 28, 2, 2, tick % 80 < 40 ? '#e0f2fe' : '#64748b');
  px(46, 36, 1, 1, '#ffffff');
  px(28, 50, 12, 18, '#1e293b');
  px(42, 44, 14, 24, '#0f172a');
  px(64, 48, 12, 20, '#1e293b');
  px(78, 42, 14, 26, '#0f172a');
  px(46, 48, 2, 2, '#facc15');
  px(82, 47, 2, 2, '#38bdf8');

  px(12, 74, 26, 56, '#1e293b');
  px(14, 76, 22, 52, '#0f172a');
  for (let sy = 80; sy < 120; sy += 9) {
    px(16, sy, 18, 6, '#1e293b');
    const blink = ((tick + sy) % 24) < 12;
    px(18, sy + 2, 2, 2, blink ? '#4ade80' : '#15803d');
    px(22, sy + 2, 2, 2, currentState === 'working' && !blink ? '#38bdf8' : '#0284c7');
  }

  px(44, 96, 30, 34, '#78350f');
  px(42, 94, 34, 4, '#92400e');
  px(49, 78, 16, 16, '#cbd5e1');
  px(52, 82, 10, 6, '#0f172a');
  px(55, 89, 4, 4, '#ef4444');
  const steamOff = Math.floor(tick / 15) % 3;
  px(56, 74 - steamOff, 2, 2, 'rgba(255,255,255,0.65)');

  px(244, 34, 52, 74, '#5c2d16');
  px(247, 37, 46, 68, '#3f1d0b');
  const bookColors = ['#ef4444', '#3b82f6', '#eab308', '#10b981', '#a855f7', '#f97316'];
  for (let shelf = 0; shelf < 3; shelf++) {
    const sy = 54 + shelf * 22;
    px(247, sy, 46, 3, '#78350f');
    for (let b = 0; b < 8; b++) {
      px(250 + b * 5, sy - 12, 4, 12, bookColors[(b + shelf * 2) % bookColors.length]);
    }
  }

  px(286, 126, 16, 14, '#b45309');
  px(284, 124, 20, 3, '#d97706');
  px(288, 112, 4, 12, '#16a34a');
  px(294, 108, 4, 16, '#22c55e');
  px(283, 115, 5, 6, '#15803d');
  px(298, 114, 5, 7, '#16a34a');

  px(108, 152, 116, 56, '#27243b');
  px(112, 156, 108, 48, '#312e59');
  px(116, 160, 100, 40, '#27243b');
}

function drawDeskAndMonitors(tick) {
  px(158, 128, 20, 14, '#1e293b');
  px(160, 126, 16, 12, '#3b82f6');
  px(166, 142, 4, 8, '#0f172a');
  px(160, 149, 16, 2, '#60a5fa');

  px(116, 98, 104, 8, '#d97706');
  px(116, 106, 104, 4, '#92400e');
  px(120, 110, 6, 28, '#451a03');
  px(210, 110, 6, 28, '#451a03');

  px(132, 74, 32, 20, '#0f172a');
  px(134, 76, 28, 16, '#020617');
  px(146, 94, 4, 4, '#60a5fa');

  px(170, 74, 34, 20, '#0f172a');
  px(172, 76, 30, 16, '#020617');
  px(185, 94, 4, 4, '#60a5fa');

  const codeSpeed = currentState === 'working' ? 4 : 18;
  const scroll = Math.floor(tick / codeSpeed);
  const lineColors = ['#38bdf8', '#4ade80', '#facc15', '#f472b6', '#a78bfa'];

  for (let i = 0; i < 4; i++) {
    const c1 = lineColors[(i + scroll) % lineColors.length];
    const w1 = 8 + ((i * 7 + scroll * 3) % 16);
    px(136, 78 + i * 3, w1, 2, c1);

    const c2 = lineColors[(i + scroll + 2) % lineColors.length];
    const w2 = 10 + ((i * 5 + scroll * 5) % 16);
    px(174, 78 + i * 3, w2, 2, c2);
  }

  px(156, 100, 22, 4, '#cbd5e1');
  px(182, 101, 4, 3, '#38bdf8');
  px(202, 93, 6, 6, '#f43f5e');
}

function drawAgent(tick) {
  const x = Math.round(agent.x);
  const y = Math.round(agent.y);
  const isMoving = agent.frame > 0;
  const isWorking = currentState === 'working';
  const bob = agent.typing ? (tick % 8 < 4 ? 0 : -1) : (isMoving ? (Math.floor(tick / 6) % 2) : (tick % 40 < 20 ? 0 : -1));

  if (isWorking) {
    ctx.fillStyle = 'rgba(56, 189, 248, 0.25)';
    ctx.beginPath();
    ctx.arc(x, y + 6, 13, 0, Math.PI * 2);
    ctx.fill();
  }

  px(x - 7, y + 11, 14, 4, 'rgba(0,0,0,0.45)');

  const stepOff = isMoving ? (Math.floor(tick / 6) % 2 === 0 ? -1 : 1) : 0;
  px(x - 5, y + 6 + stepOff, 4, 6, '#1d4ed8');
  px(x + 1, y + 6 - stepOff, 4, 6, '#1d4ed8');
  px(x - 5, y + 11 + stepOff, 4, 1, '#38bdf8');
  px(x + 1, y + 11 - stepOff, 4, 1, '#38bdf8');

  px(x - 7, y - 3 + bob, 14, 10, '#1d4ed8');
  px(x - 5, y - 2 + bob, 10, 8, '#3b82f6');
  px(x - 5, y - 2 + bob, 10, 2, '#60a5fa');
  px(x - 1, y + 1 + bob, 2, 2, isWorking ? '#facc15' : '#4ade80');

  if (agent.typing) {
    const leftArmY = tick % 6 < 3 ? -3 : -1;
    const rightArmY = tick % 6 >= 3 ? -3 : -1;
    px(x - 9, y + leftArmY, 3, 5, '#38bdf8');
    px(x + 6, y + rightArmY, 3, 5, '#38bdf8');
  } else {
    px(x - 9, y - 2 + bob - stepOff, 3, 6, '#38bdf8');
    px(x + 6, y - 2 + bob + stepOff, 3, 6, '#38bdf8');
  }

  px(x - 7, y - 14 + bob, 14, 11, '#f8fafc');
  px(x - 6, y - 15 + bob, 12, 1, '#38bdf8');

  px(x - 1, y - 18 + bob, 2, 3, '#facc15');
  px(x - 1, y - 20 + bob, 2, 2, isWorking ? '#38bdf8' : '#4ade80');

  px(x - 5, y - 12 + bob, 10, 6, '#090d16');
  const eyeColor = isWorking ? '#38bdf8' : '#4ade80';
  const accentEye = isWorking ? '#facc15' : '#a7f3d0';
  const blink = tick % 90 > 85;
  if (!blink) {
    px(x - 4, y - 10 + bob, 3, 2, eyeColor);
    px(x + 1, y - 10 + bob, 3, 2, accentEye);
  } else {
    px(x - 4, y - 9 + bob, 3, 1, eyeColor);
    px(x + 1, y - 9 + bob, 3, 1, accentEye);
  }

  px(x - 8, y - 12 + bob, 2, 6, isWorking ? '#f472b6' : '#38bdf8');
  px(x + 6, y - 12 + bob, 2, 6, isWorking ? '#f472b6' : '#38bdf8');
}

function updateAgent(tick) {
  let target = deskSpot;

  if (currentState === 'working') {
    target = deskSpot;
  } else {
    target = patrolSpots[patrolIdx];
  }

  const dx = target.x - agent.x;
  const dy = target.y - agent.y;
  const dist = Math.hypot(dx, dy);

  if (dist > 1.5) {
    const speed = currentState === 'working' ? 1.8 : 0.85;
    agent.x += (dx / dist) * speed;
    agent.y += (dy / dist) * speed;
    agent.frame++;
    agent.typing = false;

    if (Math.abs(dx) > Math.abs(dy)) {
      agent.dir = dx > 0 ? 'right' : 'left';
    } else {
      agent.dir = dy > 0 ? 'down' : 'up';
    }
  } else {
    agent.x = target.x;
    agent.y = target.y;
    agent.frame = 0;

    if (currentState === 'working') {
      agent.dir = 'down';
      agent.typing = true;
      if (tick % 14 === 0) {
        const glyphs = ['{ }', '</>', '01', 'git', 'fn()', '✓'];
        particles.push({
          x: agent.x + (Math.random() * 26 - 13),
          y: agent.y - 24,
          text: glyphs[Math.floor(Math.random() * glyphs.length)],
          life: 45
        });
      }
    } else {
      agent.dir = 'down';
      agent.typing = false;
      idleTimer++;
      if (idleTimer > 150) {
        idleTimer = 0;
        patrolIdx = (patrolIdx + 1) % patrolSpots.length;
      }
    }
  }
}

function drawParticles() {
  ctx.font = 'bold 8px monospace';
  for (let i = particles.length - 1; i >= 0; i--) {
    const p = particles[i];
    p.y -= 0.45;
    p.life--;
    ctx.fillStyle = `rgba(56, 189, 248, ${Math.max(0, p.life / 45)})`;
    ctx.fillText(p.text, Math.round(p.x), Math.round(p.y));
    if (p.life <= 0) particles.splice(i, 1);
  }
}

let tick = 0;
function loop() {
  tick++;
  ctx.clearRect(0, 0, canvas.width, canvas.height);
  drawRoom(tick);
  updateAgent(tick);

  if (agent.y <= 122) {
    drawAgent(tick);
    drawDeskAndMonitors(tick);
  } else {
    drawDeskAndMonitors(tick);
    drawAgent(tick);
  }

  drawParticles();
  requestAnimationFrame(loop);
}

loop();
"""

# ====================== GRADIO UI (Gradio 6 compatible) ======================

def launch_ui():
    try:
        import gradio as gr
    except ImportError:
        print("Gradio not installed. Run: pip install gradio")
        sys.exit(1)

    agent = CodeImprovementAgent()

    def start_working(message, history):
        if not message or not message.strip():
            return history, "idle"
        history = history + [{"role": "user", "content": message}]
        return history, "working"

    def respond(message, history):
        if not message or not message.strip():
            return history, "idle"
        response = agent.chat(message)
        history = history + [{"role": "assistant", "content": response}]
        return history, "idle"

    def clear_chat():
        agent.messages = []
        return [], "idle"

    with gr.Blocks(title="Code Improvement Agent") as demo:
        gr.Markdown("# Local Code Improvement Agent (Ollama)")
        gr.Markdown(f"**Model:** `{MODEL}` &nbsp;&nbsp;|&nbsp;&nbsp; **Dry-run:** `{DRY_RUN}`")

        with gr.Row(equal_height=True):
            with gr.Column(scale=1):
                chatbot = gr.Chatbot(height=520)
                msg = gr.Textbox(
                    placeholder="Ask me to analyze the repo, propose improvements, apply changes...",
                    label="Message",
                )
                with gr.Row():
                    submit = gr.Button("Send", variant="primary")
                    clear = gr.Button("Clear conversation")

            with gr.Column(scale=1):
                pixel_office = gr.HTML(
                    value="idle",
                    html_template=OFFICE_HTML_TEMPLATE,
                    js_on_load=OFFICE_JS_ON_LOAD,
                    show_progress="hidden",
                )

        submit.click(
            start_working, inputs=[msg, chatbot], outputs=[chatbot, pixel_office], show_progress="hidden"
        ).then(
            respond, inputs=[msg, chatbot], outputs=[chatbot, pixel_office], show_progress="hidden"
        ).then(
            lambda: "", None, msg
        )

        msg.submit(
            start_working, inputs=[msg, chatbot], outputs=[chatbot, pixel_office], show_progress="hidden"
        ).then(
            respond, inputs=[msg, chatbot], outputs=[chatbot, pixel_office], show_progress="hidden"
        ).then(
            lambda: "", None, msg
        )

        clear.click(clear_chat, outputs=[chatbot, pixel_office], show_progress="hidden")

    print("\nLaunching web UI → http://127.0.0.1:7860")
    demo.launch(
        server_name="127.0.0.1",
        server_port=7860,
        share=False,
        theme=gr.themes.Soft()
    )

# ====================== MAIN ======================

def main():
    global DRY_RUN

    print("=" * 64)
    print("  Ultimate Code Improvement Agent")
    print("=" * 64)

    if "--dry-run" in sys.argv:
        DRY_RUN = True
        sys.argv.remove("--dry-run")
        print("→ Dry-run mode enabled")

    if "--ui" in sys.argv:
        sys.argv.remove("--ui")
        launch_ui()
        return

    # CLI mode
    print(f"Model    : {MODEL}")
    print(f"Directory: {os.getcwd()}")
    print(f"Dry-run  : {DRY_RUN}")
    print("-" * 64)

    try:
        client.models.list()
    except Exception:
        print("\n❌ Cannot connect to Ollama. Run `ollama serve` and pull a model.")
        sys.exit(1)

    agent = CodeImprovementAgent()

    args = sys.argv[1:]
    goal = " ".join(args) if args else (
        "Analyze this repository. Start with structure, git status and linters. "
        "Then examine the most important files and propose the highest-value improvements. "
        "Do not write any files until I explicitly confirm."
    )

    print(f"\nGoal: {goal}\n")
    agent.chat(goal)

    print("\n" + "=" * 64)
    print("Continue the conversation. Useful phrases:")
    print("  • yes, create a branch and apply all changes")
    print("  • run the tests")
    print("  • commit and create a pull request")
    print("  • export a patch file")
    print("  • exit")
    print("=" * 64)

    while True:
        try:
            user_input = input("\nYou: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nBye!")
            break
        if not user_input:
            continue
        if user_input.lower() in {"exit", "quit", "q"}:
            print("Bye!")
            break
        agent.chat(user_input)

if __name__ == "__main__":
    main()