# Worktree 隔离 Spec

## 背景

ch13 SubAgent 隔离了消息、权限决策状态、文件读缓存和 token 计数,但 **文件系统**仍然共享。主 Agent 和后台子 Agent(以及下一章要做的 Agent Team 队员)会在同一时刻并发读写同一份工作目录的文件,出现读到对方写了一半的文件、互相覆盖修改等并行冲突——本质就是经典的并行开发文件冲突,和两个程序员同时改同一份文件一样。

Git 分支只能做**时间维度**的隔离(切换分支时工作目录被覆盖,同一时刻只有一个工作目录),不能解决并行问题;切分支还会刷被切文件的 mtime,触发依赖追踪型构建工具的链式重编。

需要的是**空间维度**的隔离:同一仓库同时挂多个工作目录、共享版本库、各自一个分支。这就是 Git Worktree (Git 2.5+) 的能力。本章在 Arkcode 中封装一层 Worktree 管理逻辑,把这块拼图补给 SubAgent,让后台 / 并行场景安全可用。

Arkcode 现有相关基础设施:
- ch13 SubAgent 已支持 frontmatter (`src/Arkcode/subagent/parser.py`),解析 `name/description/tools/disallowed_tools/model/max_turns/permission_mode/background` 等字段
- ch13 `agent.AgentTool.execute` 已是子 Agent 启动入口,本章在此处插桩 isolation 分支
- ch08 文件读缓存以绝对路径作为 key
- ch10 `src/Arkcode/command` 已有 slash 命令注册系统
- `.gitignore` 已忽略 `.Arkcode/sessions/` 等子目录,本章扩展把 `.Arkcode/worktrees/` 也忽略
- Tool 接口 `execute(ctx, args) -> Result` 现支持 ctx 携带值(已有 `ctx_key_conv` / `ctx_key_subagent_depth` 范式,Python 用 `contextvars.ContextVar` 实现),可作为 explicit cwd 的传递通道

本章不引入 Worktree 间合并策略、跨目录代码同步、多 Agent 并行编排,这些属于上层 / 下一章范畴。

## 目标

- **G1**: 提供 `WorktreeManager` 封装 Worktree 完整生命周期——创建、快速恢复、进入、退出、删除;并发场景下用单一 `asyncio.Lock` 保护内部 `active` 映射
- **G2**: 名字 (slug) 严格安全校验——限字符集 `[a-zA-Z0-9._-]`、总长度上限 64、显式拒绝 `.` 和 `..` 段名、允许 `/` 做嵌套分隔;防 LLM 输入触发路径遍历
- **G3**: Worktree 目录统一落在仓库内不被追踪的位置 `.Arkcode/worktrees/<flat_slug>/`,分支名前缀 `worktree-<flat_slug>`,嵌套 slug 的 `/` 替换为 `+` 避免 Git D/F 冲突
- **G4**: 创建后做三类环境初始化——A 复制本地配置 (`.Arkcode/config.yaml` / `.Arkcode/settings.local.yaml`)、B 按显式配置建立只读共享依赖目录、C 按项目根 `.worktreeinclude` 复制被忽略但运行需要的文件;均为 best-effort,失败只警告不中断创建。共享目录只有在权限沙箱能阻止写穿透时才建立,否则跳过。本期跳过 Git hooks 设置,不读取也不修改 `core.hooksPath`
- **G5**: 快速恢复——每个 Worktree 在 `<worktree_dir>/.metadata/<flat_slug>.json` 持久化 ArkCode manifest;目录已存在时,仅读 manifest + `.git` 指针 + `HEAD` + `refs/` 完成身份校验并恢复,不调任何 git 子进程。manifest 缺失、仓库身份/路径/分支不匹配时拒绝恢复,不猜测元数据
- **G6**: 主进程与 in-process Agent 进入 Worktree 时禁止调用 `os.chdir`——把 `cwd` 与 `workspace_root` 记到会话状态并通过 ctx 传给工具调用;Bash / Read / Write / Edit / Glob / Grep 工具显式在 Worktree 里执行。文件工具对 realpath 做 containment 校验,拒绝指向 Worktree 外的绝对路径、`..` 或 symlink 逃逸。独立 Pane 子进程的启动例外由 Agent Team 规格定义
- **G7**: 文件读缓存等以绝对路径为 key 的缓存,天然按目录隔离;进入 / 退出 Worktree **不需要清缓存**
- **G8**: 退出时变更保护——`action="remove"` 且未显式 `discard_changes=True` 时,检测到未提交修改或本地多于 base 的 commit 一律拒绝删除;退出只清除 session/ctx 状态,进程 cwd 始终不变
- **G9**: 自动清理 (`auto_cleanup`)——SubAgent 退出时,无变更则直接 remove,有变更则保留 Worktree 路径与分支名追加到 SubAgent 结果文本给主 Agent review
- **G10**: 后台过期 Worktree 清理——按命名模式 (`agent-a[0-9a-f]{7}`) 只识别临时 Worktree,叠加时间过滤(超过 cutoff 才考虑),最后做 fail-closed 变更检查(有未提交修改 / 未推送 commit 都保留)
- **G11**: `WorktreeSession` 持久化到 `.Arkcode/worktree_session.json`,Arkcode 启动时读取并校验目录仍存在;退出时清空文件而不是删文件,确保下次启动不误恢复
- **G12**: 在 `subagent.Definition` 增加 `isolation` 字段 (`""` / `"worktree"`);SubAgent 启动器检测到 `isolation:worktree` 后,自动 `create → inject worktree notice → set ctx cwd → run_to_completion → auto_cleanup`,无需在 prompt / 工具调用里显式指定
- **G13**: 提供 TUI slash 命令 `/worktree create <slug>`、`/worktree list`、`/worktree exit [--remove]`、`/worktree remove <slug> [--discard]`——让用户手动管理;手动创建的 Worktree **不走自动清理**
- **G14**: 与 ch04~ch13 协同——主 Agent 看到的工具列表不变(ctx 注入不改 schema)、prompt cache 不抖动、既有测试不破坏
- **G15**: `background:true + isolation:worktree` 为本期正式能力——Agent 工具立即返回 job_id,后台 runner 负责 `create → run → auto_cleanup`;创建、执行、取消、失败任一终态都产生通知,且只清理经过 manifest 验证属于本 job 的资源

