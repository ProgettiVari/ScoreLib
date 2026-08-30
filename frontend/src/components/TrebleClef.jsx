import React from "react";

/**
 * Treble Clef — minimal, monochrome SVG.
 * Pure black, hairline strokes. Replaces the piano-bars logo.
 */
export default function TrebleClef({ size = 28, color = "currentColor", className = "", strokeWidth = 1.5 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 32"
      fill="none"
      xmlns="http://www.w3.org/2000/svg"
      className={className}
      aria-label="Scorelib"
    >
      <path
        d="M12 1.5c-2.6 0-3.9 2.4-3.9 4.6 0 2.4 1.2 4.6 2.5 6.7-1.4 1.7-3.6 4-3.6 7.6 0 4 3.1 7.4 7 7.4 3 0 5-1.9 5-4.5 0-2.4-1.6-4.2-3.7-4.2-1.7 0-3 1.2-3 2.8 0 1.3 1 2.3 2.2 2.3.4 0 .8-.1 1.1-.3-.3 1-1.3 1.7-2.6 1.7-2.4 0-4.2-2.1-4.2-4.7 0-2.6 1.8-4.6 3.1-6.1.6 1 1.2 2.1 1.7 3.4.7 1.9 1 3.8 1 5.7 0 2-.4 3.4-1.4 4.5-.7.7-1.4 1-2 1-.5 0-.9-.2-.9-.5 0-.2.1-.3.3-.5.5-.4.7-.9.7-1.5 0-1-.8-1.7-1.7-1.7-1 0-1.8.9-1.8 2 0 1.7 1.5 3 3.6 3 3.1 0 5.4-2.6 5.4-7 0-2.5-.5-5-1.4-7.2-.7-1.7-1.5-3.2-2.3-4.5 1-1.6 1.7-3.2 1.7-5.1 0-2.6-1.5-4.9-3.8-4.9zm0 1.6c1.2 0 2.1 1.4 2.1 3.3 0 1.4-.5 2.7-1.3 4-.7-1.3-1.4-2.7-1.4-4.4 0-1.7.5-2.9 0.6-2.9z"
        fill={color}
        stroke={color}
        strokeWidth={strokeWidth * 0.3}
      />
    </svg>
  );
}

/** White variant for dark backgrounds (auth shell). */
export function TrebleClefWhite({ size = 28, className = "" }) {
  return <TrebleClef size={size} color="#FFFFFF" className={className} />;
}
