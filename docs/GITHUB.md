# GitHub 上传说明

目标仓库：[phragmites-0409/self-subjects-learning](https://github.com/phragmites-0409/self-subjects-learning)，主分支为 `main`。

根目录作为一个仓库，包含正式版、AI 旧版、依赖定义、模型清单和维护脚本。`runtimes/`、`归档/`、`发布包/`、两版 `data/`、`.env`、`node_modules/`、构建结果及压缩包由根目录 `.gitignore` 排除。

上传前在仓库根目录检查：

```powershell
git status --short
git add --dry-run .

# 生成可直接检查的纯源码压缩包
. ./scripts/runtime.ps1
& $python ./scripts/package-source.py
```

最新源码包和校验信息集中在 `发布包/源码/`。该目录是本地交付输出，不纳入源码提交。

后续更新在仓库根目录执行：

```powershell
git add .
git commit -m "Describe your changes"
git push origin main
```

远程地址为 `https://github.com/phragmites-0409/self-subjects-learning.git`。本机 Git 的默认 TLS 后端若报连接失败，可使用保持证书校验的 `git -c http.sslBackend=openssl push origin main`。

新用户从源码安装的流程见 [INSTALL.md](INSTALL.md)。大模型和第三方程序按原始来源下载；本机离线运行目录可以另作私人备份，无需加入 Git 历史。

仓库保留第三方来源声明，但没有替作者选择开源许可证。公开发布前由作者确定自身代码的授权方式，并继续保留已有第三方许可信息。
