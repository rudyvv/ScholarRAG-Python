/**
 * Markdown rendering with code syntax highlighting.
 *
 * Uses markdown-it for parsing and highlight.js for code blocks.
 */

import MarkdownIt from 'markdown-it'
import hljs from 'highlight.js'
import 'highlight.js/styles/github.css'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  typographer: true,
  breaks: true,
  highlight(str: string, lang: string): string {
    if (lang && hljs.getLanguage(lang)) {
      try {
        const highlighted = hljs.highlight(str, { language: lang, ignoreIllegals: true }).value
        return (
          '<div class="code-block-wrapper">' +
          '<button class="code-copy-btn" onclick="' +
          "navigator.clipboard.writeText(" + JSON.stringify(str) + ")" +
          '.then(() => { this.textContent = \'已复制\'; setTimeout(() => { this.textContent = \'复制\' }, 2000) })' +
          '.catch(() => { this.textContent = \'失败\' })' +
          '">复制</button>' +
          `<pre><code class="hljs language-${lang}">${highlighted}</code></pre>` +
          '</div>'
        )
      } catch {
        // fall through
      }
    }
    // Fallback: escape and wrap
    const escaped = str
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
    return `<pre><code class="hljs">${escaped}</code></pre>`
  },
})

/**
 * Render markdown text to HTML with syntax highlighting.
 */
export function renderMarkdown(text: string): string {
  if (!text) return ''
  return md.render(text)
}
