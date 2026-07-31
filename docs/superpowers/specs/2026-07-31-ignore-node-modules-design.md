# 忽略 Node.js 依赖目录设计

## 目标

停止在 Git 中跟踪仓库内所有 `node_modules` 目录，避免仓库膨胀和 Windows 长路径检出失败，同时保留本地已经安装的依赖文件。

## 变更范围

- 在根目录 `.gitignore` 中新增 `node_modules/`。
- 从 Git 索引中移除当前已跟踪的两个 `node_modules` 目录。
- 不删除本地文件，不修改业务代码、依赖清单或锁文件。

当前已跟踪范围：

- `可视化/vue-app/node_modules/`
- `outputs/stock_universe_xlsx_build/node_modules/`

## 验证

- `git check-ignore` 能匹配两个目录中的文件。
- `git ls-files` 不再返回任何 `node_modules` 文件。
- 两个本地 `node_modules` 目录仍然存在。
- 提交后工作区干净，并成功推送到 `origin/main`。

## 风险与恢复

本次只改变版本控制范围。其他环境克隆仓库后，需要根据对应的 `package.json` 和锁文件重新安装依赖。若要恢复跟踪，可删除忽略规则后，从历史提交中恢复相关文件。
