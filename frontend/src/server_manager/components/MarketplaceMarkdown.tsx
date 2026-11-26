import { useState, type ImgHTMLAttributes } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize, { defaultSchema } from "rehype-sanitize";

const ALIGN_TAGS = [
  "div",
  "p",
  "h1",
  "h2",
  "h3",
  "h4",
  "h5",
  "h6",
  "table",
  "thead",
  "tbody",
  "tr",
  "td",
  "th",
  "img",
] as const;

const markdownSanitizeSchema = {
  ...defaultSchema,
  tagNames: [...(defaultSchema.tagNames ?? []), "center"],
  protocols: {
    ...(defaultSchema.protocols ?? {}),
    src: ["http", "https"],
    srcSet: ["http", "https"],
  },
  attributes: {
    ...(defaultSchema.attributes ?? {}),
    source: [
      ...(defaultSchema.attributes?.source ?? []),
      "src",
      "srcSet",
      "type",
      "media",
    ],
    ...Object.fromEntries(
      ALIGN_TAGS.map((tag) => [
        tag,
        [
          ...(defaultSchema.attributes?.[tag] ?? []),
          "align",
          ...(tag === "img" ? ["src", "srcSet", "alt", "title", "width", "height"] : []),
        ],
      ]),
    ),
  },
};

function normalizeImageSrc(src: string | undefined): string | undefined {
  if (!src) return undefined;
  const trimmed = src.trim();
  if (!trimmed) return undefined;
  if (trimmed.startsWith("//")) return `https:${trimmed}`;
  return trimmed;
}

function MarkdownImage({
  src,
  alt,
  ...props
}: ImgHTMLAttributes<HTMLImageElement>) {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  const resolvedSrc = normalizeImageSrc(src);
  const failed = Boolean(resolvedSrc && failedSrc === resolvedSrc);

  if (!resolvedSrc || failed) {
    return (
      <span
        data-testid="markdown-image-fallback"
        className="my-1.5 inline-flex items-center gap-1.5 rounded-lg border border-border-subtle bg-surface-muted px-2.5 py-1 text-xs text-text-muted align-middle"
      >
        <span>{alt?.trim() || "Image unavailable"}</span>
      </span>
    );
  }

  return (
    <img
      {...props}
      src={resolvedSrc}
      alt={alt ?? ""}
      loading="lazy"
      decoding="async"
      referrerPolicy="no-referrer"
      onError={() => setFailedSrc(resolvedSrc)}
      className="my-1.5 inline-block max-w-full h-auto rounded-lg align-middle"
    />
  );
}

const markdownComponents: Components = {
  img: ({ node: _node, ...props }) => <MarkdownImage key={props.src} {...props} />,
  table: ({ node: _node, children, ...props }) => (
    <div className="my-4 w-full overflow-x-auto rounded-lg border border-border-subtle shadow-2xs">
      <table {...props} className="my-0 w-full border-collapse text-sm">
        {children}
      </table>
    </div>
  ),
  thead: ({ node: _node, ...props }) => (
    <thead {...props} className="bg-surface-muted/70 text-left" />
  ),
  th: ({ node: _node, ...props }) => (
    <th
      {...props}
      className="border-b border-border-subtle px-3.5 py-2.5 text-xs font-bold uppercase tracking-wide text-text-secondary"
    />
  ),
  tr: ({ node: _node, ...props }) => (
    <tr {...props} className="border-b border-border-subtle last:border-b-0" />
  ),
  td: ({ node: _node, ...props }) => (
    <td {...props} className="px-3.5 py-2.5 align-middle text-text-primary" />
  ),
  pre: ({ node: _node, ...props }) => (
    <pre
      {...props}
      className="my-4 overflow-x-auto rounded-lg border border-border-subtle bg-terminal-bg p-4 text-xs text-terminal-text [&>code]:border-0 [&>code]:bg-transparent [&>code]:p-0 [&>code]:text-inherit"
    />
  ),
  code: ({ node: _node, className = "", ...props }) => (
    <code
      {...props}
      className={`rounded-md border border-border-subtle bg-surface-muted px-1.5 py-0.5 font-mono text-[0.85em] font-medium text-text-primary break-words ${className}`}
    />
  ),
  details: ({ node: _node, ...props }) => (
    <details
      {...props}
      className="my-3 rounded-lg border border-border-subtle bg-surface-page/50 px-4 py-2.5"
    />
  ),
  summary: ({ node: _node, ...props }) => (
    <summary
      {...props}
      className="cursor-pointer select-none py-1 text-sm font-semibold text-text-primary hover:text-text-accent transition-colors"
    />
  ),
  blockquote: ({ node: _node, ...props }) => (
    <blockquote
      {...props}
      className="my-4 border-l-4 border-border-strong bg-surface-muted/40 px-4 py-2 rounded-r-lg text-text-secondary"
    />
  ),
  hr: ({ node: _node, ...props }) => (
    <hr {...props} className="my-6 border-border-subtle" />
  ),
  a: ({ node: _node, href, children, ...props }) => {
    const isExternal = typeof href === "string" && /^https?:\/\//i.test(href);
    return (
      <a
        {...props}
        href={href}
        target={isExternal ? "_blank" : undefined}
        rel={isExternal ? "noopener noreferrer" : undefined}
        className="text-text-accent hover:underline break-words"
      >
        {children}
      </a>
    );
  },
};

export interface MarketplaceMarkdownProps {
  content: string;
  className?: string;
}

export function MarketplaceMarkdown({ content, className = "" }: MarketplaceMarkdownProps) {
  return (
    <div
      className={`onx-markdown prose prose-sm max-w-none prose-code:before:content-none prose-code:after:content-none ${className}`}
    >
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        rehypePlugins={[rehypeRaw, [rehypeSanitize, markdownSanitizeSchema]]}
        components={markdownComponents}
      >
        {content}
      </ReactMarkdown>
    </div>
  );
}
