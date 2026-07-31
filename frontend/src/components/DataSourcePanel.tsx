import React, { useState } from 'react'

interface DataSource {
  name: string
  description: string
  module: string
  confidence: number
  url?: string
}

const DATA_SOURCES: DataSource[] = [
  { name: 'PubChem', description: '化合物结构/理化性质/生物活性', module: '产品基本信息', confidence: 100, url: 'https://pubchem.ncbi.nlm.nih.gov/' },
  { name: 'DrugBank', description: '药物靶点/药理/药代', module: '产品基本信息', confidence: 95, url: 'https://go.drugbank.com/' },
  { name: 'Wikipedia', description: '药物综合百科（作用机制/适应症/历史）', module: '产品基本信息', confidence: 85 },
  { name: 'FDA UNII', description: '唯一成分标识码及商品名', module: '产品基本信息/国际监管情况', confidence: 100, url: 'https://precision.fda.gov/uniisearch' },
  { name: 'ChEMBL', description: '生物活性数据库/靶点信息', module: '产品基本信息', confidence: 95, url: 'https://www.ebi.ac.uk/chembl/' },
  { name: 'DailyMed', description: 'FDA 批准的药品说明书', module: '产品基本信息', confidence: 98, url: 'https://dailymed.nlm.nih.gov/dailymed/' },
  { name: 'FDA Drugs@FDA', description: 'FDA 药品审批历史', module: '产品基本信息/国际监管情况', confidence: 98, url: 'https://www.accessdata.fda.gov/scripts/cder/daf/' },
  { name: 'FDA FAERS', description: '不良事件报告系统', module: '产品基本信息', confidence: 90 },
  { name: 'Drugs.com', description: '专业药物信息平台', module: '产品基本信息', confidence: 80, url: 'https://www.drugs.com/' },
  { name: 'EMA', description: '欧洲药品管理局审批信息', module: '国际监管情况', confidence: 98, url: 'https://www.ema.europa.eu/' },
  { name: 'PMDA', description: '日本药品医疗器械管理局', module: '国际监管情况', confidence: 95, url: 'https://www.pmda.go.jp/english/' },
  { name: 'CDE', description: '国家药品监督管理局药审中心', module: '国内登记情况', confidence: 95, url: 'http://www.cde.org.cn/' },
  { name: '药智网', description: '国内药品注册/申报信息', module: '国内登记情况', confidence: 85, url: 'https://www.yaozh.com/' },
  { name: 'FDA IIG', description: '非活性成分指南（辅料专用）', module: '监管与上市', confidence: 98, url: 'https://www.accessdata.fda.gov/scripts/cder/iig/' },
  { name: 'ClinicalTrials.gov', description: '全球临床试验注册库', module: '临床试验', confidence: 98, url: 'https://clinicaltrials.gov/' },
  { name: 'PubMed', description: '生命科学文献数据库', module: '文献与研究', confidence: 95, url: 'https://pubmed.ncbi.nlm.nih.gov/' },
  { name: 'Espacenet', description: '欧洲专利局专利数据库', module: '专利信息', confidence: 90, url: 'https://worldwide.espacenet.com/' },
  { name: 'CNIPA', description: '国家知识产权局专利检索', module: '专利信息', confidence: 90, url: 'https://www.cnipa.gov.cn/' },
  { name: 'Google Patents', description: '全球专利搜索引擎（兜底）', module: '专利信息', confidence: 80, url: 'https://patents.google.com/' },
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
        数据源清单（19个权威来源）
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
        数据源清单（19个权威来源）
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
                    <div style={{ color: '#e6edf3', fontWeight: 500 }}>
                      {ds.name}
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
