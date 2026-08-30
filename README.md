# Codex Quota HUD plugin

这是一个 Codex 本地插件版本：

- Codex `SessionStart` 时启动黑底荧光绿的本地 HUD；
- HUD 跨 Codex 会话复用；`SessionEnd` 不会关闭 HUD；
- HUD 通过本机 `codex app-server` 的只读 `account/rateLimits/read` 读取最长额度窗口；
- 倒计时只显示 `5d20h`、`20h15m` 或 `45m` 这样的纯格式。

## 使用前提

- Windows；
- 终端可以运行 `codex --version`；
- `python` 可用，并且对应 Python 安装包含 Tkinter；
- 安装插件后，在 Codex 中打开 `/hooks`，审查并信任本插件的两个 command hooks。

插件 hooks 是非托管 hooks。Codex 不会因为安装插件就自动信任它们；未信任时 HUD 不会自动启动。

## 安装到本机 Codex

全局个人 marketplace 位于 `C:\Users\Administrator\.agents\plugins\marketplace.json`，Codex 会自动发现它，不需要运行 `codex plugin marketplace add`。只需执行：

```powershell
codex plugin add codex-quota-hud@personal
```

然后重新打开 Codex，在 Codex 中运行 `/hooks`，审查并信任 `codex-quota-hud` 的 `SessionStart` 和 `SessionEnd` hooks。

## 说明

这里的“打开 Codex”对应 Codex 会话生命周期，而不是桌面应用进程生命周期。HUD 是桌面级共享进程：开始一个 Codex 会话时确保它启动，主线程结束时不会关闭，因此会话重建或发送新消息不会让 HUD 消失。HUD 会在 Codex 窗口失去焦点时自动隐藏；如需彻底关闭，请手动结束 HUD 进程。