## 功能需求

### Slug 验证

- **F1**: `worktree.validate_slug(name)` 校验规则——
  - name 非空,总长度 ≤ 64
  - 按 `/` 切段,每段必须匹配正则 `^[a-zA-Z0-9._-]+$` 且不能是 `.` 或 `..`
  - 不允许出现连续 `//`、首末 `/`
  - 失败时抛 `ValueError` 携带具体原因

### WorktreeManager 与核心数据结构

- **F2**: `worktree.Worktree`(dataclass)记录单个 Worktree 的元信息——`name`(原始 slug)、`path`(绝对路径)、`branch`(`worktree-<flat_slug>`)、`based_on`(创建时的 base 引用,如 `HEAD` 或具体 commit)、`base_commit`(创建前解析出的不可变 base SHA)、`created`(datetime)、`manual`(bool,是否用户手动创建,影响 auto_cleanup 跳过判断)、`owner_job_id`(后台 job 创建时填写,手动创建为空)
- **F3**: `worktree.WorktreeSession`(dataclass)记录当前活跃的 Worktree 会话——`original_cwd`、`worktree_path`、`worktree_name`(原 slug)、`original_branch`、`original_head_commit`、`session_id`(UUID 字符串)、`hook_based`(bool,预留)
- **F4**: `worktree.Manager` 内部字段——`repo_root`(绝对路径)、`repo_common_dir`(`git rev-parse --git-common-dir` 的 realpath)、`repo_id`(`sha256(repo_common_dir)[:16]`)、`worktree_dir`(`<repo_root>/.Arkcode/worktrees`)、`metadata_dir`(`<worktree_dir>/.metadata`)、`session_file`(`<repo_root>/.Arkcode/worktree_session.json`)、`lock: asyncio.Lock`、`active: dict[str, Worktree]`、`current_session: WorktreeSession | None`
- **F5**: `worktree.Manager(repo_root: str)` 构造时(或工厂函数 `Manager.create(repo_root)`)——
  - 校验 `repo_root` 是 git 仓库根目录(`git rev-parse --show-toplevel` 输出与之等);失败抛异常,Arkcode 启动允许降级到「Worktree 功能未启用」
  - 创建 `worktree_dir` 目录(如不存在)
  - 从 `session_file` 反序列化 `current_session`(允许文件不存在);恢复前校验 session 指向的 Worktree manifest/repo_id/path,目录不存在或身份不匹配时清空 session 文件并把 `current_session=None`
  - 扫描 `metadata_dir/*.json`,逐个按 F6 的身份校验恢复 `active`;没有合法 manifest 的目录不加入映射,仅 stderr 警告
