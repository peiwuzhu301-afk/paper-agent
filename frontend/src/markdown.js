// 轻量 Markdown 渲染器（无第三方依赖，先转义再套样式，避免 XSS）
function escapeHtml(value) {
  return String(value)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

function escapeAttr(value) {
  return escapeHtml(value).replace(/'/g, '&#39;')
}

// 行内公式 $...$ / \(...\) 与独立公式 $$...$$ / \[...\]
const MATH_RE = /(\$\$[^$]+\$\$|\$[^$\n]+\$|\\\[[^\]]+\\\]|\\\([^)]+\\\))/g

function inline(text) {
  const store = []
  const protectedText = String(text).replace(MATH_RE, (match) => {
    store.push(match)
    return `\u0000M${store.length - 1}\u0000`
  })
  let out = escapeHtml(protectedText)
  out = out.replace(/`([^`]+)`/g, '<code>$1</code>')
  out = out.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
  out = out.replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<em>$2</em>')
  out = out.replace(
    /\[([^\]]+)\]\((https?:[^)\s]+)\)/g,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  )
  // 引用标记 [P1] 渲染成小徽章
  out = out.replace(/\[(P\d+)\]/g, '<span class="cite">[$1]</span>')
  // 还原公式：交给 KaTeX 渲染
  out = out.replace(/\u0000M(\d+)\u0000/g, (match, index) => {
    const raw = store[Number(index)] || ''
    let display = false
    let latex = raw
    if (raw.startsWith('$$') && raw.endsWith('$$')) {
      display = true
      latex = raw.slice(2, -2)
    } else if (raw.startsWith('\\[') && raw.endsWith('\\]')) {
      display = true
      latex = raw.slice(2, -2)
    } else if (raw.startsWith('\\(') && raw.endsWith('\\)')) {
      latex = raw.slice(2, -2)
    } else if (raw.startsWith('$') && raw.endsWith('$')) {
      latex = raw.slice(1, -1)
    }
    return display
      ? `<span class="math-tex math-block-src" data-tex="${escapeAttr(latex)}"></span>`
      : `<span class="math-tex" data-tex="${escapeAttr(latex)}"></span>`
  })
  return out
}

function splitRow(line) {
  return line
    .trim()
    .replace(/^\|/, '')
    .replace(/\|$/, '')
    .split('|')
    .map((cell) => cell.trim())
}

export function renderMarkdown(markdown) {
  if (!markdown) return ''
  const lines = String(markdown).replace(/\r\n/g, '\n').split('\n')
  const out = []
  let inCode = false
  let headingSeq = 0
  let codeBuf = []
  let listType = null
  let para = []

  const flushPara = () => {
    if (para.length) {
      out.push(`<p>${inline(para.join(' '))}</p>`)
      para = []
    }
  }
  const closeList = () => {
    if (listType) {
      out.push(`</${listType}>`)
      listType = null
    }
  }

  let i = 0
  while (i < lines.length) {
    const line = lines[i]

    if (/^\s*```/.test(line)) {
      if (inCode) {
        out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`)
        codeBuf = []
        inCode = false
      } else {
        flushPara()
        closeList()
        inCode = true
      }
      i += 1
      continue
    }
    if (inCode) {
      codeBuf.push(line)
      i += 1
      continue
    }

    // 表格
    if (
      /^\s*\|.*\|\s*$/.test(line) &&
      i + 1 < lines.length &&
      /^\s*\|?[\s:|-]+\|?\s*$/.test(lines[i + 1]) &&
      lines[i + 1].includes('-')
    ) {
      flushPara()
      closeList()
      const header = splitRow(line)
      const rows = []
      i += 2
      while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
        rows.push(splitRow(lines[i]))
        i += 1
      }
      let html = '<table><thead><tr>'
      html += header.map((cell) => `<th>${inline(cell)}</th>`).join('')
      html += '</tr></thead><tbody>'
      html += rows
        .map((row) => `<tr>${row.map((cell) => `<td>${inline(cell)}</td>`).join('')}</tr>`)
        .join('')
      html += '</tbody></table>'
      out.push(html)
      continue
    }

    const heading = /^(#{1,6})\s+(.*)$/.exec(line)
    if (heading) {
      flushPara()
      closeList()
      const level = heading[1].length
      headingSeq += 1
      out.push(`<h${level} id="h${headingSeq}">${inline(heading[2])}</h${level}>`)
      i += 1
      continue
    }

    const blockMath = /^\s*(?:\$\$(.+)\$\$|\\\[(.+)\\\])\s*$/.exec(line)
    if (blockMath) {
      flushPara()
      closeList()
      const tex = (blockMath[1] ?? blockMath[2] ?? '').trim()
      out.push(`<div class="math-block" data-tex="${escapeAttr(tex)}"></div>`)
      i += 1
      continue
    }

    if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
      flushPara()
      closeList()
      out.push('<hr/>')
      i += 1
      continue
    }

    if (/^\s*>\s?/.test(line)) {
      flushPara()
      closeList()
      const quote = []
      while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
        quote.push(lines[i].replace(/^\s*>\s?/, ''))
        i += 1
      }
      out.push(`<blockquote>${inline(quote.join(' '))}</blockquote>`)
      continue
    }

    const ul = /^\s*[-*+]\s+(.*)$/.exec(line)
    const ol = /^\s*\d+[.)]\s+(.*)$/.exec(line)
    if (ul) {
      flushPara()
      if (listType !== 'ul') {
        closeList()
        out.push('<ul>')
        listType = 'ul'
      }
      out.push(`<li>${inline(ul[1])}</li>`)
      i += 1
      continue
    }
    if (ol) {
      flushPara()
      if (listType !== 'ol') {
        closeList()
        out.push('<ol>')
        listType = 'ol'
      }
      out.push(`<li>${inline(ol[1])}</li>`)
      i += 1
      continue
    }

    if (/^\s*$/.test(line)) {
      flushPara()
      closeList()
      i += 1
      continue
    }

    para.push(line.trim())
    i += 1
  }

  if (inCode) out.push(`<pre><code>${escapeHtml(codeBuf.join('\n'))}</code></pre>`)
  flushPara()
  closeList()
  return out.join('\n')
}
