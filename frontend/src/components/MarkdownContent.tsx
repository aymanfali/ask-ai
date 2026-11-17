import { Fragment, useState, type ReactNode } from "react";
import { Icon } from "./Icon";

function safeHref(value: string): string | null {
  try {
    const url = new URL(value, window.location.origin);
    if (["https:", "http:", "mailto:"].includes(url.protocol)) return value;
  } catch {
    return null;
  }
  return null;
}

function InlineMarkdown({ text }: { text: string }) {
  const pattern = /(\*\*[^*]+\*\*|~~[^~]+~~|\*[^*]+\*|`[^`]+`|\[[^\]]+\]\([^)]+\))/g;
  const parts = text.split(pattern);
  return <>{parts.map((part, index) => {
    if (part.startsWith("**") && part.endsWith("**")) return <strong key={index}>{part.slice(2, -2)}</strong>;
    if (part.startsWith("~~") && part.endsWith("~~")) return <del key={index}>{part.slice(2, -2)}</del>;
    if (part.startsWith("*") && part.endsWith("*")) return <em key={index}>{part.slice(1, -1)}</em>;
    if (part.startsWith("`") && part.endsWith("`")) return <code className="inline-code" key={index}>{part.slice(1, -1)}</code>;
    const linkMatch = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (linkMatch) {
      const href = safeHref(linkMatch[2]);
      return href ? <a key={index} href={href} target="_blank" rel="noreferrer noopener">{linkMatch[1]}</a> : <Fragment key={index}>{linkMatch[1]}</Fragment>;
    }
    return <Fragment key={index}>{part}</Fragment>;
  })}</>;
}

function CodeBlock({ language, code }: { language: string; code: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1400);
    } catch {
      setCopied(false);
    }
  };
  return (
    <div className="code-block">
      <div className="code-block__bar">
        <span><Icon name="code" size={14}/>{language || "Code"}</span>
        <button type="button" className="code-copy" onClick={copy} aria-label="Copy code">
          <Icon name={copied ? "check" : "copy"} size={14}/>{copied ? "Copied" : "Copy"}
        </button>
      </div>
      <pre><code>{code}</code></pre>
    </div>
  );
}

export function MarkdownContent({ content }: { content: string }) {
  const normalized = content.replace(/\r\n/g, "\n");
  const lines = normalized.split("\n");
  const blocks: ReactNode[] = [];
  let paragraph: string[] = [];
  let index = 0;
  const flushParagraph = () => {
    if (paragraph.length) {
      blocks.push(<p key={`p-${index++}`}><InlineMarkdown text={paragraph.join(" ")}/></p>);
      paragraph = [];
    }
  };

  while (index < lines.length) {
    const line = lines[index];
    const fence = line.match(/^```([^`]*)$/);
    if (fence) {
      flushParagraph();
      const language = fence[1].trim();
      const codeLines: string[] = [];
      index += 1;
      while (index < lines.length && !/^```\s*$/.test(lines[index])) {
        codeLines.push(lines[index]);
        index += 1;
      }
      blocks.push(<CodeBlock key={`code-${index}`} language={language} code={codeLines.join("\n")}/>);
      index += 1;
      continue;
    }
    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushParagraph();
      const size = heading[1].length;
      const text = <InlineMarkdown text={heading[2]}/>;
      if (size === 1) blocks.push(<h2 key={`h-${index}`}>{text}</h2>);
      else if (size === 2) blocks.push(<h3 key={`h-${index}`}>{text}</h3>);
      else blocks.push(<h4 key={`h-${index}`}>{text}</h4>);
      index += 1;
      continue;
    }
    if (/^\s*[-*]\s+/.test(line)) {
      flushParagraph();
      const items: string[] = [];
      while (index < lines.length && /^\s*[-*]\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*[-*]\s+/, ""));
        index += 1;
      }
      blocks.push(<ul key={`ul-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown text={item}/></li>)}</ul>);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      flushParagraph();
      const items: string[] = [];
      while (index < lines.length && /^\s*\d+\.\s+/.test(lines[index])) {
        items.push(lines[index].replace(/^\s*\d+\.\s+/, ""));
        index += 1;
      }
      blocks.push(<ol key={`ol-${index}`}>{items.map((item, itemIndex) => <li key={itemIndex}><InlineMarkdown text={item}/></li>)}</ol>);
      continue;
    }
    if (/^>\s?/.test(line)) {
      flushParagraph();
      const quote: string[] = [];
      while (index < lines.length && /^>\s?/.test(lines[index])) {
        quote.push(lines[index].replace(/^>\s?/, ""));
        index += 1;
      }
      blocks.push(<blockquote key={`q-${index}`}>{quote.join(" ")}</blockquote>);
      continue;
    }
    if (line.trim() === "") {
      flushParagraph();
      index += 1;
      continue;
    }
    paragraph.push(line.trim());
    index += 1;
  }
  flushParagraph();

  return <div className="markdown-content">{blocks}</div>;
}