- **F6**: `Manager.create(name: str, base_ref: str, manual: bool, owner_job_id: str = "") -> Worktree`(async)——
  - 1. `validate_slug(name)` 不通过即抛异常
  - 2. `async with self.lock:`,若 `active[name]` 已存在,抛异常
  - 3. `flat_slug = name.replace("/", "+")`、`wt_path = self.worktree_dir / flat_slug`、`branch_name = f"worktree-{flat_slug}"`
  - 4. 快速恢复路径优先:仅在 `wt_path` 与 manifest 同时存在时启用,校验 `schema_version/repo_id/name/path/branch/base_ref/base_commit/manual/owner_job_id`,再校验 `.git` 指向同一 `repo_common_dir` 且 HEAD 指向预期 branch;全部匹配才构造 `Worktree` 返回,本路径不启动 git 子进程;否则抛 `WorktreeIdentityError`
  - 5. 非恢复路径执行 `git rev-parse <base_ref>` 得 `base_commit`,再用 `git worktree add -b <branch> <wt_path> <base_commit>` 新建;已存在同名分支或路径时不自动 reset
  - 6. 新建成功后执行创建后设置 `_perform_post_creation_setup` (F7-F10),任何子步骤失败仅 stderr 警告,不中断
  - 7. 构造 `Worktree(name, path, branch, based_on, base_commit, created, manual, owner_job_id)`,把 manifest 以唯一临时文件 + `flush/fsync/os.replace` 原子写入 `metadata_dir`
  - 8. 加入 `active`,返回;步骤 4~7 失败时仅清理由本次调用新建且身份可确认的目录/分支/manifest
- **F6a**: manifest JSON 字段固定为 `schema_version/repo_id/repo_common_dir/name/path/branch/base_ref/base_commit/created_at/manual/owner_job_id`;未知 schema version 拒绝恢复。删除 Worktree 成功后同步删除 manifest;删除失败时保留 manifest 与错误信息供人工恢复
- **F7**: 创建后设置 A——复制本地配置文件,从 `<repo_root>/.Arkcode/config.yaml` 与 `<repo_root>/.Arkcode/settings.local.yaml` 复制到 Worktree 同位置(目标目录已存在跳过,文件不存在跳过)
- **F8**: 本期不设置 Git hooks——创建后设置不得探测 `.husky/`,不得读取或执行 `git config core.hooksPath`,也不得修改主仓库或 Worktree 的 Git 配置
- **F9**: 创建后设置 B——配置分为 `shared_readonly_dirs`(默认 `["node_modules", ".venv", "vendor"]`)与 `shared_writable_dirs`(默认空)。本期只实现 readonly:仅当 PathSandbox/OS sandbox 能以 realpath 拒绝对共享目标写入时才创建 symlink;文件工具允许读取声明过的 readonly target,拒绝 Write/Edit, Bash 也不得写穿透。无法保证只读时跳过并警告。`shared_writable_dirs` 非空启动即报配置不支持,避免伪隔离
- **F10**: 创建后设置 C——按项目根 `.worktreeinclude` 复制被忽略但运行需要的文件;读取 `.worktreeinclude` 每行为 glob 模式(支持 `*.env` 这种),用 `git -C <repo_root> ls-files --others --ignored --exclude-standard --directory` 列出所有忽略文件,匹配模式后逐个复制到 Worktree 对应路径;文件不存在 / 模式无匹配只警告

### 进入与退出

- **F11**: `Manager.enter(name: str) -> WorktreeSession`(async)——
  - 1. `async with self.lock:`,从 `active` 取 wt(不存在抛异常)
  - 2. 取当前 `Path.cwd()` 与当前 Git HEAD/branch 作为原状态
  - 3. 构造 `WorktreeSession(original_cwd, worktree_path=wt.path, worktree_name=name, original_branch, original_head_commit, session_id=uuid)`
  - 4. 写 `self.current_session = session`,持久化到 `session_file`(原子写——先写 tmp 再 rename)
  - 5. 返回 session
  - **不调 `os.chdir`**
