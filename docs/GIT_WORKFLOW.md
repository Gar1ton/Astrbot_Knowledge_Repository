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
