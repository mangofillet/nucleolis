/* Nucleolis identity.
 *
 * The mark is five overlapping translucent petals around a solid nucleus, with
 * two elliptical orbits carrying node dots - a nucleolus seen as an orbital
 * system. It is drawn rather than imported so the lockups stay crisp at every
 * size and the reverse-on-dark variant needs no second asset.
 *
 * `tone` selects the lockup from the brand sheet:
 *   ink      - on light backgrounds (default)
 *   reverse  - on dark backgrounds
 *   mono     - single colour, inherits currentColor
 */

type Tone = "ink" | "reverse" | "mono";

const PETAL_ANGLES = [0, 72, 144, 216, 288];

function palette(tone: Tone) {
  if (tone === "mono") {
    return {
      petal: "currentColor",
      petalOpacity: 0.16,
      nucleus: "currentColor",
      orbit: "currentColor",
      orbitOpacity: 0.55,
      dot: "currentColor",
      halo: "none",
    };
  }
  if (tone === "reverse") {
    return {
      petal: "#d6eef0",
      petalOpacity: 0.22,
      nucleus: "#f8fafc",
      orbit: "#9fb3c2",
      orbitOpacity: 0.85,
      dot: "#d6eef0",
      halo: "#0f1f2b",
    };
  }
  return {
    petal: "#8ea6bd",
    petalOpacity: 0.3,
    nucleus: "#0b121a",
    orbit: "#56697c",
    orbitOpacity: 0.9,
    dot: "#0b121a",
    halo: "#ffffff",
  };
}

export function NucleolisMark({ size = 32, tone = "ink" }: { size?: number; tone?: Tone }) {
  const c = palette(tone);
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 64 64"
      fill="none"
      aria-hidden="true"
      focusable="false"
    >
      <g>
        {PETAL_ANGLES.map((angle) => {
          const rad = ((angle - 90) * Math.PI) / 180;
          return (
            <circle
              key={angle}
              cx={32 + Math.cos(rad) * 10.5}
              cy={32 + Math.sin(rad) * 10.5}
              r="16.5"
              fill={c.petal}
              fillOpacity={c.petalOpacity}
            />
          );
        })}
      </g>

      {/* orbits - drawn over the petals, under the nucleus */}
      <g stroke={c.orbit} strokeOpacity={c.orbitOpacity} strokeWidth="1.1" fill="none">
        <ellipse cx="32" cy="32" rx="29" ry="12" transform="rotate(28 32 32)" />
        <ellipse cx="32" cy="32" rx="29" ry="12" transform="rotate(-34 32 32)" />
      </g>

      {/* orbit nodes, positioned on each ellipse */}
      <g fill={c.dot}>
        <circle cx="6.9" cy="45.6" r="2.5" />
        <circle cx="57.1" cy="18.4" r="2.5" />
        <circle cx="9.9" cy="19.6" r="2.2" />
        <circle cx="54.1" cy="44.4" r="2.2" />
      </g>

      {/* nucleus, with a halo so the orbits do not run through it */}
      {c.halo !== "none" && <circle cx="32" cy="32" r="10.5" fill={c.halo} />}
      <circle cx="32" cy="32" r="8.4" fill={c.nucleus} />
    </svg>
  );
}

export function NucleolisLockup({
  size = 30,
  tone = "ink",
  showWordmark = true,
}: {
  size?: number;
  tone?: Tone;
  showWordmark?: boolean;
}) {
  return (
    <span className="lockup" aria-label="Nucleolis">
      <NucleolisMark size={size} tone={tone} />
      {showWordmark && (
        <span className="lockup__word" style={{ fontSize: size * 0.64 }}>
          Nucleolis
        </span>
      )}
    </span>
  );
}

export default NucleolisLockup;