- **F12**: `Manager.exit(name: str, action: ExitAction, opts: ExitOptions) -> ExitReport`(async)——`ExitAction` 取 `KEEP` / `REMOVE` 枚举;`ExitOptions(discard_changes: bool)`
  - 1. `async with self.lock:`,取 `active[name]` 与 `current_session`(若 `current_session.worktree_name != name` 抛异常,只能退当前)
  - 2. 若 `action=REMOVE` 且 `not opts.discard_changes`,调 `_has_worktree_changes(wt.path, wt.base_commit)`,有变更则抛 `WorktreeHasChangesError`
  - 3. `self.current_session = None`,持久化为 `null`(覆写 session_file 为空 JSON `null` 字符串);进程 cwd 始终不变
  - 4. 若 `action=REMOVE`:`git worktree remove --force <wt_path>` → `await asyncio.sleep(0.1)` → `git branch -D <branch_name>`;成功后删 manifest 与 `active[name]`
  - 5. 返回 `ExitReport(removed: bool, path: str, branch: str)`
- **F13**: `Manager.remove(name: str, opts: ExitOptions)`——独立 remove 入口,允许删除非当前 session 的 Worktree;变更保护同 F12
- **F14**: `Manager.auto_cleanup(name: str) -> AutoCleanupReport`——
  - 1. 取 `active[name]`,`manual=True` 直接 `keep`
  - 2. `_has_worktree_changes(wt.path, wt.base_commit)` 返回 False 走 `remove(name, ExitOptions(discard_changes=True))`,报告 `AutoCleanupReport(kept=False)`
  - 3. 有变更:`AutoCleanupReport(kept=True, path=wt.path, branch=wt.branch)`
- **F15**: `_has_worktree_changes(wt_path, base_commit) -> bool`——两件事:`git -C <wt_path> status --porcelain` 非空即有未提交;`git -C <wt_path> rev-list --count <base_commit>..HEAD` >0 即有新增 commit;任一 git 命令本身出错 fail-closed 返回 True(宁可保留)

### explicit cwd 工具改造

- **F16**: 在 `Arkcode.tool` 包定义 ctx key 与帮助函数——
  - 用 `ExecutionPathContext(cwd, workspace_root, readonly_shared_targets)` 表达本次 Agent 的路径边界,通过 `ContextVar` 传递;`with_workspace(ctx)` 设置并在 finally reset token
  - `resolve_path(p, access)` 先按 `cwd` 解析相对/绝对路径,再取 `realpath`;普通路径必须位于 `workspace_root` 内
  - 路径穿过声明过的 `readonly_shared_targets` 时仅允许 `access=READ`,Write/Edit 一律拒绝;其他越界路径(包括父仓库绝对路径、`..`、未声明 symlink target)返回结构化权限错误
  - 没有 ctx 时使用主 Agent 的 repo root 构造默认边界,不得退化为无限制的进程 cwd
- **F17**: 改造 6 个核心工具支持 ctx cwd——
  - `read_file` 用 `resolve_path(path, READ)`;`write_file` / `edit_file` 用 `resolve_path(path, WRITE)`
  - `glob` / `grep` 用 READ 解析搜索根目录,返回结果前再次校验每个 realpath,不展示越界 symlink 目标
  - `bash` 在 `asyncio.create_subprocess_exec` / `subprocess.Popen` 上显式设置 `cwd=ctx.cwd`,并把 PathSandbox/OS sandbox 根设为 `workspace_root`;sandbox 必须拒绝向 readonly shared target 写入
- **F18**: ctx cwd 注入点——
  - SubAgent isolation:worktree 启动时,在调 `run_to_completion` 前用 `with_workspace(ExecutionPathContext(cwd=wt_path, workspace_root=wt_path, ...))` 包住
  - TUI `/worktree create` 后用户手动 `enter` 也注入到主 Agent 的下一次 Run 的 ctx(通过 tui 的 `run_once` 入口)
- **F19**: 工具 Schema 不变——主 Agent 看到的工具列表与参数与 ch13 完全一致,ctx 注入不暴露 cwd 字段

### SubAgent 集成

