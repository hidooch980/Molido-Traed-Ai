/**
 * The account number as a Code 39 barcode, drawn inline.
 *
 * Seven terminals whose logins differ by one digit in the middle is a table
 * nobody can read down. `111926958` and `111927791` are the same shape at a
 * glance, and telling them apart is exactly what somebody is doing when they
 * open this page - which terminal is this, and is it the one I just changed.
 * A barcode is a different shape for every number, so the eye separates the
 * rows before it has read a single digit.
 *
 * Code 39 rather than the denser symbologies: it needs no checksum, encodes
 * digits directly, and every phone scanner reads it. The number stays printed
 * beside it, because a barcode nobody can verify by eye is a picture.
 *
 * Drawn as SVG rather than fetched from a generator. A remote image would put
 * every account number this deployment holds into somebody else's request log,
 * which is a strange price for a decoration.
 */

/**
 * Code 39, as nine elements per character - bar, space, bar, space and so on,
 * beginning and ending with a bar. Exactly three of the nine are wide, which
 * is the property that makes the symbology self-checking.
 */
const CODE39: Record<string, string> = {
  "0": "nnnwwnwnn",
  "1": "wnnwnnnnw",
  "2": "nnwwnnnnw",
  "3": "wnwwnnnnn",
  "4": "nnnwwnnnw",
  "5": "wnnwwnnnn",
  "6": "nnwwwnnnn",
  "7": "nnnwnnwnw",
  "8": "wnnwnnwnn",
  "9": "nnwwnnwnn",
  A: "wnnnnwnnw",
  B: "nnwnnwnnw",
  C: "wnwnnwnnn",
  D: "nnnnwwnnw",
  E: "wnnnwwnnn",
  F: "nnwnwwnnn",
  G: "nnnnnwwnw",
  H: "wnnnnwwnn",
  I: "nnwnnwwnn",
  J: "nnnnwwwnn",
  K: "wnnnnnnww",
  L: "nnwnnnnww",
  M: "wnwnnnnwn",
  N: "nnnnwnnww",
  O: "wnnnwnnwn",
  P: "nnwnwnnwn",
  Q: "nnnnnnwww",
  R: "wnnnnnwwn",
  S: "nnwnnnwwn",
  T: "nnnnwnwwn",
  U: "wwnnnnnnw",
  V: "nwwnnnnnw",
  W: "wwwnnnnnn",
  X: "nwnnwnnnw",
  Y: "wwnnwnnnn",
  Z: "nwwnwnnnn",
  "-": "nwnnnnwnw",
  ".": "wwnnnnwnn",
  " ": "nwwnnnwnn",
  // Start and stop. Never part of the payload, always around it.
  "*": "nwnnwnwnn",
};

/** Wide elements are three narrow ones. The looser 2:1 ratio is legal and
 *  scans worse on a screen, where a narrow bar is already close to one pixel. */
const WIDE = 3;
const NARROW = 1;

type Bar = { x: number; width: number };

/**
 * The bars of one payload, in narrow-element units, with the start and stop
 * characters added. Spaces are the gaps left between them, so only the bars
 * need drawing.
 */
function bars(payload: string): { bars: Bar[]; width: number } {
  const drawn: Bar[] = [];
  let x = 0;
  const characters = `*${payload}*`.split("");

  characters.forEach((character, index) => {
    const pattern = CODE39[character];
    // An unencodable character is dropped rather than guessed at. Substituting
    // one would produce a barcode that scans cleanly to the wrong number,
    // which is worse than a shorter one.
    if (!pattern) return;

    pattern.split("").forEach((element, position) => {
      const width = element === "w" ? WIDE : NARROW;
      // Even positions are bars, odd ones are spaces.
      if (position % 2 === 0) drawn.push({ x, width });
      x += width;
    });

    // One narrow space between characters, and none after the last.
    if (index < characters.length - 1) x += NARROW;
  });

  return { bars: drawn, width: x };
}

export default function AccountBarcode({
  value,
  height = 26,
  title,
}: {
  value: string;
  height?: number;
  title?: string;
}) {
  // Code 39 has no lower case. Upper-casing is the encoding's own rule rather
  // than a display choice, so it happens here and not in the caller.
  const payload = String(value ?? "").toUpperCase();
  const { bars: drawn, width } = bars(payload);
  if (!drawn.length) return null;

  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      // Fixed height, width from the content: a ten digit login and a six
      // digit one are different widths, and stretching them to match would
      // make the narrow bars different sizes between rows and stop both
      // scanning.
      height={height}
      width={width}
      role="img"
      aria-label={title ?? payload}
      // The bars are the ink of the surrounding text, so the code follows the
      // viewer's theme without being told which one is active.
      fill="currentColor"
      style={{ display: "block", shapeRendering: "crispEdges", maxWidth: "100%" }}
    >
      <title>{title ?? payload}</title>
      {drawn.map((bar) => (
        <rect key={bar.x} x={bar.x} y={0} width={bar.width} height={height} />
      ))}
    </svg>
  );
}
