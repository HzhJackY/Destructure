# Release policy

## Release identity

- `v6.11` 是内部冻结的功能回退基线，任何公开发行准备不得修改该目录。
- `v6.12` 是后续改进线；`v6.12.1` 是其独立的公开预发行候选，身份为 `PUBLIC_PRERELEASE_UPLOAD_READY`。
- 该身份允许创建 GitHub **pre-release**，不等于生产发行认证。
- 当前强制状态是 `NOT_PRODUCTION_RELEASE_CERTIFIED`；用户要求跳过的 E2E 与真实数据门禁不得被推断为通过。

应用身份由 `version.py` 提供，交付元数据由 `BUILD_INFO.json` 描述。两者必须同时写明 v6.12.1，不得把 DATA_HOME 布局 schema 当作应用版本。

## DATA_HOME and rollback

运行数据必须位于源码目录之外，通过 `FIN_METRIC_DATA_HOME`、用户级指针或本地指针解析。公开评估默认使用全新空 DATA_HOME，不得指向生产或个人历史目录。

DATA_HOME 布局 schema 当前为 `6.10`，元数据注册表 schema 当前为 `15`；它们与应用版本 `v6.12.1` 分别演进。应用升级不得把布局 schema 字符串机械改成应用版本。迁移必须保持可审计且默认追加；回退代码不得删除、复制或重写 DATA_HOME。

## Distribution gates

公开发行至少需要全部满足：

1. 项目所有者选择并批准正式许可证，仓库根目录存在相应 `LICENSE`。
2. 完成 PyMuPDF 等所有运行/可选依赖的许可证兼容性或商业授权审查。
3. 公开清单中不含真实 PDF、Golden、用户数据、缓存、数据库、日志、密钥或机器专属配置。
4. 版本、README、BUILD_INFO、DATA_HOME 合同和依赖元数据一致。
5. 在全新环境用锁定依赖完成安装和最小可复现验证。
6. 完成秘密扫描、第三方 NOTICE/SBOM、逐文件 SHA-256 与最终 staging 审批。

v6.12.1 已按公开预发行范围闭合上述 P0；上传时必须同时提供源码、Windows 完整包、
corresponding-source/provenance companion 与 SHA-256，并勾选 pre-release。即使完成这些
步骤，也不得标记 `PRODUCTION_RELEASE_CERTIFIED`。

## Change control

公开 staging 使用 allowlist 生成，不从工作区执行 `git add .`。业务功能修改和发行工程修改应分开审阅。真实年报、用户 DATA_HOME、未经明确授权的 Golden/PDF 不得为提高演示完整度而加入候选。