- **F20**: 扩展 `subagent.Definition` 增加 `isolation: str` 字段;`parser.py` 解析 frontmatter `isolation:` 字段,合法值 `""` / `"worktree"`,非法值 stderr 警告后回落到 `""`
- **F21**: 改造 `agent.AgentTool.execute`——当 `definition.isolation == "worktree"` 时走 `_execute_with_worktree` 分支:
  - 1. 用 `agent-a<7位随机 hex>` 作为 worktree name(规避同类型并发冲突)
  - 2. 调 `worktree_manager.create(name, "HEAD", manual=False)` 创建临时 Worktree
  - 3. 构造 `worktree_notice` 文本(F22)拼到 task 文本前
  - 4. 用 `with_workspace(ExecutionPathContext(cwd=wt.path, workspace_root=wt.path, ...))` 包住后续调用
  - 5. 调 `sub_agent.run_to_completion(sub_conv, task_with_notice, events)`
  - 6. 跑完后调 `manager.auto_cleanup(name)`,`kept=True` 时把 `\n[Worktree 保留在 <path>,分支 <branch>]` 追加到 final_text
  - 7. 返回 final_text 给主 Agent
- **F22**: `build_worktree_notice(parent_cwd: str, wt_path: str) -> str` 模板(实际内容大致如下,中文友好)——
  ```
  <worktree-context>
  你当前在一个独立的 Git Worktree 副本中工作,与父 Agent 隔离。
  - 父目录: <parent_cwd>
  - 你的工作目录: <wt_path>
  - 父 Agent 提到的绝对路径基于父目录,你需要翻译成本地路径(替换前缀)再读写
  - 编辑文件前,必须先在本地 Worktree 重新 `read_file` 一次,避免使用过时内容
  </worktree-context>
  ```
- **F23**: 后台 SubAgent + isolation 协同——
  1. `task.Manager.launch` 先登记内部 `BackgroundTask(status="preparing")` 并立即对外返回 `job_id`
  2. 后台 runner 用 `owner_job_id=job_id` 创建 Worktree;成功后把 `worktree_name/path/branch` 写入执行记录并切为 `running`
  3. runner 在 `with_workspace(...)` 内调用 `run_to_completion`;ContextVar 只属于该 asyncio task,不污染主 Agent 或其他任务
  4. `completed/failed/cancelled` 都进入同一个 finally:调用 `auto_cleanup`;有未提交修改或新增 commit 时保留并把路径/分支/base_commit 写进任务通知
  5. 创建阶段失败则 job 转 `failed`;取消发生在 git 子进程期间时先终止并等待子进程,再按 manifest/owner_job_id 做补偿清理,绝不删除身份不匹配的现有目录或分支
  6. `JobGet` / `JobList` 在 preparing/running 阶段都返回 Worktree 准备进度;`JobStop` 对两种状态均有效

### TUI Slash 命令

- **F24**: `/worktree create <slug>`——调 `manager.create(slug, "HEAD", manual=True)`,输出 Worktree path + branch
- **F25**: `/worktree list`——遍历 `manager.list()`,每行格式 `<name>  <path>  <branch>  [active?]`
- **F26**: `/worktree exit [--remove] [--discard]`——退出当前 session;`--remove` 时调 `exit(name, ExitAction.REMOVE, ExitOptions(discard_changes=discard))`,`--discard` 跳过变更保护
- **F27**: `/worktree remove <slug> [--discard]`——直接调 `manager.remove(slug, ...)`
- **F28**: `/worktree enter <slug>`——调 `manager.enter(slug)`,把 ctx cwd 写到 TUI 的 `app.active_cwd` 字段,主 Agent 下次 Run 用这个 cwd 注入 ctx
- **F29**: slash 命令属于 `KindLocal`(只读)或 `KindUI`(改 TUI 状态),不进对话历史;输出走 `ui.println`

### 持久化与恢复

- **F30**: `WorktreeSession` 序列化为 JSON,字段名采用小写下划线;原子写使用同目录唯一临时文件,执行 `flush + fsync + os.replace`
- **F31**: Arkcode 启动时(`Manager.__init__` 内),读 `session_file` 反序列化;若文件内容为 `null` 或空,`current_session=None`;若 `worktree_path` 不存在或对应 manifest 的 repo_id/path/name 不匹配,清空文件并 `current_session=None`(stderr 警告 "session worktree invalid, cleared")
- **F32**: `--resume` (Arkcode 现有恢复入口)读到已有 session 时,把 `active_cwd` 设置到 `session.worktree_path`,主 Agent 后续工具调用都按 explicit cwd 走

