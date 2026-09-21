/**
 * Some agent outputs use `[Source 1]`, `[Source 2]`, etc. as plain text instead of
 * `[Source N](url)` markdown. When the same document also lists the URLs in a
 * References / Sources block or in `Source N: …` + `URL:` lines, we map numbers to
 * URLs and turn those into real markdown links so ReactMarkdown renders <a> tags.
 */

function stripUrlTrailingPunct(u: string): string {
  return u.replace(/[.,;)\]}»]+$/, '');
}

/**
 * Build N → url from common patterns in the markdown body.
 */
function extractSourceNumberToUrl(md: string): Map<number, string> {
  const map = new Map<number, string>();

  const set = (n: number, url: string) => {
    const u = stripUrlTrailingPunct(url.trim());
    if (u.startsWith('http://') || u.startsWith('https://')) {
      if (!map.has(n)) map.set(n, u);
    }
  };

  // "Source 1: ..." followed by "URL: https://..." (research data blocks, snippets)
  const sourceUrlBlock = /Source\s*(\d+)\s*:\s*[^\n]*\s*\n\s*URL:\s*(https?:\/\/[^\s]+)/gim;
  for (const m of md.matchAll(sourceUrlBlock)) {
    set(parseInt(m[1]!, 10), m[2]!);
  }

  // Single-line "Source 1: https://..." or "Source 1 - https://..."
  const sourceInline = /Source\s*(\d+)\s*[:：\-–—]\s*(https?:\/\/[^\s)\]]+)/gi;
  for (const m of md.matchAll(sourceInline)) {
    set(parseInt(m[1]!, 10), m[2]!);
  }

  // Reference-style definitions: [1]: https://... or  [^1]: https://
  const refDef = /^\[(\d+)\]:\s*(https?:\/\/\S+)/gim;
  for (const m of md.matchAll(refDef)) {
    set(parseInt(m[1]!, 10), m[2]!);
  }

  // Block starting at References / Sources / etc.
  const refHeader =
    /(?:^|\n)#{1,3}\s*(References?|Sources?|Source\s*links?|Source\s*list|Works?\s+cited|Bibliography|Further\s+reading|Footnotes?|Citations?)\b[^\n]*\n/i;
  const refMatch = md.match(refHeader);
  if (refMatch && refMatch.index !== undefined) {
    const refBlock = md.slice(refMatch.index);
    // "1. [Title](https://...)"
    const numMdLink = /^\s*(\d+)[.)\s]+\[([^\]]*)\]\((https?:\/\/[^)]+)\)/gim;
    for (const m of refBlock.matchAll(numMdLink)) {
      set(parseInt(m[1]!, 10), m[3]!);
    }
    // "1. https://..." or "1) https://"
    const numBareUrl = /^\s*(\d+)[.)\s]+(https?:\/\/[^\s)\],]+)/gim;
    for (const m of refBlock.matchAll(numBareUrl)) {
      set(parseInt(m[1]!, 10), m[2]!);
    }
  }

  return map;
}

/**
 * Replace bare `[Source N]` (not already `[Source N](url)`) with markdown links
 * when a URL is known for N.
 */
export function linkifySourceCitations(content: string): string {
  if (!content || !/Source\s*\d+/i.test(content)) return content;

  const numberToUrl = extractSourceNumberToUrl(content);
  if (numberToUrl.size === 0) return content;

  return content.replace(
    /\[Source\s*(\d+)\](?![\s]*\()/gi,
    (full, numStr: string) => {
      const n = parseInt(numStr, 10);
      const url = numberToUrl.get(n);
      if (!url) return full;
      return `[Source ${n}](${url})`;
    },
  );
}
