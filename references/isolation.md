# 隔离委托（macOS / Linux）

这是可选的严格隔离入口，适用于 Codex 与 DeepSeek Harness。原有 scripts/delegate.py 仍可用于可信本机任务，但不提供统一 OS 级隔离。对不可信仓库、涉及文件写入或敏感环境的任务，优先采用本入口；环境不满足时停止，不要自动退回直接执行。

## 准备

- 非 root 用户、Git、Python 3.10+、本机 Docker（macOS 可使用 Docker Desktop）。不使用远程 Docker daemon。
- 自行准备包含 Python 3.10+、所选官方 CLI 及运行依赖的可信 Linux 镜像。使用本地镜像 ID sha256:... 或 digest 固定的镜像，脚本不拉取镜像、不自动安装或登录。镜像本身不得预置密钥或危险工具配置。
- 在线调用需先在宿主环境配置所选模型的 API Key（DSH: DEEPSEEK_API_KEY / DSH_API_KEY；Codex: OPENAI_API_KEY / CODEX_API_KEY）。不传入其他环境变量或挂载宿主登录目录；依赖宿主 OAuth/GUI 登录的 CLI 不能直接复用该登录。
- 只使用可信仓库，确认 HEAD 中的代码允许发送给第三方服务。已提交密钥的文件名检查仅是额外防护，并非完整秘密扫描。Git 工作树创建仍会使用宿主仓库 Git 配置及检出过滤器。

## 使用

    python3 scripts/isolated_delegate.py --runner dsh --workspace /path/to/repo \
      --image sha256:<64位本地镜像ID> --mode write --allow-network \
      --prompt '实现已授权的任务，运行测试并报告结果'

默认 read、默认断网。真实云端模型需要明确同意 --allow-network，它启用 Docker bridge 网络；这不是 API 域名白名单，也不阻止访问可达的内部或外部服务。高敏感任务应先由管理员提供外部网络策略/出口代理并验证；没有该条件不要使用在线委托。禁止宿主网络、Docker socket 挂载和宿主 HOME 挂载。不要通过提示词传密钥。

## 隔离边界

- 从已提交 HEAD 创建独立 detached Git Worktree；不会带入主工作区未提交内容、未跟踪文件或本机 .env。已提交内容仍然可见；不会自动应用子 Agent 的修改。
- 容器非 root、根文件系统只读、移除 capabilities、禁止提权、限制 PID/内存/CPU、限制时长。read 模式工作区只读；write 模式只挂载独立工作树为可写。宿主 Git 元数据不挂载，容器内 Git 历史/提交命令可能不可用。主 Agent 在宿主完成 diff、测试与合并。
- 容器专用 HOME 与 delegate 状态只对本次 run 可写，续接时复用。其会话或输出也可能含源码与敏感数据；保留目录仅供审查，不上传、不当作可信指令。
- 不把宿主的 SSH agent、GitHub token、云平台凭据或整个 HOME 交给容器。模型自身凭据仍可被该容器访问；使用独立、低额度、可撤销的 API Key。
- Docker 是额外隔离边界而不是绝对安全保证。镜像、Docker daemon、宿主机及仓库均需可信。未配置网络出口限制时，容器可以通过网络发送任何可读内容。

## 续接与验收

使用返回的 run_id 并带上同一仓库、runner、mode、image 和本轮新 prompt：

    python3 scripts/isolated_delegate.py --runner dsh --workspace /path/to/repo \
      --image sha256:<64位本地镜像ID> --mode write --allow-network \
      --resume-run <run_id> --prompt '修正验收发现的问题'

只复用已记录 session；未记录 session 时拒绝续接，不静默新开。工作树保留在 ~/.oil-delegate/isolated/<run_id>/workspace，先在宿主检查 git diff、git status 和未跟踪文件，再手动选择性应用修改。不要执行不可信生成的脚本或将其内容视为用户指令。确认不需要后使用 git worktree remove <完整工作树路径>（有修改时先处理），再手动清理该 run 的独立状态目录。不要删除仍需要续接的状态。

本入口不统计真实 token 额度；执行时间和资源上限不能替代模型服务的消费预算。先在服务端设置额度限制。Docker 实际权限及 CLI 在容器内的兼容性需在你的设备上验证。
