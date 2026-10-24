# Supabase 与 GitHub

此目录位于仓库根目录，供已连接的 Supabase GitHub Integration 读取。项目的 **Working directory** 设为 `.`；`supabase/migrations/` 中的 SQL 随 Git 提交保存。要部署到现有项目，还须在集成设置中打开 **Deploy to production**、将 Production branch name 设为 `main` 并保存，然后推送新提交。只关联 GitHub 仓库而未开启该选项，不会自动修改生产数据库。

首个迁移创建 `public.profiles`：用 `auth.users.id` 作主键，注册时自动建立档案，并为已有账号补建。行级安全策略只允许登录用户读取自己的档案、修改自己的显示名称。邮箱和密码仍由 Supabase Auth 管理。

第二个迁移建立账号私有的设备目录 `learning_inventory`、条目目录 `learning_catalog`、草稿删除记录 `learning_tombstones`，以及为后续设备间传输预留的 `learning_transfer_requests` 和私有 `learning-relay` Storage 桶。迁移不包含完整题目、原始照片或长文。目录可以定位资料，但传输、接收校验及云端备份尚未完成；不能凭目录判断已经有另一台设备持有经过验证的完整副本。规则见 [多设备学习数据同步约束](../docs/CLOUD_SYNC_ARCHITECTURE.md)。

这里不放 Project URL、密钥或数据库密码。本机登录配置在被 Git 忽略的 `subjects-learning-3/.env`；新环境按该目录的 `.env.example` 填写。`config.toml` 的 `project_id` 是本地项目标识，不是数据库连接凭证。
