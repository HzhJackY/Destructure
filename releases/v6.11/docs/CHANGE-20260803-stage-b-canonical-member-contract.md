# Change Report — 阶段 B 标准成员检索与 OCR 证据呈现

## 修改

1. Statement Family Resolver 将匹配到的会计项目标签与完整源行分离。
2. Generic Structure Parser 传递标准成员 ID、标准显示名、别名和 OCR 数值候选。
3. Anchor Child Concept 保持标准成员身份；OCR 数值仅写入不可认证证据 JSON。
4. Guided Stage B 从 Research Definition 补全 `canonical_title` 与 aliases，改以稳定成员合同召回子表。
5. 旧 `HIERARCHICAL_CHILD_V2` 缓存不会被 V3 复用；旧浏览器会话被明确拦截，须重新认证 Anchor。

## 验证

- 18 项定向测试通过。
- 隔离 registry 的中国平安 2023：四个成员均为 1 candidate / 1 link。
- 隔离 registry 的中国太保 2023：第 74 页四个 OCR 成员均为 1 candidate / 1 link；主表 OCR 数值没有进入认证金额字段。

## 未做事项

未将 OCR 数字升级为可认证金额，未变更 Capture、Canonical 或 Merge。