### 后台过期清理

- **F33**: `Manager.sweep_stale(cutoff: datetime) -> list[str]`(async)——
  - 1. 遍历 `worktree_dir.iterdir()`
  - 2. **第一层** 名字匹配正则 `^agent-a[0-9a-f]{7}$`(本期只识别 SubAgent 临时模式)
  - 3. **第二层** 目录 mtime > cutoff 跳过;`current_session.worktree_path == 子目录` 跳过
  - 4. **第三层** 先校验 manifest/repo_id,再用 manifest 的 `base_commit` 调 `_has_worktree_changes`;校验失败或有变更均跳过(fail-closed)。额外跑 `git -C <子目录> rev-list --max-count=1 HEAD --not --remotes`,非空跳过(有未推送 commit 也保留)
  - 5. 通过三层的子目录调 `remove(name, ExitOptions(discard_changes=True))`,记入 `removed`
- **F34**: Arkcode 启动时跑一次 `asyncio.create_task(manager.sweep_stale(now - timedelta(hours=24)))`(异步、后台执行),不阻塞启动

### .gitignore 更新

- **F35**: 在项目根 `.gitignore` 追加 `.Arkcode/worktrees/` 与 `.Arkcode/worktree_session.json` 两行;Arkcode 启动时若发现 `.gitignore` 不含这两行,**只警告不修改**(尊重用户配置)

## 非功能需求

- **N1**: 主 Agent 看到的工具列表稳定——ctx 注入不改 schema,既有缓存不抖动
- **N2**: Worktree 创建后设置失败 (F7/F9/F10) 不阻塞创建;F8 为明确跳过项,主路径只在 git worktree add 本身失败时抛异常
- **N3**: Manager 的 `active/current_session` 状态变更受 `asyncio.Lock` 保护;锁内只做预留/提交等短操作,耗时 git 子进程不持锁。创建流程用 reservation 记录 name/path/branch,防止释放锁后同名并发创建
- **N4**: Arkcode 主进程与 in-process Agent 禁止调用 `os.chdir`;所有工具与 git 子进程都显式传 `cwd`。独立 Pane 子进程因不共享主进程 cwd,允许在启动、创建异步任务之前执行一次 `os.chdir(worktree_path)`,此后禁止再次修改 cwd
- **N5**: Worktree session 文件被破坏(非法 JSON)启动时只警告并清空,不阻断 Arkcode 启动
- **N6**: 与 ch04~ch13 既有测试零破坏——`pytest` 全绿
- **N7**: 中文友好——错误消息与命令输出全部中文(对齐 Arkcode 其他模块风格)
- **N8**: manifest/session 原子写使用唯一临时文件、`flush + fsync + os.replace`;恢复永远 fail-closed,不得根据目录名猜测 `manual/base_commit/owner_job_id`
- **N9**: 后台 Worktree 的创建、取消、异常和清理必须异常安全;任务通知最多出现一次,保留的 Worktree 必须带可复制的 path/branch/base_commit

## 不做的事

- Worktree 间的合并策略(交给上层 `git merge` / `git cherry-pick`)
- 跨 Worktree 代码同步、文件 watcher
- 多 Agent 并行编排 / Agent Team(下一章)
- 主 Agent 用专用 merge 工具(README 章末已说明)
- Plugin 来源的 Worktree 配置
- Windows 平台特殊支持(symlink 行为在 Windows 上不保证;本期 Arkcode 以 macOS / Linux 为主)
- 跨 Arkcode 进程实例的 Worktree 共享(同一仓库同一时刻只支持一个 Arkcode 实例操作 worktree session)
- Worktree 内部 git 操作的 retry / exponential backoff(用一次性 `await asyncio.sleep(0.1)` 解决 lockfile 竞态即可)

## 验收标准

