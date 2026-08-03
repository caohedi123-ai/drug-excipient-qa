import React, { useState } from 'react'

type SourceKind = '官方API' | '网络检索' | '综合检索'

interface DataSource {
  name: string
  description: string
  module: string
  confidence: number
  kind: SourceKind
  url?: string
}

// 置信度与后端 backend/tools/sources/excipient_basic_info.py 的 CONFIDENCE 字典对齐。
// 官方 API 直连=高（≥85）；网络检索兜底=低（40–60）；LLM 解析=中（70）。
const DATA_SOURCES: DataSource[] = [
  { name: 'PubChem', description: '化合物结构/理化性质/生物活性（官方 API）', module: '产品基本信息', confidence: 100, kind: '官方API', url: 'https://pubchem.ncbi.nlm.nih.gov/' },
  { name: 'DrugBank', description: '药物靶点/药理/药代（域名搜索，非官方 API）', module: '产品基本信息', confidence: 50, kind: '网络检索', url: 'https://go.drugbank.com/' },
  { name: 'Wikipedia', description: '药物综合百科（通用百科，非专业权威）', module: '产品基本信息', confidence: 60, kind: '网络检索' },
  { name: 'FDA UNII', description: '唯一成分标识码及商品名（官方 API）', module: '产品基本信息/国际监管情况', confidence: 100, kind: '官方API', url: 'https://precision.fda.gov/uniisearch' },
  { name: 'ChEMBL', description: '生物活性/靶点/作用机制/ADMET（官方 API，经 ChEMBL MCP）', module: '产品基本信息', confidence: 88, kind: '官方API', url: 'https://www.ebi.ac.uk/chembl/' },
  { name: 'DailyMed', description: 'FDA 批准的药品说明书（官方标签 API）', module: '产品基本信息', confidence: 95, kind: '官方API', url: 'https://dailymed.nlm.nih.gov/dailymed/' },
  { name: 'FDA Drugs@FDA', description: 'FDA 药品审批历史（官方 API）', module: '产品基本信息/国际监管情况', confidence: 100, kind: '官方API', url: 'https://www.accessdata.fda.gov/scripts/cder/daf/' },
  { name: 'FDA FAERS', description: '不良事件报告系统（官方 API）', module: '产品基本信息', confidence: 90, kind: '官方API' },
  { name: 'Drugs.com', description: '专业药物信息平台（域名搜索，非官方 API）', module: '产品基本信息', confidence: 50, kind: '网络检索', url: 'https://www.drugs.com/' },
  { name: 'EMA', description: '欧洲药品管理局审评信息（联网搜索）', module: '国际监管情况', confidence: 55, kind: '网络检索', url: 'https://www.ema.europa.eu/' },
  { name: 'PMDA', description: '日本药品医疗器械管理局（联网搜索）', module: '国际监管情况', confidence: 50, kind: '网络检索', url: 'https://www.pmda.go.jp/english/' },
  { name: 'CDE', description: '国家药监局药审中心登记信息（联网搜索）', module: '国内登记情况', confidence: 50, kind: '网络检索', url: 'http://www.cde.org.cn/' },
  { name: '药智网', description: '国内药品注册/申报信息（域名搜索，非官方 API）', module: '国内登记情况', confidence: 50, kind: '网络检索', url: 'https://www.yaozh.com/' },
  { name: 'FDA IIG', description: '非活性成分指南（辅料专用，官方 API）', module: '监管与上市', confidence: 100, kind: '官方API', url: 'https://www.accessdata.fda.gov/scripts/cder/iig/' },
  { name: 'ClinicalTrials.gov', description: '全球临床试验注册库（官方 API）', module: '临床试验', confidence: 90, kind: '官方API', url: 'https://clinicaltrials.gov/' },
  { name: 'PubMed', description: '生命科学文献数据库（官方 API）', module: '文献与研究', confidence: 85, kind: '官方API', url: 'https://pubmed.ncbi.nlm.nih.gov/' },
  { name: 'Espacenet', description: '欧洲专利局专利（联网搜索，非官方专利库）', module: '专利信息', confidence: 45, kind: '网络检索', url: 'https://worldwide.espacenet.com/' },
  { name: 'CNIPA', description: '国家知识产权局专利（联网搜索，非官方专利库）', module: '专利信息', confidence: 50, kind: '网络检索', url: 'https://www.cnipa.gov.cn/' },
  { name: 'PubChem（专利交叉引用）', description: '化合物专利网络交叉引用（已按同族去重）', module: '专利信息', confidence: 70, kind: '网络检索', url: 'https://pubchem.ncbi.nlm.nih.gov/' },
]

