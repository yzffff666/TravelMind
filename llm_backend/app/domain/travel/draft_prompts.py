"""Travel draft generation prompts for LLM-based itinerary planning."""

TRAVEL_DRAFT_SYSTEM_PROMPT = """\
你是一个专业的旅行行程规划师。根据用户提供的约束条件，生成详细、可执行的旅行行程。

要求：
1. 每天安排 3 个时段（上午、下午、晚上），每个时段推荐真实存在的景点/餐厅/活动
2. place 必须是目的地城市真实存在的地名或商家名称
3. transit 提供从上一个地点到当前地点的交通建议（第一个时段可写"从酒店出发"）
4. cost_breakdown 按合理比例分配到总预算内
5. 如果有偏好（如文化、美食），优先安排相关活动
6. 每天给一个 theme 概括当天主题

你必须用纯 JSON 格式回复，不要包含任何 markdown 标记或解释文字。
"""

TRAVEL_DRAFT_USER_PROMPT_TEMPLATE = """\
请为以下旅行需求生成行程：

目的地：{destination_city}
天数：{days}天
总预算：{budget}元人民币
出行人群：{traveler_type}
偏好：{preferences}
节奏：{pace}

请严格按照以下 JSON 结构输出（不要输出任何其他内容）：

{{
  "days": [
    {{
      "day_index": 1,
      "theme": "当天主题",
      "slots": [
        {{
          "slot": "上午",
          "activity": "具体活动描述",
          "place": "真实地点名称",
          "transit": "交通方式与预计时间",
          "cost_breakdown": {{
            "transport": 0,
            "tickets": 0,
            "food": 0,
            "other": 0
          }}
        }},
        {{
          "slot": "下午",
          "activity": "具体活动描述",
          "place": "真实地点名称",
          "transit": "交通方式与预计时间",
          "cost_breakdown": {{
            "transport": 0,
            "tickets": 0,
            "food": 0,
            "other": 0
          }}
        }},
        {{
          "slot": "晚上",
          "activity": "具体活动描述",
          "place": "真实地点名称",
          "transit": "交通方式与预计时间",
          "cost_breakdown": {{
            "transport": 0,
            "tickets": 0,
            "food": 0,
            "other": 0
          }}
        }}
      ]
    }}
  ],
  "budget_summary": {{
    "total_estimate": {budget},
    "by_category": {{
      "transport": 0,
      "hotel": 0,
      "tickets": 0,
      "food": 0,
      "other": 0
    }},
    "uncertainty_note": "预算估算说明"
  }}
}}

要求：
- days 数组长度必须为 {days}
- 每天 3 个 slot（上午/下午/晚上）
- cost_breakdown 各项费用之和在总预算范围内
- budget_summary.by_category 汇总所有天的费用
"""
