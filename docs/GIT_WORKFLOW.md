# Git 分支与发布维护手册

本仓库使用两个职责完全不同的长期分支：

- `developer`：唯一开发真相源，保留 v1.0.0 之前的完整历史、测试、前端源码、设计资料与发布工具。
- `main`：由 developer 的指定 commit **生成**，只保存正式插件文件；提交历史从 v1.0.0 开始。

`main` 与 `developer` 没有共同祖先，禁止在两者之间执行 merge。发布同步只能通过
`tools/build_published_tree.py` 完成。

## 1. 日常开发

克隆开发仓库后显式切换分支：

```bash
git switch developer
git status --short --branch
```

IDE 会记住最后 checkout 的分支；保持工作区停留在 `developer`，普通 commit 即会落在开发分支。
新功能可从 developer 创建 `feature/*`，完成后合回 developer。

用户安装插件时不需要切分支：仓库默认分支保持 `main`，普通 `git clone` 得到正式版本。

## 2. 远端操作审批

下列行为都属于远端变更，执行前必须单独取得用户明确批准：

- `git push`、`git push --tags`；
- 创建、删除或改写远端分支/tag；
- force push；
- 创建 PR 或 GitHub Release；
- 切换 GitHub 默认分支。

批准修改、测试或本地 commit 不代表批准 push。申请批准时必须列出：

```bash
git remote -v
git branch --show-current
git log --oneline @{upstream}..HEAD
git status --short
```

## 3. 首次建立 v1.0.0 main

1. 当前旧 `main` 在本地重命名为 `developer`，GitHub 上也将旧 main 重命名为 developer。
2. 在 developer 完成 v1.0.0、全量测试并 commit，记录 source SHA：
   `git rev-parse HEAD`。
3. 生成发布树与 ZIP：

   ```bash
   python tools/build_published_tree.py --source HEAD \
     --output dist/published \
     --zip dist/astrbot_plugin_knowledge_repository-v1.0.0.zip
   ```

4. 在独立 worktree 创建 orphan main，把 `dist/published/` 内容复制为该分支完整文件树。
5. 首个提交写明 `Release: v1.0.0` 与 `Source-Developer-Commit: <sha>`。
6. 本地验证完成后，分别申请 main push、默认分支切换和 tag push 的批准。

## 4. 后续发布

1. developer 完成功能、版本、CHANGELOG、前后端构建并 commit。
2. 冻结 source SHA；之后的开发提交不得混入本次发布。
3. 从正式 main 创建 `publish/vX.Y.Z`，用生成器输出完整替换其文件树。
4. commit message 记录 source SHA，运行 published 校验。
5. 获批后 push publish 分支、创建 PR 到 main、合并并创建版本 tag。

main 上发现的缺陷也先修 developer，再重新生成发布树；不得直接修 main 后回抄。

## 5. `.gitignore` 与发布白名单

- `.gitignore` 只阻止本地缓存、日志、运行数据等未跟踪文件进入 Git。
- `.gitattributes` 控制 `git archive` 的二次瘦身。
- `release/published-files.txt` 是 main 文件树的唯一白名单。

修改运行文件布局时必须同步更新发布白名单，并运行发布生成检查。

## 6. Hotfix

紧急修复仍从 developer 开始。修复测试通过后冻结新的 developer SHA，生成
`publish/vX.Y.Z` 并走正常 main PR。这样 developer 永远包含全部正式修复，main 永远可重建。

## 7. 人工发布指令（developer → main）

以下流程可直接作为人工发布 instruction。将 `<VERSION>` 替换为
`metadata.yaml`、`CHANGELOG.md` 与 `TODO.md` 对齐的版本，例如 `v1.1.1`。

### 7.1 认证与发布前确认

先在本机配置 GitHub 认证。推荐使用 SSH；也可以使用已配置好的 HTTPS
credential manager。不要把 PAT、密码或私钥写进 remote URL、脚本或提交记录：

```bash
# SSH 方式
git remote set-url origin git@github.com:Gar1ton/Astrbot_Knowledge_Repository.git
ssh -T git@github.com

# 或 HTTPS credential manager 方式；按系统提示完成一次登录
git remote set-url origin https://github.com/Gar1ton/Astrbot_Knowledge_Repository.git
git config --global credential.helper manager-core
```

