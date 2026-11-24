<p align="center">
  <img src="./assets/readme/hero.svg" width="100%" alt="oil-delegate：一句话把任务交给合适的 Agent，并在原会话中继续。">
</p>

## 有什么用

如果你已经在使用多个 Agent，`oil-delegate` 让你不用记住每家的命令和用法。只要把任务说清楚，它就会交给指定的 Agent，并把结果带回来。

- **自动发现**：第一次使用时，自动找出本机已有的 Agent。
- **自由选择**：由你决定启用哪些 Agent，以及是否设置一个默认 Agent。
- **按用途记住**：可以分别指定谁做代码审查、方案评审、疑难会诊和功能实现。第一次用到时问你一次，之后配套 Skill 会自动交给对应的 Agent，不用每次再说。
- **连续对话**：得到结果后可以接着追问或返工，不用重复前面的背景。

它适合代码检查、问题诊断、功能修改、方案评审，也适合让另一个 Agent 提供独立意见。

## 支持哪些 Agent

你可以使用全名，也可以使用顺手的简称，不区分大小写：

| Agent | 简称与别名 |
| --- | --- |
| Claude Code | `cc`、`claude`、`claude-code` |
| 火山方舟 GLM-5.3（本机 Claude Code 启动器） | `claude-volces`、`volces`、`glm-5.3` |
| MiniMax（本机 Claude Code 启动器） | `claude-minimax`、`minimax` |
| WorkBuddy | `wb`、`workbuddy`、`codebuddy`、`cbc` |
| Antigravity | `agy`、`antigravity` |
| Codex | `codex` |
| OpenCode | `opencode` |
| DeepSeek Harness | `dsh`、`deepseek`、`deepseek-harness` |
| Grok Build | `grok`、`grok-build` |
| Kimi Code | `kimi`、`kimi-code` |
| Cursor | `cursor`、`cursor-agent`、`cursor-cli` |

## 怎么用

### 1. 安装 Skill

最简单的方式是把下面这句话发给你的 Agent：

```text
请帮我安装这个 Skill：https://github.com/DoThingsWithAI/oil-delegate
```

也可以使用命令安装：

```bash
npx skills add DoThingsWithAI/oil-delegate
```

安装完成后，按 Agent 的提示重新加载 Skill 即可。

### 2. 第一次使用：自动检查，再让你选

第一次委托时，它会自动检查本机环境，不需要你手动运行命令。检查完成后，你只需要回答两个问题：

1. 要启用哪些 Agent？
2. 默认使用哪一个，还是每次委托时再选？

确认后才会保存配置。检查过程不会调用模型、安装软件或替你登录；如果某个 Agent 还没有登录或不可用，它会如实告诉你。

### 3. 以后直接说

```text
用 cc 检查这个仓库的登录流程，只读分析并告诉我问题在哪里。
```

```text
让 dsh 修复这个测试，修改后运行相关检查。
```

```text
用 agy 评审这个方案，再继续追问它遗漏的风险。
```

```text
让 dsh 分析当前项目，并继续刚才的会话。
```

```text
用 dsh 实现这个功能，让 grok 再检查一遍。
```

```text
以后代码审查都交给 codex，方案评审用你自己就行。
```

没有指定 Agent 时，它会使用你的默认选择；如果没有设置默认值，会先问你，不会擅自更换。默认只读；明确授权实现时，Codex 和 DSH 使用 workspace-write，Claude Code 支持受限文件编辑（不开放 shell，主 Agent 验证测试）。其他 Runner 暂只支持计划/分析（Kimi 暂停）。代码审查、方案评审和疑难会诊这三类用途一律只读。

## Mac 本机委托（默认，无需 Docker）

只读分析直接使用本机 CLI。开发任务优先使用 `scripts/native_worktree.py`：从已提交 HEAD 创建独立 Git Worktree，使用本机已配置的 DSH/Codex/Claude Code 与对应受限权限，不自动合并。详见 [本机配置与续接](references/native.md)。

Claude Code 可复用本机已有的 GLM 等第三方模型配置（例如 GLM-5.3），不强制指定 Claude 模型；要求 Claude Code 2.1.314+，先核实实际 provider。火山方舟配置使用独立 `claude-volces` runner，不会回退普通 Claude；MiniMax 使用独立 `claude-minimax` runner，同样不回退其他 CLI；若为 shell alias，需配置可执行启动器。Docker 仅为用户主动选择的高级模式，详见 [容器隔离](references/isolation.md)。不安装 Docker 也可使用日常功能。Worktree 不等于系统安全沙箱。

## 使用条件与边界

- 需要 Python 3.10 或更高版本，以及至少一个已经安装并登录的受支持 Agent。macOS 已实测 Antigravity、Codex 和 Kimi Code 的新建与续接，以及 Antigravity、Codex 的真实写入；其他 Agent 能否直接完成任务，取决于本机登录和模型配置。Linux 和 Windows 尚未实机验证。
- 任务内容会交给你选择的 Agent 及其模型服务，可能产生费用。不要在任务中放密钥。
- 安全增强版取消默认全权限、过滤常见跨服务环境凭据、默认不记录原始 prompt/事件、限制报告长度和运行时间。CLI 自身的 plan/沙箱并非统一的 OS 级隔离；本机认证文件、项目 `.env`、网络访问等风险仍需独立账号/容器及额外策略。重要项目先确认代码可交给目标服务，再检查改动和测试。

关于什么场景适合派发子 Agent、不同角色怎么分工，可以参考 Oil Book 里的[《怎样用好子 Agent》](https://book.oiloil.org/articles/subagent-workflow?utm_source=github&utm_medium=referral&utm_campaign=oil-delegate-readme)。

<details>
<summary>维护、测试与排查</summary>

在仓库目录运行回归测试，不需要调用外部模型：

```bash
python3.10 -m unittest discover -s tests -p "test_*.py" -v
```

特定 Agent 的调用差异与失败处理见 [Runner 适配参考](references/runners.md)。发现问题时，可以带上 Runner、实际版本和错误日志到 [GitHub Issues](https://github.com/DoThingsWithAI/oil-delegate/issues) 反馈。

</details>

## License

[MIT License](LICENSE)。图标与配图来源见[素材说明](assets/readme/NOTICE.md)。