const moduleColors: Record<string, string> = {
  '产品基本信息': '#58a6ff',
  '国际监管情况': '#3fb950',
  '国内登记情况': '#d29922',
  '监管与上市': '#bc8cff',
  '临床试验': '#f78166',
  '文献与研究': '#db61a2',
  '专利信息': '#7ee787',
}

const kindColors: Record<SourceKind, string> = {
  '官方API': '#3fb950',
  '网络检索': '#d29922',
  '综合检索': '#bc8cff',
}

const DataSourcePanel: React.FC<{ defaultExpanded?: boolean }> = ({ defaultExpanded = false }) => {
  const [expanded, setExpanded] = useState(defaultExpanded)
  if (!expanded) {
    return (
      <button onClick={() => setExpanded(true)}
        style={{
          background: 'linear-gradient(135deg, rgba(31,111,235,0.12) 0%, rgba(88,166,255,0.06) 100%)',
          border: '1px solid rgba(48,54,61,0.6)',
          borderRadius: 8,
          padding: '10px 16px',
          color: '#8b949e',
          fontSize: 13,
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          width: '100%',
          transition: 'border-color 0.2s',
        }}
        onMouseEnter={e => (e.currentTarget.style.borderColor = '#58a6ff')}
        onMouseLeave={e => (e.currentTarget.style.borderColor = 'rgba(48,54,61,0.6)')}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
        数据源清单（19个数据来源）
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ marginLeft: 'auto' }}>
          <path d="M9 18l6-6-6-6"/>
        </svg>
      </button>
    )
  }

  return (
    <div style={{
      background: 'rgba(13,17,23,0.9)',
      border: '1px solid #21262d',
      borderRadius: 10,
      overflow: 'hidden',
    }}>
      {/* 头部 */}
      <button onClick={() => setExpanded(false)}
        style={{
          width: '100%',
          background: 'linear-gradient(135deg, #1f6feb 0%, #388bfd 100%)',
          border: 'none',
          padding: '12px 16px',
          display: 'flex',
          alignItems: 'center',
          gap: 8,
          cursor: 'pointer',
          color: 'white',
          fontSize: 14,
          fontWeight: 600,
        }}
      >
        <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5">
          <circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>
        </svg>
        数据源清单（19个数据来源）
        <span style={{ marginLeft: 'auto', fontSize: 12, opacity: 0.8 }}>
          {DATA_SOURCES.length} 源
        </span>
        <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" style={{ transform: 'rotate(90deg)' }}>
          <path d="M9 18l6-6-6-6"/>
        </svg>
      </button>

      {/* 内容 */}
      <div style={{ padding: '12px 16px', maxHeight: 360, overflowY: 'auto' }}>
        {/* 模块分组 */}
        {['产品基本信息', '国内登记情况', '国际监管情况', '监管与上市', '临床试验', '文献与研究', '专利信息'].map(moduleName => {
          const sources = DATA_SOURCES.filter(s => s.module === moduleName || s.module.includes(moduleName))
          if (sources.length === 0) return null
          const color = moduleColors[moduleName] || '#8b949e'
          return (
            <div key={moduleName} style={{ marginBottom: 14 }}>
              <div style={{
                color,
                fontSize: 11,
                fontWeight: 600,
                textTransform: 'uppercase',
                letterSpacing: '0.06em',
                marginBottom: 8,
                paddingBottom: 6,
                borderBottom: '1px solid #21262d',
              }}>
                {moduleName}（{sources.length} 源）
              </div>
              {sources.map(ds => (
                <div key={ds.name}
                  style={{
                    display: 'flex',
                    alignItems: 'flex-start',
                    gap: 8,
                    padding: '6px 0',
                    fontSize: 12,
                  }}
                >
                  <span style={{
                    flexShrink: 0,
                    background: `${color}20`,
                    color,
                    padding: '1px 6px',
                    borderRadius: 4,
                    fontSize: 10,
                    fontWeight: 600,
                  }}>{ds.confidence}%</span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ color: '#e6edf3', fontWeight: 500, display: 'flex', alignItems: 'center', gap: 6 }}>
                      {ds.name}
                      <span style={{
                        flexShrink: 0,
                        background: `${kindColors[ds.kind]}22`,
                        color: kindColors[ds.kind],
                        padding: '0 5px',
                        borderRadius: 3,
                        fontSize: 10,
                        fontWeight: 500,
                      }}>{ds.kind}</span>
                    </div>
                    <div style={{ color: '#8b949e', fontSize: 11, marginTop: 2 }}>
                      {ds.description}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}

export default DataSourcePanel
