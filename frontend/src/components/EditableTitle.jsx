import React, { useEffect, useRef, useState } from "react";
import { Pencil } from "lucide-react";

const MAX_FONT_SIZE = 1.125;
const MIN_FONT_SIZE = 0.75;
const STEP = 0.0625;

export default function EditableTitle({ title, onEdit, className = "" }) {
  const containerRef = useRef(null);
  const titleRef = useRef(null);
  const [fontSize, setFontSize] = useState(MAX_FONT_SIZE);

  useEffect(() => {
    setFontSize(MAX_FONT_SIZE);
  }, [title]);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const fitTitle = () => {
      const titleElement = titleRef.current;
      if (!titleElement) return;
      const hasOverflow = titleElement.scrollWidth > titleElement.clientWidth + 1;
      if (hasOverflow && fontSize > MIN_FONT_SIZE) {
        setFontSize((current) => Math.max(MIN_FONT_SIZE, current - STEP));
      }
    };

    const observer = new ResizeObserver(() => requestAnimationFrame(fitTitle));
    observer.observe(container);
    fitTitle();
    return () => observer.disconnect();
  }, [fontSize]);

  return (
    <div ref={containerRef} className={`flex min-w-0 items-center gap-1 ${className}`}>
      <span
        ref={titleRef}
        className="min-w-0 flex-1 overflow-hidden text-ellipsis whitespace-nowrap font-display font-medium"
        style={{ fontSize: `${fontSize}rem` }}
        title={title}
      >
        {title}
      </span>
      {onEdit && (
        <button
          type="button"
          onClick={(event) => {
            event.stopPropagation();
            onEdit();
          }}
          className="btn-ghost shrink-0 p-1"
          title={`Rinomina ${title}`}
          aria-label={`Rinomina ${title}`}
        >
          <Pencil className="h-[1em] w-[1em]" />
        </button>
      )}
    </div>
  );
}
