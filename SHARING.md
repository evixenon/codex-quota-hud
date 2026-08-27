# 分享 Codex Quota HUD

本插件是 Windows 本地 HUD。它会通过 Codex lifecycle hooks 启动 Python/Tkinter
窗口，并调用本机 `codex` CLI 读取额度信息。因此，接收者需要自行审查并信任
hooks；不要把该插件当作纯云端插件分发。

## 前提条件

每台使用该插件的电脑都需要：

- Windows；
- 可以运行 `codex --version` 的 Codex CLI；
- 可以运行 `python`，且该 Python 安装包含 Tkinter；
- 安装完成后，在 Codex 中用 `/hooks` 审查并信任本插件的 `SessionStart` 与
  `SessionEnd` hooks。

安装或更新插件后，需要新建一个 Codex 任务，新的 skills 和 hooks 才会加载。

## 迁移到另一台自己的电脑

最简单的方式是复制整个插件目录。必须保留全部内容，包括 `.codex-plugin/`、
`hooks/`、`hud/`、`skills/` 和 `scripts/`；不要只复制 HUD 脚本。

也可以用 Git 在多台自己的电脑之间同步。Git 负责同步源码；
`@plugin-creator` 负责创建或维护 marketplace 配置；插件的实际安装由 Codex 的
Plugins 页面或 `codex plugin add` 完成。`@plugin-creator` 不是主要的安装命令。

在开发电脑初始化并推送仓库：

```powershell
cd C:\Users\Administrator\repos\codex-quota-hud
git init
git add .
git commit -m "Initial Codex Quota HUD plugin"
git branch -M main
git remote add origin <你的 Git 仓库地址>
git push -u origin main
```

在另一台电脑克隆插件：

```powershell
git clone <你的 Git 仓库地址> C:\Users\<用户名>\repos\codex-quota-hud
```

建议在目标电脑将插件放到一个固定目录，例如：

```text
C:\Users\<用户名>\repos\codex-quota-hud
```

然后在目标电脑的 personal marketplace 中创建一个指向该目录的条目。推荐使用
Codex 的 `@plugin-creator` 完成此操作，避免 marketplace 相对路径配置错误。可以在
新任务中使用以下提示：

```text
@plugin-creator 将现有插件 C:\Users\<用户名>\repos\codex-quota-hud 注册到 personal marketplace。
不要重建、移动或覆盖插件文件；仅创建或更新 marketplace 条目，并确认它指向这个现有目录。
```

完成后：

1. 重启 ChatGPT Desktop / Codex。
2. 在 Plugins 的 Personal 来源中安装 `codex-quota-hud`，或运行：

   ```powershell
   codex plugin add codex-quota-hud@personal
   ```

3. 新建一个 Codex 任务。
4. 在 `/hooks` 中审查并信任两个 hooks。

源代码更新后，在目标电脑执行：

```powershell
cd C:\Users\<用户名>\repos\codex-quota-hud
git pull
```

再重新安装插件并新建任务。仅 `git pull` 不会更新 Codex 已安装到本机缓存中的插件副本。

当前开发电脑的 personal marketplace 配置使用本机目录
`C:\Users\Administrator\repos\codex-quota-hud`。该路径对其他电脑无效，不能直接
复制 `C:\Users\Administrator\.agents\plugins\marketplace.json`。

## 通过 Git 仓库分享

给其他人或团队分发时，推荐使用 Git 仓库 marketplace。仓库应采用以下布局：

```text
your-plugin-repo/
  .agents/
    plugins/
      marketplace.json
  plugins/
    codex-quota-hud/
      .codex-plugin/
      hooks/
      hud/
      scripts/
      skills/
```

这是团队分发的推荐布局：marketplace 配置与插件源码一起进入 Git，不需要每位接收者
重新运行 `@plugin-creator`。如果当前仓库根目录就是插件目录，则需要先将它移动到
`plugins/codex-quota-hud/`，再在外层仓库创建 `.agents/plugins/marketplace.json`。

`your-plugin-repo/.agents/plugins/marketplace.json` 的核心条目如下：

```json
{
  "name": "your-plugins",
  "interface": {
    "displayName": "Your Plugins"
  },
  "plugins": [
    {
      "name": "codex-quota-hud",
      "source": {
        "source": "local",
        "path": "./plugins/codex-quota-hud"
      },
      "policy": {
        "installation": "AVAILABLE",
        "authentication": "ON_INSTALL"
      },
      "category": "Productivity"
    }
  ]
}
```

接收者在终端添加 marketplace：

```powershell
codex plugin marketplace add <GitHub用户名>/<仓库名>
```

也可以使用 Git URL 或本地 marketplace 根目录：

```powershell
codex plugin marketplace add https://github.com/<组织或用户名>/<仓库名>.git
codex plugin marketplace add C:\path\to\your-plugin-repo
```

接收者随后在 Codex 的 Plugins 页面，或在 Codex CLI 的 `/plugins` 中安装
`codex-quota-hud`，再新建任务并信任 hooks。

更新发布者仓库后，接收者执行：

```powershell
codex plugin marketplace upgrade <marketplace名称>
```

然后重新安装或更新插件，并新建任务。

## 在 ChatGPT 工作区内发布

如果发布者是 ChatGPT workspace 管理员，可以在 Plugins 的 Personal 来源中找到该
插件，打开三点菜单，选择 Publish，并指定可以访问的 workspace 角色。

这种发布仅面向该 workspace 成员，不会出现在所有用户可见的公共插件目录中。
公开发布需要走 OpenAI 的插件提交与审核流程。

## 安全提示

本插件在 `SessionStart` 和 `SessionEnd` 时执行本机 Python 脚本。分享前应让接收者
查看源码，特别是 `hooks/hooks.json`、`hooks/session_start.py`、
`hooks/session_end.py` 与 `hud/codex_hud.py`。接收者应只从可信仓库安装，并在
`/hooks` 中逐项确认 hook 定义。

## 官方文档

- https://developers.openai.com/plugins/build/plugins
- https://learn.chatgpt.com/docs/plugins