- **AC1**: `worktree.validate_slug` 对 `"feature/a"` 通过,对 `"../etc"` / `".."` / `"a//b"` / `"a/b "` 拒绝
- **AC2**: `manager.create("alice", "HEAD", manual=True)` 在 `.Arkcode/worktrees/alice/` 下落地 Worktree,分支为 `worktree-alice`
- **AC3**: `manager.create("team/alice", "HEAD", manual=True)` 在 `.Arkcode/worktrees/team+alice/` 下落地,分支 `worktree-team+alice`
- **AC4**: 已存在 worktree 目录且 manifest/repo/branch/path/base_commit 全部匹配时再调 create 走快速恢复,不调 `git worktree add`;manifest 缺失或任一身份字段不匹配时抛 `WorktreeIdentityError`,目录和分支均不修改
- **AC5**: 创建后设置 A——主仓库存在 `.Arkcode/settings.local.yaml` 时,Worktree 内同位置出现该文件
- **AC6**: 创建后设置不会探测 `.husky/` 或调用任何 `git config core.hooksPath`;创建前后主仓库与 Worktree 的 hooks 配置均未被 Arkcode 修改
- **AC7**: 创建后设置 B——具备只读 sandbox 时主仓库 `node_modules/` 可建立 readonly symlink,Read 成功而 Write/Edit/Bash 写穿透被拒绝;无只读保障时不建立 symlink 并输出警告
- **AC8**: 创建后设置 C——主仓库有 `.worktreeinclude` 含 `*.env`,且主仓库存在被忽略的 `.env`,Worktree 内出现 `.env`
- **AC9**: `manager.enter(name)` **不**改变进程 `Path.cwd()`;返回 session 含正确字段
- **AC9a**: `manager.exit/manager.remove/auto_cleanup` 同样不改变进程 `Path.cwd()`
- **AC10**: `manager.exit(name, ExitAction.REMOVE, ExitOptions())` 当 Worktree 有未提交修改时,抛 `WorktreeHasChangesError`,Worktree 目录仍在
- **AC11**: `manager.exit(name, ExitAction.REMOVE, ExitOptions(discard_changes=True))` 显式 discard 时,目录被删,分支被删
- **AC12**: `manager.auto_cleanup(name)` 对 `manual=True` 直接 keep;对 `manual=False` 且无变更直接 remove
- **AC13**: 工具 `read_file` / `write_file` / `edit_file` / `bash` / `glob` / `grep` 在 ctx 注入 cwd 后,以 cwd 为基准解析相对路径(单测断言)
- **AC14**: `bash` 工具在 ctx cwd 注入下,子进程 `cwd=` 参数为 ctx cwd(单测 / 集成测试可断言)
- **AC14a**: Worktree 文件工具访问父仓库绝对路径、`../` 越界路径或未声明 symlink target 时返回权限错误;允许访问 Worktree 内绝对路径
- **AC15**: `subagent.Definition.isolation == "worktree"` 时,`AgentTool.execute` 创建临时 Worktree、注入 worktree notice、传 ctx cwd、跑完后调 auto_cleanup
- **AC16**: SubAgent + worktree 路径上,子 Agent 写文件不影响主 Agent 工作目录(集成测试或 tmux 实跑可观察)
- **AC17**: `/worktree create alice` slash 命令成功落地 Worktree,`/worktree list` 输出含 alice
- **AC18**: `/worktree exit --remove` 在 Worktree 有未提交修改时报错;加 `--discard` 后成功删除
- **AC19**: `manager.sweep_stale(cutoff)` 只删命名匹配 `agent-a[0-9a-f]{7}` 的目录、跳过当前 session、跳过有变更或有未推送 commit 的目录
- **AC20**: `WorktreeSession` 持久化到 `.Arkcode/worktree_session.json`,启动时读取;指向的 Worktree 目录被外部删除后,启动时清空 session 并 stderr 警告
- **AC21**: 项目可启动 (`python -m Arkcode`)、所有单元测试通过 (`pytest`)、lint 通过 (`ruff check`)
- **AC22**: tmux 实跑——`python -m Arkcode` 启动 + 触发 `isolation:worktree` 子 Agent 改文件 + 验证主目录 `server.py`(若改的是 `server.py`)未变,Worktree 副本里 `server.py` 已变;Worktree 留盘 / 自动清理符合预期
- **AC23**: `Agent(..., run_in_background=true)` 且定义为 `isolation:worktree` 时立即返回 job_id;JobGet 依次可观察 `preparing → running → completed`,主 Agent 全程可继续输入
- **AC24**: 后台 Worktree 在 preparing/running 阶段执行 JobStop 后进入 cancelled;干净资源被回收,已有修改的 Worktree 被保留且通知含 path/branch/base_commit
- **AC25**: 后台创建遇到同名分支、损坏 manifest、git 子进程失败或进程取消时不重置/删除任何非本任务资源,并产生一次 failed/cancelled 通知
