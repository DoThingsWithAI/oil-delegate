# Mac 本机轻量委托（默认推荐）

不需要 Docker。使用已安装并登录的 DeepSeek Harness / Codex，Python 3.10+，写入任务额外需要 Git。只读任务直接用 scripts/delegate.py，写入任务优先使用 scripts/native_worktree.py。

    python3 scripts/native_worktree.py --runner dsh --workspace /path/to/repo \
      --prompt '按已确认方案实现并测试'

入口通过原 delegate.py 调用目标 CLI，继承其 workspace-write 参数、常见凭据过滤、日志控制及超时限制。新建独立 detached Git Worktree，只检出已提交 HEAD，不包含未提交的代码、未跟踪文件和本地 .env；如果本轮需要未提交的上下文，先由主 Agent 与用户确认处理方式，不擅自提交。常见已跟踪密钥文件名会导致拒绝，但不构成完整密钥扫描。

返回 run_id、worktree、session_id 和报告路径。主 Agent 检查该 worktree 的 git status / git diff 和测试结果，再选择性应用；不自动合并、提交、推送。对于返工使用同一个 runner 和仓库：

    python3 scripts/native_worktree.py --runner dsh --workspace /path/to/repo \
      --resume-run <run_id> --prompt '修复验收发现的问题'

同一 run 防止并行续接；没有 session 不静默开启新会话。完成验收并确认不再续接后，使用 git worktree remove <完整工作树路径>；有修改先处理，不强制删除。状态目录保留在 ~/.oil-delegate/native-worktrees/，按需手动清理。

注意：Worktree 是代码修改隔离，不是系统安全沙箱，它与主仓库共享 Git 元数据。本机 CLI 的权限机制因版本和配置不同而异，且仍可使用本机登录、读取其获准访问的文件或联网；环境变量过滤不是完整的凭据隔离。不要用于不可信仓库、敏感环境或未获授权发送给第三方模型的代码；这类任务需要独立账号及实际 OS/网络隔离，条件不足时停止。Docker 仅是用户主动选择的高级可选方式，不影响本机普通使用，也不自动安装。