确认认证有效后，回到 developer 并冻结源提交。工作区必须干净；不要用
`git add -A` 把缓存、运行数据或未确认的改动带入发布：

```bash
git fetch origin developer main
git switch developer
git pull --ff-only origin developer
git status --short --branch
SOURCE_SHA="$(git rev-parse HEAD)"
VERSION="v1.1.1"  # 替换为本次发布版本，并确认与 metadata.yaml 一致
```

### 7.2 生成并验证正式树

必须从已提交的 `SOURCE_SHA` 生成，不能使用 `WORKTREE` 作为正式发布输入：

```bash
python3 -m pytest
ruff check .
git diff --check

python3 tools/build_published_tree.py \
  --source "$SOURCE_SHA" \
  --output dist/published \
  --zip "dist/astrbot_plugin_knowledge_repository-${VERSION}.zip"
```

如果项目包含前端且本机具备 Node.js，再运行：

```bash
cd web/frontend
npm run build
cd ../..
python3 tools/sync_frontend.py --check
```

测试工具或 Node.js 缺失时不得假装验证通过；记录为阻塞项，并在远端发布前
补齐依赖后重跑。发布生成器会校验白名单、必需文件、禁止文件和 ZIP 大小。

### 7.3 创建发布分支与本地提交

发布分支必须从正式 `origin/main` 创建；禁止把 `developer` merge 到 `main`，
也禁止直接在 `main` 手改文件。下面的 `git rm` 只允许在新建的本地
`publish/<VERSION>` 分支执行：

```bash
git switch -c "publish/$VERSION" origin/main
git rm -r -- .
cp -a dist/published/. .

# 只暂存生成树；git add -A 可能把 developer 的缓存或源码带进来
git add -u
git add -- $(find dist/published -type f -printf %P\n)
git diff --cached --check

git commit \
  -m "Release: $VERSION" \
  -m "Source-Developer-Commit: $SOURCE_SHA"
git show --stat --oneline HEAD
```

提交前应确认索引只包含生成器输出。若同一工作区残留了 developer 的
`tests/`、`tools/`、`web/frontend/` 或 `__pycache__/`，不要删除用户文件，
只用生成树路径显式暂存，或改用独立 worktree 重做发布分支。

### 7.4 推送发布分支并合并到 main

远端操作前再次报告并确认以下四项：remote、源分支、目标分支和提交范围。
本项目的目标不是直接向 `main` 推送，而是先推送发布分支并创建 PR：

```bash
git remote -v
git branch --show-current
git log --oneline origin/main..HEAD
git status --short

git push -u origin "publish/$VERSION"
```

然后在 GitHub 网页创建 Pull Request：

1. `base` 选择 `main`，`compare` 选择 `publish/<VERSION>`。
2. 标题使用 `Release: <VERSION>`。
3. 描述写明 `Source-Developer-Commit: <SOURCE_SHA>`、生成器命令和验证结果。
4. 等待 CI 与人工审查通过后合并 PR；不使用 force push，不直接把
   `developer` 推到 `main`。

合并后再同步本地并创建版本 tag：

```bash
git fetch origin main
git switch main  # 若本地没有 main，先执行 git switch -c main --track origin/main
git pull --ff-only origin main
git tag -a "$VERSION" -m "Release $VERSION" origin/main
git push origin "$VERSION"
```

### 7.5 本轮 v1.1.1 操作记录

2026-08-04 已按上述流程完成本地准备：developer 源提交为
`818731747ec800167d99ada080fc3af480b13848`，生成器输出 501 个文件和约
4.00 MiB 的 ZIP，本地发布提交为 `743bcbd`（`Release: v1.1.1`）。
`git diff --check` 通过；由于本机缺少 `pytest`、`ruff` 与 `node`，完整测试、
静态检查和前端构建未能执行。随后执行
`git push -u origin publish/v1.1.1` 时因 HTTPS 没有可用认证失败，未产生远端
分支、PR 或 main 变更。认证完成后，从该发布提交继续执行 7.4，不要重新改写
或 force push 提交。
