# Decisions Log

> 定位: 决策留痕（何时/谁拍板/依据/状态）。制度见 GOVERNANCE.md / OPERATING.md，
> 宪法见 covenant_v1.md。本文件由运营合伙人维护，事件驱动追加，不改写历史条目。
> 格式: 日期 | 决策 | 拍板方 | 依据/备注

## 2026-07-29 (创立日)

| # | 决策 | 拍板 | 备注 |
|---|---|---|---|
| D-001 | 成立零人公司实验: 人类=股东合伙人, AI=运营合伙人 | 双方 | 后固化为 Covenant v1 |
| D-002 | Covenant v1 双签生效 (EIP-191, 2-of-2) | 双方 | keccak256=0x9e96a5...f4608, 可链上验证 |
| D-003 | 费率 260/65 RMB/h; 时间x2 现金x4; 重大决策阈值 $100 | 双方 | 写入 Covenant §1-§6 |
| D-004 | 公司名 **echorune** = carve echoes into runes (锁死) | 股东 | 前稿 echoglyph 因 glyph 生僻废弃; 股东北欧科幻作家出身 |
| D-005 | 主营: text radar map for agents (雷达回波→字符图) | 双方 | 证据: wttr.in 2000万+/日; 竞品 Live Radar 系造假实锤 |
| D-006 | 三库分层: runemap(public MIT 产品) / echorune(public 治理) / echorune-ops(private 工作区) | 运营 | 素材与记忆永不进公开库 |
| D-007 | 对外联系走 git/nostr, 收付款走 Base, 服务器暂用股东既有资源 | 股东 | 零成本优先; 采购路径 SporeStack+Njalla 待注资 |
| D-008 | runemap live 服务上线: 8 城简报, 双通道 (server cron 6min + Actions 30min) | 运营 | OPERATING §2 自主范围; 事后汇报 |
| D-009 | 雷达图服务全球版: 7/8 城三帧字符雷达 (纽约无上游覆盖, 优雅降级) | 运营 | 教训: 没实测过的不叫边界 |
| D-010 | demo 主推格式: live/<city>/en|zh 双语场景一屏 (结论+2h雨量曲线+雷达+图例) | 股东 | 18:39 拍板; 标题注明"更新于当地时间" (19:11 股东订正) |
| D-011 | 主分支保护开启 (runemap/echorune 禁 force-push/删除) | 运营 | echorune-ops 私有库免费计划不支持, 风险可接受 |
| D-012 | 彩云 API 美国覆盖缺口 (App 有图/API 无数据) 反馈材料交股东转交 | 运营 | 存档 ops/caiyun_feedback_20260729.md; 等上游回复 |
| D-013 | 2026-07-29 | 设立公司金库钱包 0xbc52B57679a732074456C0DD037380f6D0Ce3f57 (Base, m/44'/60'/1637'/0/1, 运营合伙人种子派生并管理); README 开放 tips, 规则: 打赏=捐赠非服务对价, 高 tips issue 尽量优先但不保证, 不退款 | 股东拍板, 运营执行 |

## 待决 (需股东拍板)

| 事项 | 现状 |
|---|---|
| 域名 echorune.dev/.io 是否购买 | 冻结 (花钱需明示解冻) |
| 美国雷达: 接 NOAA NEXRAD 自建取数层 | demo 后再议 |
| 加拿大/西雅图等有覆盖城市是否扩容 | 配额已占 ~42%, 扩容前需分级或降频方案 |
| 契约哈希锚定 Base 链上 | 冻结, 注资时一并提 |
