# Change Report：v6.12.1 源码审阅 ZIP

## 变更

- 新增 `FIRST_RUN.md`，定义首次安装、空 DATA_HOME、合成验证和可选能力的边界。
- 更新 README 与公开测试合同，使其指向 v6.12.1 的 `344 passed` 记录。
- 生成外部 ZIP、文件清单和 SHA-256；压缩包不写回候选源码目录。

## 验证

- 检查 ZIP 根目录、文件清单、SHA-256 与解压副本逐文件哈希。
- 检查 ZIP 不包含 PDF、数据库、缓存、日志、私钥或本机数据目录。

## 未运行

浏览器 E2E、真实 PDF、Golden、Discovery/OCR、生产 DATA_HOME 均未运行。该交付为审阅包，
不是正式或开箱即用发行包。
