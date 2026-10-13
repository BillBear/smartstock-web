export function formatOptionalNumber(value, digits = 2) {
  if (value === null || value === undefined || value === '' || !Number.isFinite(Number(value))) return '未知'
  return Number(value).toFixed(digits)
}

export function quoteDescription(record) {
  const source = record.quote_source || '来源未记录'
  const time = record.quote_time || '时间未记录'
  return `${record.quote_status === 'latest_session' ? '最近交易日行情' : '行情未核验'} · ${source} · ${time}`
}
