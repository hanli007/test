"""
TraderPro S6 测试用例 - 完整规范版（含管理后台，覆盖全量需求）
遵循 CLAUDE.md 用例规范：TC-XX 格式 + 多层级颗粒度 + 8个一级模块
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import xmind_helper as h
from xmind_helper import gen_id, build_xmind

# ── 基础节点构建函数 ────────────────────────────────────────────
def L(t):
    """叶子节点"""
    return h._topic(gen_id(), t, "", sc=False)

def G(t, children, sc=True):
    """分组节点"""
    return h._topic(gen_id(), t, children, sc=sc)

def STEPS(children):
    """测试步骤节点（浅蓝）"""
    return h._topic(gen_id(), "测试步骤", children, sid=h.S_STEP, sc=True)

def EXP(children):
    """预期结果节点（浅绿）"""
    return h._topic(gen_id(), "预期结果", children, sid=h.S_EXP, sc=False)

def EXTRA(text):
    """额外前置节点（浅橙）"""
    return h._topic(gen_id(), f"额外前置：{text}", "", sid=h.S_EXTRA, sc=False)

def TC(tc_id, title, steps_xml, exp_xml, extra=None):
    """用例节点（浅灰加粗）"""
    exp  = EXP(exp_xml)
    step = STEPS(steps_xml + exp)
    pre  = EXTRA(extra) if extra else ""
    return h._topic(gen_id(), f"{tc_id} {title}", pre + step, sid=h.S_TC, sc=True)

def REF(ref_id, title, fields_xml, checks_xml):
    """数据库/Apollo/Job 引用节点 —— 字段（蓝）+ 验证要点（绿）"""
    fields = h._topic(gen_id(), "关键字段", fields_xml, sid=h.S_STEP, sc=True)
    checks = h._topic(gen_id(), "验证要点", checks_xml, sid=h.S_EXP, sc=False)
    return h._topic(gen_id(), f"{ref_id} {title}", fields + checks, sid=h.S_TC, sc=True)

def MOD(title, pre, cases_xml, color_idx):
    """彩虹色一级模块"""
    return h.module_node(title, pre, cases_xml, color_idx)

# ════════════════════════════════════════════════════════════════
# 0. Web端
# ════════════════════════════════════════════════════════════════

# ── 落地页/活动页 ──
web_season_info = G("赛季信息展示",
    TC("TC-W01", "赛季基本信息正确展示",
       L("访问TraderPro S6落地页") +
       L("查看活动信息区域"),
       G("页面展示",
           L("赛季标题（seasonNo=6）正确") +
           L("activityStartTime/activityEndTime 时间格式正确（yyyy-MM-dd HH:mm:ss）") +
           L("开放品类列表展示：虚拟货币/贵金属/股票/综合")) +
       G("赛季状态提示",
           L("未开始：显示倒计时/活动未开始") +
           L("进行中：显示活动进行中") +
           L("已结束：显示活动已结束")))
)

web_signup = G("报名功能",
    TC("TC-W02", "正常报名全流程",
       L("登录满足KYC(kycFlag=2)的母账户") +
       L("活动进行中访问落地页") +
       L("点击报名按钮，确认并提交"),
       G("接口响应",
           L("返回code=0，成功") +
           L("返回participantId、demoAccountId、seasonId")) +
       G("数据库",
           L("tb_tpx_participant 新增记录，status=0，signup_time=当前时间") +
           L("tb_tpx_demo_account 新增记录，status=INIT，demo_user_id 根据历史情况") +
           L("tb_tpx_rank_record 新增4条记录（CRYPTO/METAL/STOCK/ALL），version=0，active=1")) +
       G("站内信",
           L("用户收到 MSG_TPX_01 报名成功通知"))) +

    TC("TC-W03", "活动未开始时报名",
       L("赛季status=0（未开始）时访问落地页") +
       L("点击报名"),
       G("前端提示",
           L("报名入口置灰或提示活动未开始")) +
       G("接口响应（若前端未拦截）",
           L("返回错误码70001"))) +

    TC("TC-W04", "活动已结束时报名",
       L("赛季status=2（已结束）时访问落地页") +
       L("点击报名"),
       G("前端提示",
           L("报名入口提示活动已结束")) +
       G("接口响应（若前端未拦截）",
           L("返回错误码70001"))) +

    TC("TC-W05", "KYC未完成用户报名",
       L("登录kycFlag!=2的账户") +
       L("活动进行中点击报名"),
       L("返回错误码70002，前端提示需完成KYC")) +

    TC("TC-W06", "重复报名同赛季",
       L("已报名S6的用户再次点击报名"),
       L("返回错误码70003，提示已报名该赛季")) +

    TC("TC-W07", "存在活跃老TraderPro记录的用户报名",
       L("该用户有status=TRADING的老TraderPro参与记录") +
       L("活动进行中点击报名"),
       L("返回错误码70004")) +

    TC("TC-W08", "子账户不允许报名",
       L("使用子账户登录") +
       L("活动进行中点击报名"),
       L("返回错误码70007")) +

    TC("TC-W09", "统一账户不允许报名",
       L("使用统一账户登录") +
       L("活动进行中点击报名"),
       L("返回错误码70008")) +

    TC("TC-W10", "TraderPro二阶段用户不允许报名",
       L("使用TraderPro毕业阶段（phase2）用户登录") +
       L("活动进行中点击报名"),
       L("返回错误码70009")) +

    TC("TC-W11", "模拟盘账户不允许报名",
       L("使用模拟盘账户登录") +
       L("活动进行中点击报名"),
       L("返回错误码70010")) +

    TC("TC-W12", "Apollo signupOpen=false 时报名被全局关闭",
       L("Apollo tpx.config.signupOpen=false"),
       L("报名接口返回报名未开放错误（70001或相应错误提示）"),
       extra="Apollo tpx.config.signupOpen 设为 false")
)

web_rank = G("排行榜",
    TC("TC-W13", "品类Tab切换与排行榜数据展示",
       L("已报名用户访问排行榜页面") +
       L("依次切换虚拟货币/贵金属/股票/综合四个Tab"),
       G("展示正确性",
           L("每个品类榜单独立展示，按ROI降序排列") +
           L("展示字段：排名/用户昵称/头像/ROI/成交笔数/胜率") +
           L("未成交用户(trade_count=0)不出现在榜单中")) +
       G("myRank个人排名",
           L("已登录已报名且有成交记录：展示个人排名和ROI") +
           L("已登录已报名但无成交记录：myRank=null或未入榜"))) +

    TC("TC-W14", "同ROI排名规则验证",
       L("准备两个ROI相同的参赛用户，用户A先达到该ROI，用户B后达到"),
       L("用户A排名在用户B之前（update_time升序，先达到者优先）")) +

    TC("TC-W15", "Apollo rankOpen=false 时排行榜不可访问",
       L("Apollo tpx.config.rankOpen=false") +
       L("访问排行榜页面"),
       L("排行榜不展示或提示功能暂未开放"),
       extra="Apollo tpx.config.rankOpen 设为 false")
)

web_demo = G("Demo账户与ROI展示",
    TC("TC-W16", "报名成功后Demo账户初始余额展示",
       L("报名成功后进入个人参赛信息页") +
       L("查看Demo账户余额"),
       G("Job未执行前",
           L("status=INIT，余额可能展示为0或初始化中")) +
       G("Job执行完成后",
           L("status=INITED，余额展示10000.00000000 USDT"))) +

    TC("TC-W17", "ROI实时数据展示（30分钟刷新）",
       L("用户完成合约交易后等待下一个30分钟快照") +
       L("刷新个人参赛数据"),
       G("ROI数据",
           L("各品类ROI随交易盈亏正确变动") +
           L("综合ROI与全账户权益一致")) +
       G("ROI数值精度",
           L("保留6位小数，与接口返回一致")))
)

web_roi_trend = G("ROI走势图",
    TC("TC-W18", "ROI走势图按30分钟间隔展示",
       L("已报名且有成交记录的用户访问ROI走势页") +
       L("查看走势图"),
       G("走势数据",
           L("按snapshotTime升序展示，间隔30分钟") +
           L("报名时ROI=0，随交易变动") +
           L("活动结束后走势数据不再更新")))
)

web_season_notice = G("站内信通知",
    TC("TC-W19", "活动开始站内信（MSG_TPX_02）",
       L("activity_start_time到达，TraderProXSeasonStatusJob执行"),
       L("所有已报名用户收到MSG_TPX_02 活动开始通知")) +
    TC("TC-W20", "活动即将结束站内信（MSG_TPX_04/05）",
       L("距activity_end_time提前48h时触发MSG_TPX_04") +
       L("距activity_end_time提前24h时触发MSG_TPX_05"),
       L("已报名用户分别收到两条活动即将结束提醒")) +
    TC("TC-W21", "活动正式结束站内信（MSG_TPX_06）",
       L("activity_end_time到达，赛季状态流转为已结束"),
       L("已报名用户收到MSG_TPX_06 活动正式结束通知")) +
    TC("TC-W22", "获奖通知（MSG_TPX_08）与未获奖通知（MSG_TPX_10）",
       L("结算Job完成计算并发放奖励后"),
       G("获奖用户",
           L("收到MSG_TPX_08 获奖通知，内容包含奖励类型和金额")) +
       G("未获奖用户",
           L("收到MSG_TPX_10 未获奖安慰通知")))
)

mod_web = MOD("Web端",
    "已登录、网络正常、使用PC Web浏览器访问",
    web_season_info + web_signup + web_rank + web_demo + web_roi_trend + web_season_notice,
    0)

# ════════════════════════════════════════════════════════════════
# 1. H5
# ════════════════════════════════════════════════════════════════

h5_cases = G("报名功能",
    TC("TC-H01", "H5报名全流程",
       L("iOS Safari/Android Chrome打开H5落地页") +
       L("完成KYC的用户在活动进行中点击报名"),
       G("功能正确性",
           L("报名成功，与Web端逻辑一致")) +
       G("H5适配",
           L("报名弹窗布局正常，无内容溢出/截断"))) +
    TC("TC-H02", "H5各异常场景报名",
       L("分别使用以下场景测试：KYC未完成/活动时间外/重复报名/子账户/统一账户/模拟盘/phase2用户"),
       L("错误提示文案正确，符合H5界面布局"))
) + G("排行榜",
    TC("TC-H03", "H5排行榜展示与品类切换",
       L("H5页面打开排行榜，依次切换四个品类Tab"),
       G("数据正确性",
           L("排行榜数据与Web端一致")) +
       G("H5适配",
           L("Tab切换流畅，列表滚动正常") +
           L("用户昵称/头像在H5屏幕宽度下无溢出")))
) + G("ROI展示与走势",
    TC("TC-H04", "H5 Demo账户余额与ROI展示",
       L("H5打开个人参赛数据页面"),
       G("展示正确性",
           L("数值与Web端一致")) +
       G("H5适配",
           L("高精度小数（6位）无截断") +
           L("千分位格式一致")))
)

mod_h5 = MOD("H5",
    "使用iOS Safari/Android Chrome浏览器访问H5版本",
    h5_cases,
    1)

# ════════════════════════════════════════════════════════════════
# 2. 服务端
# ════════════════════════════════════════════════════════════════

# 5.1 报名接口
svr_signup = G("5.1 报名接口 POST /v1/traderPro/signup",
    TC("TC-S01", "正常报名 — 返回参数完整性",
       L("满足所有报名条件的用户提交报名请求") +
       L("seasonId=有效赛季ID"),
       G("接口响应",
           L("code=0，msg=success") +
           L("data.participantId: Long，对应tb_tpx_participant.id") +
           L("data.demoAccountId: Long，对应tb_tpx_demo_account.id") +
           L("data.seasonId: Long，与入参一致"))) +

    TC("TC-S02", "报名时间校验 — 活动未开始（70001）",
       L("当前时间 < activity_start_time，提交报名"),
       L("返回错误码70001 TPX_SIGNUP_NOT_OPEN")) +

    TC("TC-S03", "报名时间校验 — 活动已结束（70001）",
       L("当前时间 > activity_end_time，提交报名"),
       L("返回错误码70001 TPX_SIGNUP_NOT_OPEN")) +

    TC("TC-S04", "KYC校验（70002）",
       L("kycFlag=0或1的账户提交报名"),
       L("返回错误码70002 TPX_KYC_NOT_COMPLETED")) +

    TC("TC-S05", "重复报名同赛季（70003）",
       L("同userId同seasonId已有tb_tpx_participant记录，再次提交"),
       L("返回错误码70003 TPX_ALREADY_SIGNED_UP")) +

    TC("TC-S06", "老TraderPro活跃记录检查（70004）",
       L("用户有status=TRADING的老版TraderPro参与记录，提交报名"),
       L("返回错误码70004 TPX_ACTIVE_TRADER_PRO_EXISTS")) +

    TC("TC-S07", "操作过于频繁限流（70005）",
       L("同一用户短时间内高频提交报名请求"),
       L("返回错误码70005 TPX_OPERATION_TOO_FREQUENT")) +

    TC("TC-S08", "子账户不允许报名（70007）",
       L("使用子账户Token调用报名接口"),
       L("返回错误码70007 TPX_SUB_ACCOUNT_NOT_ALLOWED")) +

    TC("TC-S09", "统一账户不允许报名（70008）",
       L("使用统一账户Token调用报名接口"),
       L("返回错误码70008 TPX_UNIFIED_ACCOUNT_NOT_ALLOWED")) +

    TC("TC-S10", "TraderPro二阶段用户不允许报名（70009）",
       L("TraderPro毕业阶段（phase2）用户调用报名接口"),
       L("返回错误码70009 TPX_TRADER_PRO_PHASE2_NOT_ALLOWED")) +

    TC("TC-S11", "模拟盘不允许报名（70010）",
       L("模拟盘账户调用报名接口"),
       L("返回错误码70010 TPX_PAPER_TRADING_NOT_ALLOWED")) +

    TC("TC-S12", "Apollo signupOpen=false 全局关闭报名",
       L("Apollo tpx.config.signupOpen=false") +
       L("满足所有条件的用户调用报名接口"),
       L("报名被拦截，接口返回报名未开放错误"),
       extra="Apollo tpx.config.signupOpen 设为 false") +

    TC("TC-S13", "并发防重 — 同用户并发两次报名",
       L("同userId并发发起两次报名请求") +
       L("Redis分布式锁 tpx:signup:lock:{userId}，TTL=5s"),
       G("结果",
           L("仅有一次报名成功，tb_tpx_participant只有一条记录")) +
       G("数据库唯一索引",
           L("uk_season_user(season_id, user_id) 约束生效"))) +

    TC("TC-S14", "Demo账户跨赛季复用 — 有历史demo_user_id",
       L("该用户在历史赛季已有tb_tpx_demo_account记录，demo_user_id!=null") +
       L("新赛季报名"),
       G("数据库",
           L("新赛季tb_tpx_demo_account.demo_user_id=已有值") +
           L("status=INIT，等待Job重置余额")) +
       G("Job执行后",
           L("调用资产服务重置该子账户余额为10000") +
           L("status更新为INITED"))) +

    TC("TC-S15", "Demo账户首次创建 — 无历史demo_user_id",
       L("该用户从未参与过TraderPro，无历史Demo子账户") +
       L("报名"),
       G("数据库",
           L("tb_tpx_demo_account.demo_user_id=null，status=INIT")) +
       G("Job执行后",
           L("调用资产服务新建Demo子账户，回填demo_user_id") +
           L("充值10000 USDT，status=INITED")))
)

# 5.2 排行榜接口
svr_rank = G("5.2 排行榜接口 POST /v1/traderPro/rank",
    TC("TC-S16", "各品类榜单数据正确性",
       L("category=1(CRYPTO)/2(METAL)/3(STOCK)/0(ALL) 分别查询") +
       L("seasonId=有效赛季ID"),
       G("接口响应结构",
           L("data.total: 当前品类入榜总人数") +
           L("data.rankList[].rank: 从1开始连续排名") +
           L("data.rankList[].roi: 按ROI降序排列") +
           L("data.rankList[].tradeCount/winRate 字段存在")) +
       G("排名规则",
           L("trade_count=0的用户不出现在榜单中") +
           L("同ROI时update_time升序（先达到者排名靠前）"))) +

    TC("TC-S17", "myRank字段 — 已入榜用户",
       L("当前登录用户有成交记录（trade_count>0）") +
       L("查询排行榜接口"),
       G("myRank字段",
           L("data.myRank非null") +
           L("rank/userId/nickname/roi/tradeCount/winRate 字段完整") +
           L("myRank通过实时查询，不走缓存"))) +

    TC("TC-S18", "myRank字段 — 未入榜用户",
       L("当前登录用户无成交记录（trade_count=0）") +
       L("查询排行榜接口"),
       L("data.myRank=null")) +

    TC("TC-S19", "Guava缓存验证（5分钟过期/30秒异步刷新）",
       L("首次查询某品类榜单，记录响应时间t1") +
       L("立即再次查询同品类"),
       G("缓存命中",
           L("第二次查询无DB查询，响应更快")) +
       G("缓存Key隔离",
           L("不同品类缓存独立，修改CRYPTO数据不影响METAL缓存")) +
       G("缓存失效",
           L("5分钟后强制重加载DB数据"))) +

    TC("TC-S20", "Apollo rankOpen=false 排行榜关闭",
       L("Apollo tpx.config.rankOpen=false") +
       L("查询排行榜接口"),
       L("接口返回排行榜不可用或空数据"),
       extra="Apollo tpx.config.rankOpen 设为 false") +

    TC("TC-S21", "入参校验",
       L("seasonId=null / category=999 / category=-1"),
       L("返回错误码30000 PARAM_IS_ERROR"))
)

# 5.3 我的排名接口
svr_myrank = G("5.3 我的排名接口 GET /v1/traderPro/myRank",
    TC("TC-S22", "已报名有成交记录用户查询",
       L("已报名且trade_count>0的用户") +
       L("category=CRYPTO/METAL/STOCK/ALL 分别查询"),
       G("接口响应",
           L("data.rank: 当前名次（正整数，>=1）") +
           L("data.roi: ROI，保留6位小数") +
           L("data.tradeCount: 当前品类成交总笔数") +
           L("data.winRate: 胜率，保留4位小数") +
           L("data.totalParticipants: 当前品类入榜总人数") +
           L("data.category: 与入参一致"))) +

    TC("TC-S23", "已报名无成交记录用户查询",
       L("已报名但无任何成交记录的用户查询myRank"),
       G("接口响应",
           L("HTTP 200，code=0") +
           L("data.rank=-1") +
           L("data.roi=0.000000") +
           L("data.tradeCount=0"))) +

    TC("TC-S24", "入参校验",
       L("seasonId=null / category=INVALID"),
       L("返回错误码30000 PARAM_IS_ERROR"))
)

# 5.4 赛季信息接口
svr_season = G("5.4 赛季信息接口 GET /v1/traderPro/season",
    TC("TC-S25", "指定seasonId查询",
       L("传入有效seasonId"),
       G("接口响应",
           L("data.seasonId/seasonNo/title 正确") +
           L("data.activityStartTime/activityEndTime 格式正确") +
           L("data.status: 0/1/2 与当前赛季状态一致") +
           L("data.statusDesc: 未开始/进行中/已结束") +
           L("data.demoInitialBalance=10000.00000000") +
           L("data.categories: 包含CRYPTO/METAL/STOCK/ALL"))) +

    TC("TC-S26", "不传seasonId — 返回最新赛季",
       L("不传seasonId参数"),
       L("返回id最大的赛季（按id降序取第一条）")) +

    TC("TC-S27", "seasonId不存在 — 降级返回null",
       L("传入不存在的seasonId"),
       G("降级处理",
           L("code=0，data=null") +
           L("不抛错误码")))
)

# 5.5 ROI走势接口（注意：tech doc 3.3.4说明该接口已删除，与5.5有矛盾）
svr_roi_trend = G("5.5 ROI走势接口 GET /v1/traderPro/roiTrend【注意：3.3.4节说明接口已删除，需与研发确认】",
    TC("TC-S28", "ROI走势接口存在性确认【待确认】",
       L("【需确认】技术文档3.3.4节：/roiTrend API同步删除") +
       L("但5.5节仍有接口文档 — 需与研发确认该接口是否上线") +
       L("若上线：按5.5节测试走势数据") +
       L("若已删除：验证接口返回404或提示不存在"),
       G("若接口存在",
           L("trend数据按snapshotTime升序，间隔30分钟") +
           L("未报名时返回空走势列表（code=0，data.trend=[]）") +
           L("入参seasonId=null/category=INVALID → 错误码30000")))
)

# 5.6 Inner接口：发奖重试
svr_reward_retry = G("5.6 [Inner] 发奖重试 POST /inner/v1/traderPro/reward/retry",
    TC("TC-S29", "批量重试全部失败记录",
       L("结算后有CouponGrantRecord.status=END的失败记录") +
       L("只传seasonId，不传userIds") +
       L("携带内部鉴权Token X-Inner-Token"),
       G("接口响应",
           L("data.retriedCount = 本次扫描到的失败记录总数") +
           L("data.successCount = 重试后流转为GRANT_ING的记录数") +
           L("data.failedCount = 仍失败的记录数"))) +

    TC("TC-S30", "指定用户精确重试",
       L("传入seasonId + userIds=[userId1, userId2]") +
       L("只重试指定用户的发奖记录"),
       L("只有指定userId的记录被重试，其他记录不受影响")) +

    TC("TC-S31", "无鉴权Token",
       L("不携带X-Inner-Token调用内部接口"),
       L("返回鉴权失败"))
)

# 5.7 Inner接口：违规处理
svr_violation = G("5.7 [Inner] 违规处理 POST /inner/v1/traderPro/violation/process",
    TC("TC-S32", "正常违规处理流程",
       L("传入seasonId/userId/reason") +
       L("携带X-Inner-Token"),
       G("接口响应",
           L("data.processed=true")) +
       G("数据库",
           L("tb_tpx_participant.status=1（违规冻结）")) +
       G("合约",
           L("该用户所有合约持仓已被强制平仓")) +
       G("站内信",
           L("用户收到MSG_TPX_07 违规处理完成通知")) +
       G("审计日志",
           L("reason写入审计日志，记录操作人信息"))) +

    TC("TC-S33", "reason字段超500字符",
       L("reason传入501字符以上"),
       L("返回参数校验错误")) +

    TC("TC-S34", "无鉴权Token",
       L("不携带X-Inner-Token"),
       L("返回鉴权失败"))
)

mod_server = MOD("服务端",
    "通过API调用，关注接口逻辑、入参校验、错误码、DB数据正确性",
    svr_signup + svr_rank + svr_myrank + svr_season + svr_roi_trend + svr_reward_retry + svr_violation,
    2)

# ════════════════════════════════════════════════════════════════
# 3. 业务流
# ════════════════════════════════════════════════════════════════

flow_signup_chain = G("报名全链路",
    TC("TC-F01", "报名→Demo账户初始化完整链路",
       L("用户提交报名请求") +
       L("等待TraderProXDemoAccountCompensateJob执行（每分钟轮询）"),
       G("报名成功",
           L("tb_tpx_participant.status=0 signup_time正确") +
           L("tb_tpx_demo_account.status=INIT")) +
       G("Job执行完成",
           L("tb_tpx_demo_account.status=INITED") +
           L("demo_user_id回填正确") +
           L("Demo子账户余额=10000 USDT（调用资产服务确认）")) +
       G("排行榜初始化",
           L("tb_tpx_rank_record新增4条（CRYPTO/METAL/STOCK/ALL）") +
           L("version=0，active=1，roi=0，trade_count=0")))
)

flow_roi_chain = G("成交→ROI更新链路（MQ+快照双路径）",
    TC("TC-F02", "成交统计MQ实时更新链路",
       L("用户在Demo子账户完成一笔合约平仓") +
       L("Canal Binlog → DemoContractOrderTriggerHandler → TRADER_PRO_X_INCOME_STATISTIC") +
       L("TraderProXStatisticIncomeConsumer消费"),
       G("数据库更新",
           L("对应品类的tb_tpx_rank_record.trade_count+1") +
           L("盈利平仓时win_count+1") +
           L("win_rate=win_count/trade_count 正确更新")) +
       G("幂等保障",
           L("Redis tpx:income:dedup:{seasonId}:{orderId} 已存在时跳过重复消费")) +
       G("ALL品类",
           L("category=ALL的rank_record行同步更新trade_count"))) +

    TC("TC-F03", "ROI快照Job 30分钟更新链路",
       L("等待TraderProXRoiSnapshotJob触发（每30分钟）") +
       L("用户有持仓或历史平仓记录"),
       G("历史盈亏增量更新",
           L("InnerHistoryPositionQueryFeignClient查询lastEndId之后新记录") +
           L("positionProfits按symbolId路由品类") +
           L("tb_tpx_history_pnl.cumulative_pnl正确累加") +
           L("last_end_id更新为本次处理的最大id")) +
       G("浮动盈亏",
           L("InnerAccountFeignClient查询当前positionDTOs.unrealised") +
           L("按symbolId路由到对应品类")) +
       G("ROI计算",
           L("品类ROI=(cumulative_pnl+unrealised)/10000") +
           L("综合ROI=(sum(usdtEquity)-10000)/10000")) +
       G("排行榜更新",
           L("tb_tpx_rank_record.roi/max_profit_rate/max_retracement 乐观锁更新") +
           L("version字段自增")) +
       G("symbolId不在任何品类",
           L("该盈亏仅计入ALL，不计入分品类ROI")))
)

flow_settlement_chain = G("赛季结束→结算发奖链路",
    TC("TC-F04", "赛季状态机流转",
       L("等待activity_end_time到达") +
       L("TraderProXSeasonStatusJob每分钟检查"),
       G("状态流转",
           L("tb_tpx_season.status: 1(进行中) → 2(已结束)")) +
       G("站内信",
           L("所有参赛用户收到MSG_TPX_06 活动正式结束")) +
       G("MQ",
           L("发送TRADER_PRO_X_SEASON_STATUS_CHANGE消息通知下游"))) +

    TC("TC-F05", "最终ROI快照（活动结束边界处理）",
       L("activity_end_time到达后，TraderProXRoiSnapshotJob触发") +
       L("season.status=已结束 且 final_snapshot_done=false"),
       G("边界处理",
           L("effectiveEndTime=activity_end_time（不用now）") +
           L("执行最后一次历史仓位查询和ROI计算")) +
       G("完成标记",
           L("tb_tpx_history_pnl.final_snapshot_done=1")) +
       G("后续轮次",
           L("final_snapshot_done=1后，Job直接跳过"))) +

    TC("TC-F06", "结算Job执行链路",
       L("TraderProXSeasonStatusJob触发TraderProXSettlementJob") +
       L("Redis SETNX tpx:settlement:lock:{seasonId}"),
       G("分布式锁",
           L("锁抢占成功后执行结算逻辑") +
           L("TTL=30分钟，防止因故卡住")) +
       G("奖励计算",
           L("读取tb_tpx_rank_record active=1按ROI降序排名") +
           L("按reward_config.categoryRewards计算品类榜TOP N获奖名单") +
           L("按reward_config.totalRewards计算综合榜TOP N获奖名单")) +
       G("写入发放队列",
           L("每条奖励调用couponUseService.grantPlan写入CouponGrantRecord") +
           L("CouponGrantRecord.ticketStatus=CAN_GRANT") +
           L("srcId幂等：结算Job重跑时根据tb_tpx_reward.src_id!=null跳过已提交记录")) +
       G("奖励记录",
           L("tb_tpx_reward新增记录，status=0(PENDING)")) +
       G("站内信",
           L("获奖用户收到MSG_TPX_08") +
           L("未获奖用户收到MSG_TPX_10")))
)

flow_reward_dispatch = G("异步实际发券链路（compensateCouponRecordJob）",
    TC("TC-F07", "发券Job正常发放流程",
       L("CouponGrantRecord.ticketStatus=CAN_GRANT 记录存在") +
       L("现有compensateCouponRecordJob定期执行"),
       G("状态流转",
           L("CAN_GRANT → GRANT_ING（调用assets券系统API）") +
           L("assets确认 → GRANT_SUCCESS")) +
       G("用户侧验证",
           L("获奖用户账户中出现对应奖励券"))) +

    TC("TC-F08", "发券失败重试机制",
       L("模拟assets券系统调用失败") +
       L("观察重试逻辑"),
       G("失败处理",
           L("状态流转为END（超过重试次数）") +
           L("触发告警通知")) +
       G("人工补发",
           L("调用inner接口 /inner/v1/traderPro/reward/retry 触发重试") +
           L("成功后状态流转为GRANT_ING → GRANT_SUCCESS")))
)

flow_risk_chain = G("风控检测→违规处理链路",
    TC("TC-F09", "仓位比例异常风控链路",
       L("构造持仓名义价值/账户余额 > tpx.risk.max_position_ratio 的用户") +
       L("等待TraderProXRiskCheckJob触发（每小时整点）") +
       L("等待第二次触发（2小时后）"),
       G("第一次触发",
           L("Redis写入tpx:risk:suspect:{userId}:{seasonId}，TTL=2h")) +
       G("连续两次触发",
           L("写入tb_tpx_violation_suspect，等待人工审核")) +
       G("管理后台确认违规",
           L("调用/inner/v1/traderPro/violation/process") +
           L("强制平仓+tb_tpx_participant.status=1+发MSG_TPX_07")))
)

mod_flow = MOD("业务流",
    "关注完整数据链路：服务调用→DB写入→MQ传递→状态流转→对外展示",
    flow_signup_chain + flow_roi_chain + flow_settlement_chain + flow_reward_dispatch + flow_risk_chain,
    3)

# ════════════════════════════════════════════════════════════════
# 4. 管理后台
# ════════════════════════════════════════════════════════════════

admin_season = G("赛季配置管理",
    TC("TC-A01", "新增赛季配置",
       L("进入赛季管理页面，点击新增") +
       L("填写所有必填字段并提交"),
       G("必填校验",
           L("seasonNo/title/activityStartTime/activityEndTime/categories 均不可为空")) +
       G("时间合法性",
           L("activityEndTime 必须晚于 activityStartTime")) +
       G("数据库",
           L("tb_tpx_season 新增一条记录，status=0（未开始）") +
           L("categories字段为JSON数组，如[CRYPTO,METAL,STOCK,ALL]"))) +

    TC("TC-A02", "奖励配置（rewardConfig JSON）填写与校验",
       L("填写reward_config JSON字段：品类榜配置（CRYPTO/METAL/STOCK）+ 综合榜配置（totalRewards）+ expertConversionConfig") +
       L("提交赛季配置"),
       G("JSON格式校验",
           L("格式错误时保存失败并提示")) +
       G("品类榜配置",
           L("categoryRewards下包含CRYPTO/METAL/STOCK三个品类") +
           L("每品类tiers包含rankFrom/rankTo/couponType/amount字段")) +
       G("综合榜配置",
           L("totalRewards.tiers包含rankFrom/rankTo/couponType/amount字段")) +
       G("专家转化配置",
           L("expertConversionConfig.minRoiPercent: 最低ROI门槛") +
           L("expertConversionConfig.minTradeCount: 最低成交笔数") +
           L("expertConversionConfig.requireNoViolation: 是否要求无违规"))) +

    TC("TC-A03", "风控配置（riskConfig JSON）填写",
       L("填写risk_config JSON字段：最大单日亏损率/不活跃天数/最大回撤等"),
       G("Apollo回落",
           L("risk_config字段优先级高于Apollo全局默认值")) +
       G("数据库",
           L("tb_tpx_season.risk_config字段正确存储"))) +

    TC("TC-A04", "查看赛季状态流转",
       L("赛季创建后，在管理后台跟踪状态变化") +
       L("等待activity_start_time到达，TraderProXSeasonStatusJob执行") +
       L("等待activity_end_time到达，TraderProXSeasonStatusJob执行"),
       G("状态流转",
           L("0(未开始) → 1(进行中) → 2(已结束)")) +
       G("页面刷新后",
           L("状态描述文案与状态码一致")))
)

admin_violation = G("违规审核",
    TC("TC-A05", "查看违规待审核列表",
       L("TraderProXRiskCheckJob检测到异常用户后") +
       L("进入管理后台违规审核页面"),
       G("页面展示",
           L("展示tb_tpx_violation_suspect中的待审核用户列表") +
           L("包含用户UID/检测到的异常类型/首次检测时间"))) +

    TC("TC-A06", "确认违规处理",
       L("选中待审核用户，填写违规原因（必填，最大500字符）") +
       L("点击确认违规"),
       G("操作结果",
           L("data.processed=true")) +
       G("数据库",
           L("tb_tpx_participant.status=1（违规冻结）")) +
       G("合约",
           L("所有合约持仓已强制平仓")) +
       G("站内信",
           L("用户收到MSG_TPX_07")) +
       G("审计",
           L("操作人信息和reason写入审计日志"))) +

    TC("TC-A07", "误报解除",
       L("选中待审核用户，点击误报解除"),
       G("Redis",
           L("tpx:risk:suspect:{userId}:{seasonId} Key被清除")) +
       G("用户状态",
           L("tb_tpx_participant.status保持0，正常参赛"))) +

    TC("TC-A08", "违规原因reason字段校验",
       L("reason=空 / reason>500字符"),
       G("为空时",
           L("提示reason不能为空")) +
       G("超500字符时",
           L("提示长度超限")))
)

admin_reward = G("发奖管理",
    TC("TC-A09", "查看结算后发奖状态",
       L("结算Job执行完成后进入发奖管理页面"),
       G("发奖记录展示",
           L("展示tb_tpx_reward中各用户发奖状态") +
           L("状态：0=待发放 1=已发放 2=发放失败 3=发放中"))) +

    TC("TC-A10", "手动触发发奖重试（状态=END的失败记录）",
       L("发现status=END的失败发奖记录") +
       L("通过管理后台或调用/inner/v1/traderPro/reward/retry接口"),
       G("批量重试",
           L("不传userIds时重试该赛季所有END状态记录")) +
       G("精确重试",
           L("传入特定userIds只重试指定用户")))
)

mod_admin = MOD("管理后台",
    "通过运营后台系统进行操作，关注配置生效、审批流程、人工干预场景",
    admin_season + admin_violation + admin_reward,
    4)

# ════════════════════════════════════════════════════════════════
# 5. 数据库
# ════════════════════════════════════════════════════════════════

db_season = REF("DB-01", "tb_tpx_season（赛季主表）",
    L("id: BIGINT PK 主键自增") +
    L("season_no: INT 赛季编号（如6）") +
    L("title: VARCHAR(64) 赛季标题") +
    L("activity_start_time: DATETIME 活动开始时间（报名开放+交易开始）") +
    L("activity_end_time: DATETIME 活动结束时间（MQ停止消费+触发结算）") +
    L("demo_initial_balance: DECIMAL(20,8) Demo初始资金，默认10000") +
    L("status: TINYINT 0=未开始 1=进行中 2=已结束") +
    L("categories: VARCHAR(128) 本赛季品类列表JSON，如[CRYPTO,METAL,STOCK,ALL]") +
    L("reward_config: TEXT 奖励配置JSON（品类榜+综合榜名次→券tier配置+expertConversionConfig）") +
    L("risk_config: TEXT 风控阈值JSON（优先级高于Apollo全局默认值）") +
    L("create_time/update_time/is_deleted"),
    L("赛季状态流转（0→1→2）由TraderProXSeasonStatusJob驱动") +
    L("reward_config中expertConversionConfig包含minRoiPercent/minTradeCount/requireNoViolation") +
    L("不同赛季categories字段可只开放部分品类，结算时仅计算该列表内品类")
)

db_participant = REF("DB-02", "tb_tpx_participant（参赛记录表）",
    L("id: BIGINT PK") +
    L("season_id: BIGINT 关联赛季") +
    L("user_id: BIGINT 用户ID") +
    L("signup_time: DATETIME 报名时间（ROI起算时间）") +
    L("status: TINYINT 0=正常 1=违规冻结 2=主动退出") +
    L("唯一索引: uk_season_user(season_id, user_id)"),
    L("signup_time作为ROI历史仓位查询的起算时间（固定不变）") +
    L("TraderProXStatisticIncomeConsumer分发前先检查status=0（活跃）") +
    L("Guava Cache缓存活跃参与者列表，TTL=5分钟")
)

db_demo = REF("DB-03", "tb_tpx_demo_account（Demo账户表）",
    L("id: BIGINT PK") +
    L("season_id: BIGINT") +
    L("user_id: BIGINT") +
    L("demo_user_id: BIGINT Demo子账户UID（跨赛季复用时写入已有值，新建时由Job回填）") +
    L("balance: DECIMAL(20,8) 当前余额，初始化后=10000") +
    L("initial_balance: DECIMAL(20,8) 初始资金=10000") +
    L("status: TINYINT 0=INIT（待初始化） 1=INITED（已就绪）") +
    L("唯一索引: uk_season_user(season_id, user_id)") +
    L("查询索引: idx_user_id(user_id) — 用于跨赛季查找已有demo_user_id"),
    L("Job扫描status=INIT且create_time<now()-5s的记录执行补偿") +
    L("跨赛季复用：先查历史demo_user_id，有则复用并重置余额，无则新建") +
    L("幂等：Redis锁tpx:demo:init:lock:{userId}:{seasonId}，TTL=60s")
)

db_rank = REF("DB-04", "tb_tpx_rank_record（排行榜记录表）",
    L("id: BIGINT PK") +
    L("season_id/user_id") +
    L("category: TINYINT 0=综合ALL 1=虚拟货币CRYPTO 2=贵金属METAL 3=股票STOCK") +
    L("version: INT 乐观锁版本号，初始0，每次更新+1") +
    L("active: TINYINT 1=正常参赛") +
    L("total_profit: DECIMAL(20,8) 累计已实现盈亏（USDT）") +
    L("roi: DECIMAL(10,6) ROI百分比（冗余存储供排行榜直接读取）") +
    L("trade_count: INT 成交笔数（MQ实时更新）") +
    L("win_count: INT 盈利笔数（MQ实时更新）") +
    L("win_rate: DECIMAL(6,4) 胜率=win_count/trade_count（MQ实时更新）") +
    L("max_profit_rate: DECIMAL(10,6) 历史最高ROI（快照Job更新）") +
    L("max_retracement: DECIMAL(10,6) 最大回撤（快照Job计算）") +
    L("唯一索引: uk_season_user_category(season_id, user_id, category)") +
    L("查询索引: idx_season_category_active_roi(season_id, category, active, roi DESC)"),
    L("每用户每品类只有一行（无多版本逻辑）") +
    L("违规处理：不重置排名数据，仅冻结tb_tpx_participant.status=1") +
    L("乐观锁更新：UPDATE...WHERE id=? AND version=?") +
    L("排行榜查询：active=1且trade_count>0入榜，按roi DESC排序")
)

db_history_pnl = REF("DB-05", "tb_tpx_history_pnl（历史已实现盈亏缓存表）",
    L("id: BIGINT PK") +
    L("season_id/user_id") +
    L("category: TINYINT 0=ALL 1=CRYPTO 2=METAL 3=STOCK") +
    L("version: INT 对应rank_record.version，重置后新版本从0开始") +
    L("cumulative_pnl: DECIMAL(20,8) 自报名时间起累计已平仓盈亏（USDT）") +
    L("last_end_id: BIGINT 上次已处理历史仓位最大id（增量游标）") +
    L("final_snapshot_done: TINYINT 1=已完成最终快照") +
    L("唯一索引: uk_season_user_category(season_id, user_id, category)"),
    L("增量优化：每次快照Job只查lastEndId之后的新记录，叠加到cumulative_pnl") +
    L("ROI计算：categoryRoi=(cumulative_pnl+unrealised)/10000") +
    L("最终快照：season结束后final_snapshot_done=1，后续Job轮次跳过") +
    L("每用户每品类只有一行记录（版本通过version字段区分）")
)

db_reward = REF("DB-06", "tb_tpx_reward（奖励发放表）",
    L("id: BIGINT PK") +
    L("season_id/user_id") +
    L("reward_type: TINYINT 1=品类奖励 2=综合榜奖励 3=特别奖励") +
    L("category: TINYINT 品类（品类奖励时有值）") +
    L("rank: INT 获奖名次") +
    L("coupon_amount: DECIMAL(20,8) 券面值") +
    L("src_id: BIGINT 幂等Key，关联CouponGrantRecord.src_id") +
    L("status: TINYINT 0=PENDING 1=SUCCESS 2=FAILED 3=PROCESSING") +
    L("retry_count: INT 重试次数"),
    L("状态机：0(PENDING)→3(PROCESSING)→1(SUCCESS) / →2(FAILED)→0(重置后重试)") +
    L("防超发：CAS status=0→3防并发，srcId+唯一约束防重复写CouponGrantRecord") +
    L("防漏发：逐条独立事务，单条失败不影响其他记录") +
    L("结算Job重跑幂等：src_id!=null的记录跳过")
)

mod_db = MOD("数据库",
    "技术文档所有涉及表与关键字段汇总，含索引/约束/业务逻辑",
    db_season + db_participant + db_demo + db_rank + db_history_pnl + db_reward,
    5)

# ════════════════════════════════════════════════════════════════
# 6. Apollo
# ════════════════════════════════════════════════════════════════

ap_main = REF("AP-01", "tpx.config（命名空间：upex.trigger，Key：tpx.config）",
    L("signupOpen: Boolean 报名全局开关，false时所有报名请求被拦截") +
    L("rankOpen: Boolean 排行榜展示开关") +
    L("supportSymbols: String 允许交易的全量symbolId（三品类并集，逗号分隔）") +
    L("  — 合约侧通过TraderProConfig#getAccountSupportSymbols读取，用于校验下单权限，必须配置") +
    L("maxLeverage: Int 统一最大杠杆倍数，默认20，合约侧校验用") +
    L("cryptoSymbolIds: String 虚拟货币品类symbolId列表，逗号分隔") +
    L("metalSymbolIds: String 贵金属品类symbolId列表，逗号分隔") +
    L("stockSymbolIds: String 股票品类symbolId列表，逗号分隔") +
    L("  — 三者之和应等于supportSymbols; TraderProXCategoryRouter热更新") +
    L("riskCheckIntervalSeconds: Int 风控检查间隔，默认3600秒") +
    L("snapshotBatchSize: Int ROI快照Job每批处理用户数，默认200") +
    L("historyPositionPageSize: Int 查历史仓位每页条数，默认500") +
    L("rewardActivityId: Long 活动ID，0表示未配置") +
    L("rewardSource: Int 来源标识（TicketSourceEnum整型值）"),
    L("配置变更需热更新：TraderProXConfig注册addChangeListener支持动态生效") +
    L("supportSymbols缺失或为空时，用户无法下单（关键配置，上线前必须验证）") +
    L("cryptoSymbolIds+metalSymbolIds+stockSymbolIds的并集应等于supportSymbols") +
    L("读取方式：TraceConfigUtils.getTraderProXConfig()")
)

ap_reward = REF("AP-02", "tpx.reward.* 发奖配置",
    L("tpx.reward.tcid.crypto: String 虚拟货币品类券配置ID") +
    L("tpx.reward.tcid.metal: String 贵金属品类券配置ID") +
    L("tpx.reward.tcid.stock: String 股票品类券配置ID") +
    L("tpx.reward.tcid.all: String 综合榜券配置ID") +
    L("tpx.reward.activity_id: Long 活动ID") +
    L("tpx.reward.source: Int 来源标识（TicketSourceEnum整型值）"),
    L("结算Job调用grantPlan时使用这些配置项生成CouponGrantParam") +
    L("tcid对应管理后台创建的卡券配置，上线前必须配置正确") +
    L("activity_id和source影响券的分类和溯源，需提前与运营确认")
)

ap_risk = REF("AP-03", "tpx.risk.* 风控配置（Apollo兜底，risk_config字段优先）",
    L("tpx.risk.max_position_ratio: Decimal 最大仓位占比阈值") +
    L("（其他风控阈值通过tb_tpx_season.risk_config JSON字段配置）"),
    L("tb_tpx_season.risk_config优先级高于Apollo全局默认值") +
    L("TraderProXRiskCheckJob读取risk_config，Apollo作为fallback兜底")
)

mod_apollo = MOD("Apollo",
    "技术文档所有Apollo配置项汇总（命名空间：upex.trigger）",
    ap_main + ap_reward + ap_risk,
    6)

# ════════════════════════════════════════════════════════════════
# 7. Job
# ════════════════════════════════════════════════════════════════

job_season_status = REF("JOB-01", "TraderProXSeasonStatusJob（赛季状态机）",
    L("触发方式：Cron 0 * * * * ?（每分钟）") +
    L("功能：扫描赛季状态，驱动未开始→进行中→已结束") +
    L("触发发奖：activity_end_time到达时触发TraderProXSettlementJob（一次性）") +
    L("站内信：activity_start_time → MSG_TPX_02；endTime-48h → MSG_TPX_04；endTime-24h → MSG_TPX_05；endTime → MSG_TPX_06") +
    L("MQ：发送TRADER_PRO_X_SEASON_STATUS_CHANGE消息"),
    L("状态流转时间误差：每分钟轮询，最大误差1分钟") +
    L("监控：赛季状态机流转失败触发钉钉+短信告警（trader_pro.season_status.fail）") +
    L("站内信触发时机需与PRD确认48h/24h提前量是否正确")
)

job_demo_compensate = REF("JOB-02", "TraderProXDemoAccountCompensateJob（Demo账户初始化补偿）",
    L("触发方式：Cron 0 */1 * * * ?（每分钟）") +
    L("功能：扫描tb_tpx_demo_account.status=INIT且create_time<now()-5s的记录") +
    L("新建场景：demo_user_id=null → 调用资产服务创建Demo子账户 → 回填demo_user_id → 充值10000") +
    L("复用场景：demo_user_id!=null → 调用资产服务重置余额为10000") +
    L("两种场景均更新status=INITED") +
    L("幂等：Redis分布式锁tpx:demo:init:lock:{userId}:{seasonId}，TTL=60s"),
    L("create_time<now()-5s的延迟扫描目的：等待事务提交完成") +
    L("监控：Demo账户初始化失败触发钉钉告警（trader_pro.demo_account.init_fail）") +
    L("幂等性验证：Job重跑时status=INITED的记录不会被重复处理")
)

job_roi_snapshot = REF("JOB-03", "TraderProXRoiSnapshotJob（ROI快照与排行榜更新）",
    L("触发方式：Cron 0 */30 * * * ?（每30分钟）") +
    L("功能：批量查账户权益 → 增量更新tb_tpx_history_pnl → 计算品类ROI → 更新tb_tpx_rank_record") +
    L("增量查询：InnerHistoryPositionQueryFeignClient，lastEndId游标，startTime=signup_time") +
    L("浮动盈亏：InnerAccountFeignClient查positionDTOs.unrealised") +
    L("品类ROI = (cumulative_pnl + unrealised) / 10000") +
    L("综合ROI = (sum(balanceDTOs.usdtEquity) - 10000) / 10000") +
    L("乐观锁保护：UPDATE...WHERE version=? 防并发覆盖") +
    L("边界处理：season已结束时effectiveEndTime=activity_end_time，执行最终快照后final_snapshot_done=1"),
    L("snapshotBatchSize默认200，可通过Apollo动态调整") +
    L("symbolId不在任何品类配置中：只计入ALL，不计入分品类") +
    L("最终快照完成标记验证：final_snapshot_done=1后后续轮次跳过")
)

job_risk_check = REF("JOB-04", "TraderProXRiskCheckJob（异常仓位风控检测）",
    L("触发方式：Cron 0 0 * * * ?（每小时整点）") +
    L("检测规则1：持仓名义价值/账户余额 > max_position_ratio 连续2次触发") +
    L("检测规则2：同方向单品类持仓笔数超过刷单阈值") +
    L("首次触发：Redis写tpx:risk:suspect:{userId}:{seasonId}，TTL=2h") +
    L("连续触发：写tb_tpx_violation_suspect，等待人工审核"),
    L("riskCheckIntervalSeconds=3600，可通过Apollo动态调整") +
    L("监控：风控Job执行异常，连续2次失败触发钉钉告警（trader_pro.risk_check.error）") +
    L("误报解除：清除Redis标记，用户状态不受影响")
)

job_settlement = REF("JOB-05", "TraderProXSettlementJob（结算发奖）",
    L("触发方式：由TraderProXSeasonStatusJob在activity_end_time到达时触发（一次性）") +
    L("分布式锁：Redis SETNX tpx:settlement:lock:{seasonId}，TTL=30分钟") +
    L("奖励计算：读取rank_record active=1按ROI降序，匹配reward_config.categoryRewards/totalRewards") +
    L("写入CouponGrantRecord：调用couponUseService.grantPlan，ticketStatus=CAN_GRANT") +
    L("幂等：src_id已存在则跳过，tb_tpx_reward.src_id!=null判断") +
    L("站内信：获奖→MSG_TPX_08；未获奖→MSG_TPX_10"),
    L("监控：发奖失败>0触发告警；结算耗时>300s触发告警；锁抢占失败触发告警") +
    L("实际发券由现有compensateCouponRecordJob驱动（无需新增），与结算锁无关") +
    L("结算Job重跑安全：src_id幂等保证不重复计算奖励")
)

job_coupon_compensate = REF("JOB-06", "compensateCouponRecordJob（现有Job复用，异步发券）",
    L("触发方式：现有XxlJob定期执行（已在线上运行）") +
    L("功能：扫描CouponGrantRecord.status=CAN_GRANT/GRANT_ING，调用assets券系统API") +
    L("状态流转：CAN_GRANT → GRANT_ING → GRANT_SUCCESS / END（超阈值失败）") +
    L("加Redis分布式锁防并发"),
    L("无需新增，复用现有实现") +
    L("END状态记录需人工通过/inner/v1/traderPro/reward/retry触发重试") +
    L("监控：发奖失败笔数>0（trader_pro.reward.fail_count）触发钉钉+短信")
)

mod_job = MOD("Job",
    "技术文档所有定时任务汇总，含Cron表达式/触发条件/幂等机制/监控告警",
    job_season_status + job_demo_compensate + job_roi_snapshot + job_risk_check + job_settlement + job_coupon_compensate,
    0)

# ════════════════════════════════════════════════════════════════
# 组合并生成
# ════════════════════════════════════════════════════════════════
all_modules = (
    mod_web +
    mod_h5 +
    mod_server +
    mod_flow +
    mod_admin +
    mod_db +
    mod_apollo +
    mod_job
)

out = "/Users/xiaobu.lv/Downloads/TraderPro_S6_测试用例_v3.xmind"
build_xmind(out, "TraderPro S6 测试用例（完整版 v3）", all_modules)
