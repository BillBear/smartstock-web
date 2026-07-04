export function getAIDecisionTerminology({ decisionSource } = {}) {
  const isCoachAligned = decisionSource === 'coach_service'
  if (isCoachAligned) {
    return {
      panelTitle: '智能选股决策（小白版）',
      decisionLabel: '智能选股动作',
      confidenceLabel: '参考信心度',
      confidenceProgressPrefix: '参考信心',
      probabilityTitle: '参考概率',
      probabilityHelp: '来自智能选股上下文，仅用于观察和模拟验证，不代表已校准胜率。',
    }
  }
  return {
    panelTitle: 'AI智能决策（小白版）',
    decisionLabel: 'AI最终决策',
    confidenceLabel: '信心度',
    confidenceProgressPrefix: 'AI信心度',
    probabilityTitle: '实现概率',
    probabilityHelp: '',
  }
}
